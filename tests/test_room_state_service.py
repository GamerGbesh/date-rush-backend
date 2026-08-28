import pytest
from unittest.mock import AsyncMock, patch

from app.enums import Gender, PlayerRole, RoomState, UserState
from app.exceptions import InvalidRoomTransitionError, RoomNotFoundError
from app.models.room import Room, RoomParticipant
from app.models.room_state_history import RoomStateHistory
from app.models.user import User
from app.services.room_state_service import VALID_TRANSITIONS, room_state_service


def _create_test_room(db, initial_state: RoomState = RoomState.READY) -> Room:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience1 = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    audience2 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, audience1, audience2])
    db.commit()

    room = Room(
        state=initial_state,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=0,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    db.add(RoomParticipant(room_id=room.id, user_id=audience1.id, role=PlayerRole.AUDIENCE))
    db.add(RoomParticipant(room_id=room.id, user_id=audience2.id, role=PlayerRole.AUDIENCE))
    db.commit()
    db.refresh(room)
    return room


class TestValidTransitions:
    @pytest.mark.asyncio
    async def test_full_room_lifecycle(self, db):
        room = _create_test_room(db, RoomState.READY)
        assert room.state == RoomState.READY
        assert room.current_round == 0

        with patch("app.services.room_state_service.ws_manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
            # READY -> INTRO
            room = await room_state_service.transition(db, room.id, RoomState.INTRO)
            assert room.state == RoomState.INTRO
            assert room.current_round == 0
            mock_broadcast.assert_awaited_with(
                room.id,
                {"type": "room_state_changed", "room_id": room.id, "previous_state": "ready", "state": "intro"},
            )

            # INTRO -> QUESTIONING (round becomes 1)
            room = await room_state_service.transition(db, room.id, RoomState.QUESTIONING)
            assert room.state == RoomState.QUESTIONING
            assert room.current_round == 1

            # QUESTIONING -> VOTING
            room = await room_state_service.transition(db, room.id, RoomState.VOTING)
            assert room.state == RoomState.VOTING
            assert room.current_round == 1

            # VOTING -> ELIMINATION
            room = await room_state_service.transition(db, room.id, RoomState.ELIMINATION)
            assert room.state == RoomState.ELIMINATION
            assert room.current_round == 1

            # ELIMINATION -> QUESTIONING (round increments to 2)
            room = await room_state_service.transition(db, room.id, RoomState.QUESTIONING)
            assert room.state == RoomState.QUESTIONING
            assert room.current_round == 2

            # QUESTIONING -> VOTING
            room = await room_state_service.transition(db, room.id, RoomState.VOTING)
            assert room.state == RoomState.VOTING
            assert room.current_round == 2

            # VOTING -> ELIMINATION
            room = await room_state_service.transition(db, room.id, RoomState.ELIMINATION)
            assert room.state == RoomState.ELIMINATION

            # ELIMINATION -> FINAL
            room = await room_state_service.transition(db, room.id, RoomState.FINAL)
            assert room.state == RoomState.FINAL
            assert room.current_round == 2

            # FINAL -> MATCHED
            room = await room_state_service.transition(db, room.id, RoomState.MATCHED)
            assert room.state == RoomState.MATCHED

            # MATCHED -> COMPLETED
            room = await room_state_service.transition(db, room.id, RoomState.COMPLETED)
            assert room.state == RoomState.COMPLETED


class TestInvalidTransitions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("current_state", "target_state"),
        [
            (RoomState.READY, RoomState.VOTING),
            (RoomState.READY, RoomState.MATCHED),
            (RoomState.READY, RoomState.QUESTIONING),
            (RoomState.INTRO, RoomState.VOTING),
            (RoomState.QUESTIONING, RoomState.COMPLETED),
            (RoomState.QUESTIONING, RoomState.INTRO),
            (RoomState.QUESTIONING, RoomState.MATCHED),
            (RoomState.VOTING, RoomState.QUESTIONING),
            (RoomState.COMPLETED, RoomState.QUESTIONING),
            (RoomState.COMPLETED, RoomState.READY),
        ],
    )
    async def test_invalid_transition_raises_domain_error(self, db, current_state, target_state):
        room = _create_test_room(db, current_state)
        with pytest.raises(InvalidRoomTransitionError) as exc_info:
            await room_state_service.transition(db, room.id, target_state)
        
        assert exc_info.value.from_state == current_state.value
        assert exc_info.value.to_state == target_state.value
        assert "Invalid room transition" in exc_info.value.message


class TestTransitionHistory:
    @pytest.mark.asyncio
    async def test_records_history_per_transition(self, db):
        room = _create_test_room(db, RoomState.READY)

        with patch("app.services.room_state_service.ws_manager.broadcast", new_callable=AsyncMock):
            await room_state_service.transition(db, room.id, RoomState.INTRO)
            await room_state_service.transition(db, room.id, RoomState.QUESTIONING)
            await room_state_service.transition(db, room.id, RoomState.VOTING)

        history = room_state_service.get_history(db, room.id)
        assert len(history) == 3

        assert history[0].from_state == RoomState.READY
        assert history[0].to_state == RoomState.INTRO

        assert history[1].from_state == RoomState.INTRO
        assert history[1].to_state == RoomState.QUESTIONING

        assert history[2].from_state == RoomState.QUESTIONING
        assert history[2].to_state == RoomState.VOTING


class TestRoomNotFound:
    @pytest.mark.asyncio
    async def test_transition_nonexistent_room_raises_404(self, db):
        with pytest.raises(RoomNotFoundError):
            await room_state_service.transition(db, 99999, RoomState.INTRO)


class TestEliminationStateDetermination:
    def test_more_than_one_audience_routes_to_questioning(self, db):
        room = _create_test_room(db, RoomState.ELIMINATION)
        next_state = room_state_service.determine_next_elimination_state(db, room)
        assert next_state == RoomState.QUESTIONING

    def test_single_audience_routes_to_final(self, db):
        room = _create_test_room(db, RoomState.ELIMINATION)
        # Mark one audience member as having left
        audience_participants = [p for p in room.participants if p.role == PlayerRole.AUDIENCE]
        audience_participants[0].left_at = db.get(User, audience_participants[0].user_id).created_at
        db.commit()
        db.refresh(room)

        next_state = room_state_service.determine_next_elimination_state(db, room)
        assert next_state == RoomState.FINAL
