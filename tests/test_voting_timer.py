import asyncio
import pytest

from app.enums import Gender, ParticipantStatus, PlayerRole, RoomState, UserState, VoteChoice
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.room_state_service import room_state_service
from app.services.voting_service import voting_service


def _setup_room(db, audience_count: int = 5) -> tuple[Room, User, list[User]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
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

    db.commit()
    db.refresh(room)
    return room, challenger, audience


@pytest.mark.asyncio
async def test_voting_timer_auto_finalizes_and_eliminates_non_voters(client, db):
    room, challenger, audience = _setup_room(db, audience_count=5)

    # Transition to VOTING using state service
    await room_state_service.transition(db, room.id, RoomState.VOTING)

    # Override timer with very short duration for fast test
    voting_service.start_voting_timer(room.id, room.current_round, duration_seconds=0.1)

    # Only 2 out of 5 users vote YES; 3 users disconnect/stall
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[0].id, "vote": "yes"})
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[1].id, "vote": "yes"})

    # Wait for the timer to expire
    await asyncio.sleep(0.25)

    db.refresh(room)
    assert room.state == RoomState.ONE_ON_ONE

    # Check survivors
    p0 = db.get(RoomParticipant, (room.id, audience[0].id))
    p1 = db.get(RoomParticipant, (room.id, audience[1].id))
    assert p0.status == ParticipantStatus.ACTIVE
    assert p0.left_at is None
    assert p1.status == ParticipantStatus.ACTIVE
    assert p1.left_at is None

    # Check unvoted participants were eliminated and re-queued
    for user in audience[2:]:
        p = db.get(RoomParticipant, (room.id, user.id))
        assert p.status == ParticipantStatus.ELIMINATED
        assert p.left_at is not None

        db.refresh(user)
        assert user.state == UserState.QUEUED
        assert user.queued_at is not None


@pytest.mark.asyncio
async def test_early_all_votes_cancels_timer_and_transitions(client, db):
    room, challenger, audience = _setup_room(db, audience_count=2)

    await room_state_service.transition(db, room.id, RoomState.VOTING)

    # Start long timer
    voting_service.start_voting_timer(room.id, room.current_round, duration_seconds=10.0)
    assert room.id in voting_service._timers

    # Both users vote YES immediately
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[0].id, "vote": "yes"})
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[1].id, "vote": "yes"})

    db.refresh(room)
    assert room.state == RoomState.ONE_ON_ONE

    # Timer should be cancelled and cleaned up
    assert room.id not in voting_service._timers


@pytest.mark.asyncio
async def test_voting_timer_single_survivor_goes_to_final(client, db):
    room, challenger, audience = _setup_room(db, audience_count=3)

    await room_state_service.transition(db, room.id, RoomState.VOTING)
    voting_service.start_voting_timer(room.id, room.current_round, duration_seconds=0.1)

    # 1 votes YES, 1 votes NO, 1 stalls
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[0].id, "vote": "yes"})
    client.post(f"/rooms/{room.id}/vote", json={"user_id": audience[1].id, "vote": "no"})

    await asyncio.sleep(0.25)

    db.refresh(room)
    assert room.state == RoomState.ONE_ON_ONE


@pytest.mark.asyncio
async def test_voting_timer_zero_survivors_goes_to_completed(client, db):
    room, challenger, audience = _setup_room(db, audience_count=3)

    await room_state_service.transition(db, room.id, RoomState.VOTING)
    voting_service.start_voting_timer(room.id, room.current_round, duration_seconds=0.1)

    # Nobody votes YES (all stall)
    await asyncio.sleep(0.25)

    db.refresh(room)
    assert room.state == RoomState.COMPLETED

    # Check challenger was evicted and re-queued
    db.refresh(challenger)
    assert challenger.state == UserState.QUEUED
    assert challenger.queued_at is not None

    p_challenger = db.get(RoomParticipant, (room.id, challenger.id))
    assert p_challenger.status == ParticipantStatus.ELIMINATED
    assert p_challenger.left_at is not None
