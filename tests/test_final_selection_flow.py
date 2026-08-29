import pytest

from app.enums import Gender, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.models.match import Match
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.room_state_service import room_state_service


def _seed_finalists_room(db, finalist_count: int = 3) -> tuple[Room, User, list[User]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    finalists = [
        User(name=f"Finalist_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
        for i in range(finalist_count)
    ]
    db.add_all([challenger] + finalists)
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
    for f in finalists:
        db.add(RoomParticipant(room_id=room.id, user_id=f.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))

    db.commit()
    db.refresh(room)
    return room, challenger, finalists


class TestFinalSelectionFlow:
    @pytest.mark.asyncio
    async def test_full_final_selection_and_match_creation(self, client, db):
        room, challenger, finalists = _seed_finalists_room(db, finalist_count=3)

        # 1. Challenger checks eligible candidates via API
        status_resp = client.get(f"/rooms/{room.id}/final-selection?user_id={challenger.id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["is_challenger"] is True
        assert len(data["candidates"]) == 3
        candidate_ids = [c["id"] for c in data["candidates"]]
        assert finalists[1].id in candidate_ids

        # Non-challenger does not receive candidate list
        aud_status_resp = client.get(f"/rooms/{room.id}/final-selection?user_id={finalists[0].id}")
        assert aud_status_resp.json()["candidates"] is None

        # 2. Challenger selects Finalist 1
        resp = client.post(
            f"/rooms/{room.id}/final-selection",
            json={"user_id": challenger.id, "candidate_id": finalists[1].id},
        )
        assert resp.status_code == 201
        match_data = resp.json()
        assert match_data["challenger_id"] == challenger.id
        assert match_data["audience_id"] == finalists[1].id
        assert match_data["status"] == "created"

        # 3. Verify database state
        db.refresh(room)
        assert room.state == RoomState.COMPLETED

        # Challenger and chosen candidate are MATCHED
        db.refresh(challenger)
        db.refresh(finalists[1])
        assert challenger.state == UserState.MATCHED
        assert finalists[1].state == UserState.MATCHED

        p_chal = db.get(RoomParticipant, (room.id, challenger.id))
        p_cand1 = db.get(RoomParticipant, (room.id, finalists[1].id))
        assert p_chal.status == ParticipantStatus.SELECTED
        assert p_cand1.status == ParticipantStatus.SELECTED

        # Non-selected finalists (Finalist 0 and 2) are ELIMINATED and returned to QUEUED
        for idx in [0, 2]:
            db.refresh(finalists[idx])
            assert finalists[idx].state == UserState.QUEUED
            assert finalists[idx].queued_at is not None
            p_other = db.get(RoomParticipant, (room.id, finalists[idx].id))
            assert p_other.status == ParticipantStatus.ELIMINATED
            assert p_other.left_at is not None

        # Verify exactly one match exists in DB
        matches = db.query(Match).where(Match.room_id == room.id).all()
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_single_survivor_shortcut_creates_match_automatically(self, client, db):
        challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
        aud1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
        aud2 = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
        db.add_all([challenger, aud1, aud2])
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
        db.add(RoomParticipant(room_id=room.id, user_id=aud1.id, role=PlayerRole.AUDIENCE))
        db.add(RoomParticipant(room_id=room.id, user_id=aud2.id, role=PlayerRole.AUDIENCE))
        db.commit()

        # Transition into ONE_ON_ONE
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        # Aud 1: YES -> finalist
        client.post(f"/rooms/{room.id}/one-on-one/1/question", json={"user_id": aud1.id, "text": "Q1"})
        client.post(f"/rooms/{room.id}/one-on-one/1/answer", json={"user_id": challenger.id, "text": "A1"})
        client.post(f"/rooms/{room.id}/one-on-one/1/vote", json={"user_id": aud1.id, "vote": "yes"})

        # Aud 2: NO -> eliminated
        client.post(f"/rooms/{room.id}/one-on-one/2/question", json={"user_id": aud2.id, "text": "Q2"})
        client.post(f"/rooms/{room.id}/one-on-one/2/answer", json={"user_id": challenger.id, "text": "A2"})
        client.post(f"/rooms/{room.id}/one-on-one/2/vote", json={"user_id": aud2.id, "vote": "no"})

        # Since only 1 survivor (Aud 1), room automatically matches and completes!
        db.refresh(room)
        assert room.state == RoomState.COMPLETED

        match = db.query(Match).where(Match.room_id == room.id).one()
        assert match.challenger_id == challenger.id
        assert match.audience_id == aud1.id

        db.refresh(challenger)
        db.refresh(aud1)
        assert challenger.state == UserState.MATCHED
        assert aud1.state == UserState.MATCHED
