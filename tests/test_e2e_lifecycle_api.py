import pytest

from app.enums import Gender, MatchRoomState, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.models.match import Match
from app.models.match_room import MatchRoom
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.queue_manager import queue_manager
from app.services.room_state_service import room_state_service


class TestE2ELifecycleAPI:
    @pytest.mark.asyncio
    async def test_complete_multi_survivor_lifecycle_api(self, client, db):
        """
        Full end-to-end integration test covering:
        1. Registration & Queueing
        2. Automatic Game Room Creation
        3. User Profile State Recovery (/users/me)
        4. Public Questioning & Challenger Answers
        5. Public Voting & Elimination
        6. Sequential One-on-One Sessions & Private Voting
        7. Final Selection & Candidate Validation
        8. Match & MatchRoom Creation
        9. Private Contact Exchange & Partner Retrieval
        10. Final User Event Completion & Queue Protection
        """
        # --- 1. Registration & Queue ---
        resp_f = client.post("/queue/join", json={"name": "Ama", "gender": "female"})
        assert resp_f.status_code == 201
        female_id = resp_f.json()["user_id"]

        male_ids = []
        for i in range(5):
            resp_m = client.post("/queue/join", json={"name": f"Guy_{i}", "gender": "male"})
            male_ids.append(resp_m.json()["user_id"])

        # When 5th male joins, room is automatically created!
        resp_me_f = client.get(f"/users/me?user_id={female_id}")
        assert resp_me_f.status_code == 200
        me_data = resp_me_f.json()
        assert me_data["state"] == "in_game"
        assert me_data["role"] == "challenger"
        room_id = me_data["room_id"]
        assert room_id is not None

        # --- 2. Advance Room to QUESTIONING ---
        await room_state_service.transition(db, room_id, RoomState.INTRO)
        await room_state_service.transition(db, room_id, RoomState.QUESTIONING)

        # --- 3. Public Questioning: Challenger answers 3 questions ---
        for round_num in range(1, 4):
            resp_ans = client.post(
                f"/rooms/{room_id}/answers",
                json={"user_id": female_id, "answer": f"Answer for round {round_num}"},
            )
            assert resp_ans.status_code == 201

        # Room automatically transitions to VOTING after 3rd answer!
        room = db.get(Room, room_id)
        db.refresh(room)
        assert room.state == RoomState.VOTING

        # Check voting status API
        resp_v_status = client.get(f"/rooms/{room_id}/voting?user_id={male_ids[0]}")
        assert resp_v_status.status_code == 200
        assert resp_v_status.json()["state"] == "voting"
        assert resp_v_status.json()["has_voted"] is False
        assert resp_v_status.json()["total_voters"] == 5

        # --- 4. Public Voting: 3 YES, 2 NO ---
        # Guy 0, 1, 2 vote YES
        for idx in range(3):
            resp_vote = client.post(
                f"/rooms/{room_id}/vote",
                json={"user_id": male_ids[idx], "vote": "yes"},
            )
            assert resp_vote.status_code == 201

        # Guy 3, 4 vote NO -> triggers vote finalization
        for idx in range(3, 5):
            resp_vote = client.post(
                f"/rooms/{room_id}/vote",
                json={"user_id": male_ids[idx], "vote": "no"},
            )
            assert resp_vote.status_code == 201

        # Room automatically enters ONE_ON_ONE with 3 surviving audience members
        db.refresh(room)
        assert room.state == RoomState.ONE_ON_ONE

        # Verify Guy 3 and 4 are eliminated and set to WAITING
        for idx in range(3, 5):
            u_elim = db.get(User, male_ids[idx])
            assert u_elim.state == UserState.WAITING

        # --- 5. Sequential One-on-One Sessions ---
        # Retrieve 1-on-1 status
        resp_ooo = client.get(f"/rooms/{room_id}/one-on-one")
        assert resp_ooo.status_code == 200
        sessions = resp_ooo.json()
        assert len(sessions) == 3

        # Session 1 (Guy 0): Asks Q -> Chal Answers -> Votes YES (Finalist)
        s1_id = sessions[0]["id"]
        client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/question", json={"user_id": male_ids[0], "text": "Q1"})
        client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/answer", json={"user_id": female_id, "text": "A1"})
        client.post(f"/rooms/{room_id}/one-on-one/{s1_id}/vote", json={"user_id": male_ids[0], "vote": "yes"})

        # Session 2 (Guy 1): Asks Q -> Chal Answers -> Votes NO (Eliminated)
        s2_id = sessions[1]["id"]
        client.post(f"/rooms/{room_id}/one-on-one/{s2_id}/question", json={"user_id": male_ids[1], "text": "Q2"})
        client.post(f"/rooms/{room_id}/one-on-one/{s2_id}/answer", json={"user_id": female_id, "text": "A2"})
        client.post(f"/rooms/{room_id}/one-on-one/{s2_id}/vote", json={"user_id": male_ids[1], "vote": "no"})

        # Session 3 (Guy 2): Asks Q -> Chal Answers -> Votes YES (Finalist)
        s3_id = sessions[2]["id"]
        client.post(f"/rooms/{room_id}/one-on-one/{s3_id}/question", json={"user_id": male_ids[2], "text": "Q3"})
        client.post(f"/rooms/{room_id}/one-on-one/{s3_id}/answer", json={"user_id": female_id, "text": "A3"})
        client.post(f"/rooms/{room_id}/one-on-one/{s3_id}/vote", json={"user_id": male_ids[2], "vote": "yes"})

        # Room automatically transitions to FINAL_SELECTION (2 finalists: Guy 0 and Guy 2)!
        db.refresh(room)
        assert room.state == RoomState.FINAL_SELECTION

        # --- 6. Challenger Final Selection ---
        resp_fs_status = client.get(f"/rooms/{room_id}/final-selection?user_id={female_id}")
        assert resp_fs_status.status_code == 200
        fs_data = resp_fs_status.json()
        assert fs_data["is_challenger"] is True
        assert len(fs_data["candidates"]) == 2
        candidate_ids = [c["id"] for c in fs_data["candidates"]]
        assert male_ids[0] in candidate_ids
        assert male_ids[2] in candidate_ids

        # Challenger selects Guy 2
        resp_select = client.post(
            f"/rooms/{room_id}/final-selection",
            json={"user_id": female_id, "candidate_id": male_ids[2]},
        )
        assert resp_select.status_code == 201
        match_id = resp_select.json()["id"]

        # --- 7. Match & MatchRoom Recovery ---
        resp_match = client.get(f"/matches/{match_id}?user_id={female_id}")
        assert resp_match.status_code == 200
        match_details = resp_match.json()
        assert match_details["status"] == "created"
        assert match_details["partner"]["id"] == male_ids[2]
        match_room_id = match_details["match_room_id"]
        assert match_room_id is not None

        resp_mr = client.get(f"/match-rooms/{match_room_id}?user_id={female_id}")
        assert resp_mr.status_code == 200
        assert resp_mr.json()["state"] == "waiting_for_contacts"
        assert resp_mr.json()["my_contact_submitted"] is False

        # --- 8. Contact Submission & Atomic Exchange ---
        # Challenger submits WhatsApp
        client.post(
            f"/match-rooms/{match_room_id}/contacts",
            json={"user_id": female_id, "whatsapp": "+233201234567", "snapchat": None},
        )

        # Guy 2 submits Snapchat -> Triggers exchange!
        resp_c2 = client.post(
            f"/match-rooms/{match_room_id}/contacts",
            json={"user_id": male_ids[2], "whatsapp": None, "snapchat": "guy2_snap"},
        )
        assert resp_c2.status_code == 201
        assert resp_c2.json()["state"] == "completed"
        assert resp_c2.json()["partner"]["name"] == "Ama"
        assert resp_c2.json()["partner"]["whatsapp"] == "+233201234567"

        # Challenger checks contacts -> receives Guy 2's Snapchat
        resp_c1 = client.get(f"/match-rooms/{match_room_id}/contacts?user_id={female_id}")
        assert resp_c1.status_code == 200
        assert resp_c1.json()["partner"]["name"] == "Guy_2"
        assert resp_c1.json()["partner"]["snapchat"] == "guy2_snap"

        # --- 9. Completed User State & Queue Protection ---
        resp_final_me = client.get(f"/users/me?user_id={female_id}")
        assert resp_final_me.json()["state"] == "completed"
        assert resp_final_me.json()["match_id"] == match_id
        assert resp_final_me.json()["match_room_id"] == match_room_id

        # Completed users cannot queue
        resp_requeue = client.post("/queue/join", json={"name": "Ama", "gender": "female"})
        # (New account created since queue/join creates new User, but existing user object is blocked via queue_manager.add)
        u_chal = db.get(User, female_id)
        with pytest.raises(Exception):
            queue_manager.add(db, u_chal)

    @pytest.mark.asyncio
    async def test_single_survivor_shortcut_e2e(self, client, db):
        """1 survivor after 1-on-1 automatically matches and completes."""
        chal = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
        aud1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
        db.add_all([chal, aud1])
        db.commit()

        room = Room(state=RoomState.ELIMINATION, challenger_id=chal.id, challenger_gender=chal.gender, current_round=1)
        db.add(room)
        db.flush()

        db.add(RoomParticipant(room_id=room.id, user_id=chal.id, role=PlayerRole.CHALLENGER))
        db.add(RoomParticipant(room_id=room.id, user_id=aud1.id, role=PlayerRole.AUDIENCE))
        db.commit()

        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        # Aud 1 votes YES
        client.post(f"/rooms/{room.id}/one-on-one/1/question", json={"user_id": aud1.id, "text": "Q1"})
        client.post(f"/rooms/{room.id}/one-on-one/1/answer", json={"user_id": chal.id, "text": "A1"})
        client.post(f"/rooms/{room.id}/one-on-one/1/vote", json={"user_id": aud1.id, "vote": "yes"})

        # Single survivor automatically forms Match & MatchRoom!
        match = db.query(Match).where(Match.room_id == room.id).one()
        assert match.challenger_id == chal.id
        assert match.audience_id == aud1.id

        mr = db.query(MatchRoom).where(MatchRoom.match_id == match.id).one()
        assert mr.state == MatchRoomState.WAITING_FOR_CONTACTS
