import pytest

from app.enums import Gender, MatchRoomState, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.exceptions import UserAlreadyCompletedEventError
from app.models.match import Match
from app.models.match_room import MatchRoom
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.match_room_service import match_room_service
from app.services.match_service import match_service
from app.services.queue_manager import queue_manager


def _seed_match_for_flow(db) -> tuple[MatchRoom, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand])
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
    return match_room, challenger, cand


class TestContactExchangeFlow:
    @pytest.mark.asyncio
    async def test_full_contact_exchange_and_user_completion(self, client, db):
        mr, challenger, cand = _seed_match_for_flow(db)

        # 1. Challenger submits WhatsApp
        resp_c1 = client.post(
            f"/match-rooms/{mr.id}/contacts",
            json={"user_id": challenger.id, "whatsapp": "+233201111111", "snapchat": None},
        )
        assert resp_c1.status_code == 201
        data_c1 = resp_c1.json()
        assert data_c1["state"] == "waiting_for_contacts"
        assert data_c1["submitted"] is True
        assert data_c1["partner"] is None  # Partner contact not revealed yet!

        # Challenger checks status before partner submission
        status_c1 = client.get(f"/match-rooms/{mr.id}/contacts?user_id={challenger.id}")
        assert status_c1.status_code == 200
        assert status_c1.json()["partner"] is None

        # Candidate checks status before candidate submission
        status_cand_pre = client.get(f"/match-rooms/{mr.id}/contacts?user_id={cand.id}")
        assert status_cand_pre.status_code == 200
        assert status_cand_pre.json()["submitted"] is False
        assert status_cand_pre.json()["partner"] is None

        # 2. Candidate submits Snapchat
        resp_c2 = client.post(
            f"/match-rooms/{mr.id}/contacts",
            json={"user_id": cand.id, "whatsapp": None, "snapchat": "kofi_snap"},
        )
        assert resp_c2.status_code == 201
        data_c2 = resp_c2.json()
        assert data_c2["state"] == "completed"
        assert data_c2["submitted"] is True
        # Candidate immediately receives Challenger's WhatsApp!
        assert data_c2["partner"] is not None
        assert data_c2["partner"]["name"] == "Ama"
        assert data_c2["partner"]["whatsapp"] == "+233201111111"
        assert data_c2["partner"]["snapchat"] is None

        # 3. Challenger now checks status and receives Candidate's Snapchat!
        status_c1_post = client.get(f"/match-rooms/{mr.id}/contacts?user_id={challenger.id}")
        assert status_c1_post.status_code == 200
        data_c1_post = status_c1_post.json()
        assert data_c1_post["state"] == "completed"
        assert data_c1_post["partner"]["name"] == "Kofi"
        assert data_c1_post["partner"]["snapchat"] == "kofi_snap"
        assert data_c1_post["partner"]["whatsapp"] is None

        # 4. Verify database state
        db.refresh(mr)
        assert mr.state == MatchRoomState.COMPLETED
        assert mr.completed_at is not None

        match = db.get(Match, mr.match_id)
        assert match.status == MatchStatus.COMPLETED

        db.refresh(challenger)
        db.refresh(cand)
        assert challenger.state == UserState.COMPLETED
        assert cand.state == UserState.COMPLETED

        # 5. Queue protection: Completed users cannot re-enter the queue
        with pytest.raises(UserAlreadyCompletedEventError):
            queue_manager.add(db, challenger)

        with pytest.raises(UserAlreadyCompletedEventError):
            queue_manager.add(db, cand)
