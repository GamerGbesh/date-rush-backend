import pytest

from app.enums import Gender, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.exceptions import (
    FinalSelectionUnauthorizedError,
    InvalidFinalSelectionStateError,
    MatchAlreadyExistsError,
    NotEligibleFinalistError,
)
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.match_service import match_service


def _seed_final_selection_room(db) -> tuple[Room, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    cand2 = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand1, cand2])
    db.commit()

    room = Room(
        state=RoomState.FINAL_SELECTION,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    db.add(RoomParticipant(room_id=room.id, user_id=cand1.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))
    db.add(RoomParticipant(room_id=room.id, user_id=cand2.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))

    db.commit()
    db.refresh(room)
    return room, challenger, cand1, cand2


class TestMatchServiceValidations:
    @pytest.mark.asyncio
    async def test_challenger_can_select_valid_finalist(self, db):
        room, challenger, cand1, _ = _seed_final_selection_room(db)

        match = await match_service.create_match(
            db=db,
            room_id=room.id,
            challenger_id=challenger.id,
            candidate_id=cand1.id,
        )
        assert match.id is not None
        assert match.challenger_id == challenger.id
        assert match.audience_id == cand1.id
        assert match.status == MatchStatus.CREATED

    @pytest.mark.asyncio
    async def test_non_challenger_cannot_select(self, db):
        room, _, cand1, cand2 = _seed_final_selection_room(db)

        with pytest.raises(FinalSelectionUnauthorizedError):
            await match_service.create_match(
                db=db,
                room_id=room.id,
                challenger_id=cand1.id,
                candidate_id=cand2.id,
            )

    @pytest.mark.asyncio
    async def test_cannot_select_non_finalist_or_eliminated(self, db):
        room, challenger, cand1, _ = _seed_final_selection_room(db)

        # Non-finalist participant
        outsider = User(name="Outsider", gender=Gender.MALE, state=UserState.IN_GAME)
        db.add(outsider)
        db.commit()
        db.add(RoomParticipant(room_id=room.id, user_id=outsider.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.ELIMINATED))
        db.commit()

        with pytest.raises(NotEligibleFinalistError):
            await match_service.create_match(
                db=db,
                room_id=room.id,
                challenger_id=challenger.id,
                candidate_id=outsider.id,
            )

    @pytest.mark.asyncio
    async def test_challenger_cannot_select_self(self, db):
        room, challenger, _, _ = _seed_final_selection_room(db)

        with pytest.raises(NotEligibleFinalistError):
            await match_service.create_match(
                db=db,
                room_id=room.id,
                challenger_id=challenger.id,
                candidate_id=challenger.id,
            )

    @pytest.mark.asyncio
    async def test_cannot_select_twice_or_change_selection(self, db):
        room, challenger, cand1, cand2 = _seed_final_selection_room(db)

        await match_service.create_match(
            db=db,
            room_id=room.id,
            challenger_id=challenger.id,
            candidate_id=cand1.id,
        )

        with pytest.raises((InvalidFinalSelectionStateError, MatchAlreadyExistsError)):
            await match_service.create_match(
                db=db,
                room_id=room.id,
                challenger_id=challenger.id,
                candidate_id=cand2.id,
            )
