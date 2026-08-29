import pytest

from app.enums import Gender, OneOnOneSessionState, PlayerRole, RoomState, UserState
from app.models.one_on_one_session import OneOnOneSession
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.one_on_one_service import one_on_one_service
from app.services.room_state_service import room_state_service


def _seed_surviving_room(db) -> tuple[Room, User, list[User]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
        for i in range(3)
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

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    for a in audience:
        db.add(RoomParticipant(room_id=room.id, user_id=a.id, role=PlayerRole.AUDIENCE))

    db.commit()
    db.refresh(room)
    return room, challenger, audience


class TestOneOnOneCreation:
    @pytest.mark.asyncio
    async def test_transition_to_one_on_one_creates_sessions(self, db):
        room, challenger, audience = _seed_surviving_room(db)

        # Transition ELIMINATION -> ONE_ON_ONE
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        sessions = (
            db.query(OneOnOneSession)
            .where(OneOnOneSession.room_id == room.id)
            .order_by(OneOnOneSession.sequence.asc())
            .all()
        )

        assert len(sessions) == 3
        assert [s.sequence for s in sessions] == [1, 2, 3]

        # Session 1 is ACTIVE; 2 and 3 are PENDING
        assert sessions[0].state == OneOnOneSessionState.ACTIVE
        assert sessions[0].started_at is not None
        assert sessions[0].audience_id == audience[0].id
        assert sessions[0].challenger_id == challenger.id

        assert sessions[1].state == OneOnOneSessionState.PENDING
        assert sessions[1].started_at is None
        assert sessions[1].audience_id == audience[1].id

        assert sessions[2].state == OneOnOneSessionState.PENDING
        assert sessions[2].started_at is None
        assert sessions[2].audience_id == audience[2].id

    @pytest.mark.asyncio
    async def test_only_one_session_active_at_a_time(self, db):
        room, challenger, audience = _seed_surviving_room(db)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        active = one_on_one_service.get_active_session(db, room.id)
        assert active is not None
        assert active.sequence == 1
        assert active.audience_id == audience[0].id
