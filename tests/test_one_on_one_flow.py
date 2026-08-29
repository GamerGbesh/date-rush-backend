import pytest

from app.enums import (
    Gender,
    OneOnOneSessionState,
    ParticipantStatus,
    PlayerRole,
    RoomState,
    UserState,
    VoteChoice,
)
from app.models.one_on_one_session import OneOnOneSession
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.one_on_one_service import one_on_one_service
from app.services.room_state_service import room_state_service


def _setup_one_on_one_room(db, count: int = 3) -> tuple[Room, User, list[User]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
        for i in range(count)
    ]
    db.add_all([challenger] + audience)
    db.commit()

    room = Room(
        state=RoomState.ELIMINATION,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
    )
    db.add(room)
    db.flush()

    db.add(
        RoomParticipant(
            room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER
        )
    )
    for a in audience:
        db.add(RoomParticipant(room_id=room.id, user_id=a.id, role=PlayerRole.AUDIENCE))

    db.commit()
    db.refresh(room)
    return room, challenger, audience


class TestOneOnOneFlow:
    @pytest.mark.asyncio
    async def test_full_sequential_one_on_one_flow(self, client, db):
        room, challenger, audience = _setup_one_on_one_room(db, count=3)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        sessions = (
            db.query(OneOnOneSession)
            .where(OneOnOneSession.room_id == room.id)
            .order_by(OneOnOneSession.sequence.asc())
            .all()
        )
        s1, s2, s3 = sessions

        # --- SESSION 1: Audience 0 asks, Challenger answers, Audience 0 votes YES ---
        # 1. Aud 0 asks question
        resp1 = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={
                "user_id": audience[0].id,
                "text": "What is your philosophy on life?",
            },
        )
        assert resp1.status_code == 201
        assert resp1.json()["question"] == "What is your philosophy on life?"

        # 2. Challenger answers
        resp2 = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/answer",
            json={
                "user_id": challenger.id,
                "text": "Always keep learning and growing.",
            },
        )
        assert resp2.status_code == 201
        assert resp2.json()["state"] == "voting"

        # 3. Aud 0 votes YES
        resp3 = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/vote",
            json={"user_id": audience[0].id, "vote": "yes"},
        )
        assert resp3.status_code == 201

        # Session 1 is COMPLETED, Session 2 is now ACTIVE
        db.refresh(s1)
        db.refresh(s2)
        assert s1.state == OneOnOneSessionState.COMPLETED
        assert s1.vote == VoteChoice.YES
        assert s2.state == OneOnOneSessionState.ACTIVE

        # --- SESSION 2: Audience 1 asks, Challenger answers, Audience 1 votes NO ---
        client.post(
            f"/rooms/{room.id}/one-on-one/{s2.id}/question",
            json={"user_id": audience[1].id, "text": "Do you like cats?"},
        )
        client.post(
            f"/rooms/{room.id}/one-on-one/{s2.id}/answer",
            json={"user_id": challenger.id, "text": "No, I am allergic."},
        )
        resp_vote2 = client.post(
            f"/rooms/{room.id}/one-on-one/{s2.id}/vote",
            json={"user_id": audience[1].id, "vote": "no"},
        )
        assert resp_vote2.status_code == 201

        # Audience 1 is ELIMINATED and QUEUED; Session 3 is now ACTIVE
        db.refresh(s2)
        db.refresh(s3)
        assert s2.state == OneOnOneSessionState.COMPLETED
        assert s2.vote == VoteChoice.NO

        p1 = db.get(RoomParticipant, (room.id, audience[1].id))
        assert p1.status == ParticipantStatus.ELIMINATED
        assert p1.left_at is not None

        u1 = db.get(User, audience[1].id)
        assert u1.state == UserState.WAITING

        assert s3.state == OneOnOneSessionState.ACTIVE

        # --- SESSION 3: Audience 2 asks, Challenger answers, Audience 2 votes YES ---
        client.post(
            f"/rooms/{room.id}/one-on-one/{s3.id}/question",
            json={"user_id": audience[2].id, "text": "What is your dream job?"},
        )
        client.post(
            f"/rooms/{room.id}/one-on-one/{s3.id}/answer",
            json={"user_id": challenger.id, "text": "Being an AI engineer."},
        )
        client.post(
            f"/rooms/{room.id}/one-on-one/{s3.id}/vote",
            json={"user_id": audience[2].id, "vote": "yes"},
        )

        # All sessions finished -> 2 survivors (Aud 0 and Aud 2) -> Room transitions to FINAL_SELECTION!
        db.refresh(room)
        assert room.state == RoomState.FINAL_SELECTION

    @pytest.mark.asyncio
    async def test_zero_survivors_transitions_to_completed(self, client, db):
        room, challenger, audience = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        sessions = (
            db.query(OneOnOneSession)
            .where(OneOnOneSession.room_id == room.id)
            .order_by(OneOnOneSession.sequence)
            .all()
        )

        # Both vote NO
        for idx, (s, aud) in enumerate(zip(sessions, audience)):
            client.post(
                f"/rooms/{room.id}/one-on-one/{s.id}/question",
                json={"user_id": aud.id, "text": f"Q{idx}"},
            )
            client.post(
                f"/rooms/{room.id}/one-on-one/{s.id}/answer",
                json={"user_id": challenger.id, "text": f"A{idx}"},
            )
            client.post(
                f"/rooms/{room.id}/one-on-one/{s.id}/vote",
                json={"user_id": aud.id, "vote": "no"},
            )

        db.refresh(room)
        assert room.state == RoomState.COMPLETED


class TestOneOnOneValidations:
    @pytest.mark.asyncio
    async def test_challenger_cannot_ask_question(self, client, db):
        room, challenger, _ = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
        s1 = one_on_one_service.get_active_session(db, room.id)

        resp = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": challenger.id, "text": "Challenger asking question"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_other_audience_cannot_ask_question_for_active_session(
        self, client, db
    ):
        room, _, audience = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
        s1 = one_on_one_service.get_active_session(db, room.id)

        # Audience 1 trying to ask in Audience 0's session
        resp = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": audience[1].id, "text": "Audience 1 intruding"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_audience_cannot_submit_answer(self, client, db):
        room, _, audience = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
        s1 = one_on_one_service.get_active_session(db, room.id)

        client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": audience[0].id, "text": "Valid question"},
        )

        resp = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/answer",
            json={"user_id": audience[0].id, "text": "Audience trying to answer"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_question_rejected(self, client, db):
        room, _, audience = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
        s1 = one_on_one_service.get_active_session(db, room.id)

        client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": audience[0].id, "text": "First question"},
        )
        resp2 = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": audience[0].id, "text": "Second question"},
        )
        assert resp2.status_code in (409, 422)

    @pytest.mark.asyncio
    async def test_empty_question_rejected(self, client, db):
        room, _, audience = _setup_one_on_one_room(db, count=2)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)
        s1 = one_on_one_service.get_active_session(db, room.id)

        resp = client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": audience[0].id, "text": "   "},
        )
        assert resp.status_code in (422, 400)
