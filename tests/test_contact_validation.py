import pytest

from app.enums import Gender, MatchRoomState, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.exceptions import (
    DuplicateContactSubmissionError,
    InvalidContactPayloadError,
    InvalidMatchRoomStateError,
    MatchRoomUnauthorizedError,
)
from app.models.match import Match
from app.models.match_room import MatchRoom
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.match_room_service import match_room_service
from app.services.match_service import match_service


def _setup_match_room(db) -> tuple[MatchRoom, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    outsider = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand, outsider])
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
    db.add(RoomParticipant(room_id=room.id, user_id=cand.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))
    db.commit()

    match = Match(room_id=room.id, challenger_id=challenger.id, audience_id=cand.id, status=MatchStatus.CREATED)
    db.add(match)
    db.commit()

    match_room = match_room_service.create_match_room(db, match.id)
    return match_room, challenger, cand, outsider


class TestContactValidation:
    @pytest.mark.asyncio
    async def test_valid_whatsapp_only(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        c = await match_room_service.submit_contact(
            db, mr.id, challenger.id, whatsapp="+233201234567", snapchat=None
        )
        assert c.whatsapp == "+233201234567"
        assert c.snapchat is None

    @pytest.mark.asyncio
    async def test_valid_snapchat_only(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        c = await match_room_service.submit_contact(
            db, mr.id, challenger.id, whatsapp=None, snapchat="ama_gh"
        )
        assert c.whatsapp is None
        assert c.snapchat == "ama_gh"

    @pytest.mark.asyncio
    async def test_valid_both(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        c = await match_room_service.submit_contact(
            db, mr.id, challenger.id, whatsapp="+233201234567", snapchat="ama_gh"
        )
        assert c.whatsapp == "+233201234567"
        assert c.snapchat == "ama_gh"

    @pytest.mark.asyncio
    async def test_empty_or_whitespace_rejected(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        with pytest.raises(InvalidContactPayloadError):
            await match_room_service.submit_contact(
                db, mr.id, challenger.id, whatsapp="   ", snapchat=""
            )

    @pytest.mark.asyncio
    async def test_oversized_contact_rejected(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        with pytest.raises(InvalidContactPayloadError):
            await match_room_service.submit_contact(
                db, mr.id, challenger.id, whatsapp="+" + "1" * 105, snapchat=None
            )

    @pytest.mark.asyncio
    async def test_duplicate_submission_rejected(self, db):
        mr, challenger, _, _ = _setup_match_room(db)
        await match_room_service.submit_contact(
            db, mr.id, challenger.id, whatsapp="+233201234567", snapchat=None
        )
        with pytest.raises(DuplicateContactSubmissionError):
            await match_room_service.submit_contact(
                db, mr.id, challenger.id, whatsapp="+233209999999", snapchat=None
            )

    @pytest.mark.asyncio
    async def test_unauthorized_user_rejected(self, db):
        mr, _, _, outsider = _setup_match_room(db)
        with pytest.raises(MatchRoomUnauthorizedError):
            await match_room_service.submit_contact(
                db, mr.id, outsider.id, whatsapp="+233201234567", snapchat=None
            )
