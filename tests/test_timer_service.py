"""
Comprehensive unit tests for the standalone TimerService and phase-specific timeout behaviors.
"""

import asyncio
from datetime import datetime, timezone
import pytest

from app.enums import (
    Gender,
    MatchStatus,
    OneOnOneSessionState,
    ParticipantStatus,
    PlayerRole,
    QuestionPhase,
    QuestionTarget,
    RoomState,
    UserState,
    VoteChoice,
)
from app.models.answer import Answer
from app.models.match import Match
from app.models.one_on_one_session import OneOnOneSession
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.room_question import RoomQuestion
from app.models.user import User
from app.services.match_service import match_service
from app.services.one_on_one_service import one_on_one_service
from app.services.questioning_service import questioning_service
from app.services.room_state_service import room_state_service
from app.services.timer_service import timer_service
from app.services.voting_service import voting_service


def _create_sample_room(db, audience_count: int = 3) -> tuple[Room, User, list[User]]:
    challenger = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.FEMALE, state=UserState.IN_GAME)
        for i in range(audience_count)
    ]
    db.add_all([challenger] + audience)
    db.commit()

    room = Room(
        state=RoomState.QUESTIONING,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    for a in audience:
        db.add(RoomParticipant(room_id=room.id, user_id=a.id, role=PlayerRole.AUDIENCE))

    # Add 3 questions for questioning
    questions = list(db.query(Question).filter(Question.active.is_(True)).limit(3).all())
    for pos, q in enumerate(questions, start=1):
        db.add(RoomQuestion(room_id=room.id, question_id=q.id, position=pos, phase=QuestionPhase.PUBLIC))

    room.current_question_id = questions[0].id
    db.commit()
    db.refresh(room)
    return room, challenger, audience


@pytest.mark.asyncio
async def test_timer_service_start_get_and_cancel():
    """Verify timer start, get_timer_info countdown math, and clean cancel."""
    triggered = False

    async def _on_timeout():
        nonlocal triggered
        triggered = True

    timer_service.start_timer(
        room_id=999,
        timer_type="test_timer",
        duration_seconds=5.0,
        on_timeout=_on_timeout,
    )

    info = timer_service.get_timer_info(999)
    assert info["active"] is True
    assert info["timer_type"] == "test_timer"
    assert info["duration_seconds"] == 5.0
    assert 0 < info["remaining_seconds"] <= 5.0

    # Cancel timer
    cancelled = timer_service.cancel_timer(999)
    assert cancelled is True
    assert timer_service.get_timer_info(999)["active"] is False

    await asyncio.sleep(0.05)
    assert triggered is False


@pytest.mark.asyncio
async def test_timer_api_endpoint(client, db):
    """Verify GET /rooms/{room_id}/timer returns timer metadata."""
    room, challenger, audience = _create_sample_room(db)

    # When no timer active
    timer_service.cancel_timer(room.id)
    resp = client.get(f"/rooms/{room.id}/timer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["room_id"] == room.id
    assert data["active"] is False

    # When timer is started
    timer_service.start_timer(
        room_id=room.id,
        timer_type="questioning",
        duration_seconds=480.0,
        on_timeout=lambda: None,
    )
    resp = client.get(f"/rooms/{room.id}/timer")
    assert resp.status_code == 200
    data = resp.json()
    assert data["room_id"] == room.id
    assert data["active"] is True
    assert data["timer_type"] == "questioning"
    assert data["duration_seconds"] == 480.0
    assert 0 < data["remaining_seconds"] <= 480.0


@pytest.mark.asyncio
async def test_questioning_timeout_zero_answers_requeues_all(client, db):
    """If challenger answers 0 questions, challenger and audience are re-queued and room completes."""
    room, challenger, audience = _create_sample_room(db, audience_count=2)

    # Start short questioning timer (0.1s)
    questioning_service.start_questioning_timer(room.id, duration_seconds=0.1)

    # Wait for timer expiry
    await asyncio.sleep(0.2)

    db.refresh(room)
    assert room.state == RoomState.COMPLETED

    db.refresh(challenger)
    assert challenger.state == UserState.QUEUED
    assert challenger.queued_at is not None

    for a in audience:
        db.refresh(a)
        assert a.state == UserState.QUEUED
        assert a.queued_at is not None


@pytest.mark.asyncio
async def test_questioning_timeout_partial_answers_advances_to_voting(client, db):
    """If challenger answers 1 of 3 questions, remaining get '[No Response]' and room advances to VOTING."""
    room, challenger, audience = _create_sample_room(db, audience_count=2)

    # Challenger submits Answer 1
    client.post(
        f"/rooms/{room.id}/answers",
        json={"user_id": challenger.id, "answer": "I only answered Question 1"},
    )

    # Start questioning timer to trigger timeout for remaining
    questioning_service.start_questioning_timer(room.id, duration_seconds=0.1)

    await asyncio.sleep(0.2)

    db.refresh(room)
    assert room.state == RoomState.VOTING

    answers = list(db.query(Answer).filter(Answer.room_id == room.id).all())
    assert len(answers) == 3
    assert answers[0].answer == "I only answered Question 1"
    assert answers[1].answer == "[No Response]"
    assert answers[2].answer == "[No Response]"


@pytest.mark.asyncio
async def test_one_on_one_question_timeout_eliminates_audience(client, db):
    """If audience does not ask question in time, audience is eliminated and next session starts."""
    room, challenger, audience = _create_sample_room(db, audience_count=2)

    # Set room state to ELIMINATION so transition to ONE_ON_ONE is valid
    room.state = RoomState.ELIMINATION
    db.commit()

    # Transition to ONE_ON_ONE
    await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

    s1 = db.query(OneOnOneSession).filter(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()
    # Override question timer with short duration
    one_on_one_service.start_question_timer(room.id, s1.id, duration_seconds=0.1)

    await asyncio.sleep(0.2)

    db.refresh(s1)
    assert s1.state == OneOnOneSessionState.COMPLETED

    # First audience user was eliminated
    aud1 = db.get(User, s1.audience_id)
    assert aud1.state == UserState.QUEUED

    # Session 2 was activated
    s2 = db.query(OneOnOneSession).filter(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 2).one()
    assert s2.state == OneOnOneSessionState.ACTIVE


@pytest.mark.asyncio
async def test_one_on_one_answer_timeout_autofills_no_response_and_starts_vote(client, db):
    """If challenger does not answer private question in time, answer is '[No Response]' and vote timer starts."""
    room, challenger, audience = _create_sample_room(db, audience_count=1)

    room.state = RoomState.ELIMINATION
    db.commit()

    await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
    s1 = db.query(OneOnOneSession).filter(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()

    # Audience asks question
    client.post(
        f"/rooms/{room.id}/one-on-one/{s1.id}/question",
        json={"user_id": s1.audience_id, "text": "What is your favorite dish?"},
    )

    # Override answer timer with short duration
    one_on_one_service.start_answer_timer(room.id, s1.id, duration_seconds=0.1)

    await asyncio.sleep(0.2)

    db.refresh(s1)
    assert s1.state == OneOnOneSessionState.VOTING
    assert s1.answer == "[No Response]"


@pytest.mark.asyncio
async def test_one_on_one_vote_timeout_submits_no_vote(client, db):
    """If audience does not vote in time, vote is treated as NO and user is eliminated."""
    room, challenger, audience = _create_sample_room(db, audience_count=1)

    room.state = RoomState.ELIMINATION
    db.commit()

    await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
    s1 = db.query(OneOnOneSession).filter(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()

    client.post(
        f"/rooms/{room.id}/one-on-one/{s1.id}/question",
        json={"user_id": s1.audience_id, "text": "Question?"},
    )
    client.post(
        f"/rooms/{room.id}/one-on-one/{s1.id}/answer",
        json={"user_id": challenger.id, "text": "Answer!"},
    )

    # Override vote timer with short duration
    one_on_one_service.start_vote_timer(room.id, s1.id, duration_seconds=0.1)

    await asyncio.sleep(0.2)

    db.refresh(s1)
    assert s1.state == OneOnOneSessionState.COMPLETED
    assert s1.vote == VoteChoice.NO


@pytest.mark.asyncio
async def test_final_selection_timeout_auto_selects_first_finalist(client, db):
    """If challenger does not make final selection in time, first candidate is auto-selected."""
    room, challenger, audience = _create_sample_room(db, audience_count=2)

    # Mark both audience participants as FINALIST
    p1 = db.get(RoomParticipant, (room.id, audience[0].id))
    p2 = db.get(RoomParticipant, (room.id, audience[1].id))
    p1.status = ParticipantStatus.FINALIST
    p2.status = ParticipantStatus.FINALIST
    room.state = RoomState.ONE_ON_ONE
    db.commit()

    # Transition to FINAL_SELECTION
    await room_state_service.transition(db, room.id, RoomState.FINAL_SELECTION)

    # Override final selection timer with short duration
    match_service.start_final_selection_timer(room.id, duration_seconds=0.1)

    await asyncio.sleep(0.2)

    # Match was created
    match = db.query(Match).filter(Match.room_id == room.id).one()
    assert match.challenger_id == challenger.id
    assert match.audience_id == audience[0].id
    assert match.status == MatchStatus.CREATED
