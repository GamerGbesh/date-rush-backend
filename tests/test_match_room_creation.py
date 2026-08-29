import pytest

from app.enums import Gender, MatchRoomState, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.exceptions import MatchRoomNotFoundError, MatchRoomUnauthorizedError
from app.models.match import Match
from app.models.match_room import MatchRoom
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.match_room_service import match_room_service
from app.services.match_service import match_service


def _seed_completed_match(db) -> tuple[Match, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    outsider = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand1, outsider])
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
    db.commit()
    db.refresh(room)
    return room, challenger, cand1, outsider


class TestMatchRoomCreation:
    @pytest.mark.asyncio
    async def test_match_creation_creates_private_match_room(self, db):
        room, challenger, cand1, outsider = _seed_completed_match(db)

        match = await match_service.create_match(
            db=db,
            room_id=room.id,
            challenger_id=challenger.id,
            candidate_id=cand1.id,
        )

        # Verify MatchRoom created
        match_room = db.query(MatchRoom).where(MatchRoom.match_id == match.id).one()
        assert match_room.state == MatchRoomState.WAITING_FOR_CONTACTS
        assert match_room.created_at is not None
        assert match_room.completed_at is None

        # Verify authorization
        # Challenger and cand1 can access
        mr_chal = match_room_service.get_match_room_for_user(db, match_room.id, challenger.id)
        assert mr_chal.id == match_room.id

        mr_cand = match_room_service.get_match_room_for_user(db, match_room.id, cand1.id)
        assert mr_cand.id == match_room.id

        # Outsider is rejected
        with pytest.raises(MatchRoomUnauthorizedError):
            match_room_service.get_match_room_for_user(db, match_room.id, outsider.id)

    def test_non_existent_match_room_raises_404(self, db):
        with pytest.raises(MatchRoomNotFoundError):
            match_room_service.get_match_room(db, 99999)
