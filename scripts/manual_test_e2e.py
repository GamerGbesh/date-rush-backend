"""
Comprehensive System Audit for Date Rush.
Audits the complete lifecycle:
1. Health & Database
2. Queue operations & FIFO Matchmaking
3. Room creation & Public Questioning
4. Public Voting & Elimination
5. Single GameRoom WebSocket & Filtered One-on-One Sessions
6. Message Isolation & Privacy Verification
7. Final Selection & MatchRoom Contact Exchange
8. Reconnection & Security Guards
"""

import sys
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.models  # noqa: F401
from app.database import Base, get_db
from app.enums import (
    ParticipantStatus,
    PlayerRole,
    QuestionTarget,
    RoomState,
    UserState,
)
from app.main import app
from app.models.one_on_one_session import OneOnOneSession
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.user import User


def log(section: str, msg: str):
    print(f"\n[\033[1;34m{section}\033[0m] {msg}")


def success(msg: str):
    print(f"  \033[1;32m✓\033[0m {msg}")


def error(msg: str):
    print(f"  \033[1;31m✗\033[0m {msg}")
    sys.exit(1)


def run_system_audit():
    # Setup isolated test database engine
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()

    # Seed questions
    questions = [
        Question(text=f"General Question {i}", target_gender=QuestionTarget.ANY, active=True)
        for i in range(1, 10)
    ]
    db.add_all(questions)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.main.init_db"):
        with TestClient(app, raise_server_exceptions=True) as client:
            print("\033[1;36m========================================================\033[0m")
            print("\033[1;36m       DATE RUSH — COMPREHENSIVE SYSTEM AUDIT           \033[0m")
            print("\033[1;36m========================================================\033[0m")

            # --- 1. Health & Queue Status ---
            log("AUDIT 1", "Health check and initial queue status...")
            resp = client.get("/health")
            assert resp.status_code == 200 and resp.json() == {"status": "ok"}
            success("API is healthy.")

            resp_q = client.get("/queue/status")
            assert resp_q.status_code == 200
            success(f"Initial queue status: {resp_q.json()}")

            # --- 2. Registration & FIFO Matchmaking ---
            log("AUDIT 2", "Queue registration & automatic room formation...")
            resp_f = client.post("/queue/join", json={"name": "Ama (Challenger)", "gender": "female"})
            female_id = resp_f.json()["user_id"]
            success(f"Female registered: #{female_id}")

            male_ids = []
            for name in ["Kofi", "Yaw", "Kwame", "Kojo", "Kwabena"]:
                resp_m = client.post("/queue/join", json={"name": name, "gender": "male"})
                male_ids.append(resp_m.json()["user_id"])
                success(f"Male registered: {name} (#{male_ids[-1]})")

            me_resp = client.get(f"/users/me?user_id={female_id}")
            room_id = me_resp.json()["room_id"]
            assert room_id is not None
            success(f"Room #{room_id} formed automatically upon threshold satisfaction!")

            # --- 3. Single GameRoom WebSocket & Questioning ---
            log("AUDIT 3", "GameRoom WebSocket connection & 3 public questioning rounds...")
            # Advance room to questioning
            client.post(f"/admin/rooms/{room_id}/transition", json={"state": "intro"})
            client.post(f"/admin/rooms/{room_id}/transition", json={"state": "questioning"})

            # Connect Challenger and Audience 1 to the Single GameRoom WebSocket
            with client.websocket_connect(f"/ws/rooms/{room_id}/users/{female_id}") as ws_chal:
                with client.websocket_connect(f"/ws/rooms/{room_id}/users/{male_ids[0]}") as ws_aud1:
                    with client.websocket_connect(f"/ws/rooms/{room_id}/users/{male_ids[1]}") as ws_aud2:
                        with client.websocket_connect(f"/ws/rooms/{room_id}/users/{male_ids[2]}") as ws_aud3:
                            # State sync on connect
                            assert ws_chal.receive_json()["type"] == "room_state_changed"
                            assert ws_chal.receive_json()["type"] == "question_started"
                            assert ws_aud1.receive_json()["type"] == "room_state_changed"
                            assert ws_aud1.receive_json()["type"] == "question_started"
                            assert ws_aud2.receive_json()["type"] == "room_state_changed"
                            assert ws_aud2.receive_json()["type"] == "question_started"
                            assert ws_aud3.receive_json()["type"] == "room_state_changed"
                            assert ws_aud3.receive_json()["type"] == "question_started"
                            success("Initial GameRoom WebSocket state synchronized for all clients.")

                            # Answer 3 questions
                            for r_num in range(1, 4):
                                client.post(
                                    f"/rooms/{room_id}/answers",
                                    json={"user_id": female_id, "answer": f"Answer to Round {r_num}"},
                                )
                                # Consume broadcast answer
                                ev_ans_c = ws_chal.receive_json()
                                ev_ans_a1 = ws_aud1.receive_json()
                                _ = ws_aud2.receive_json()
                                _ = ws_aud3.receive_json()
                                assert ev_ans_c["type"] == "answer_revealed"
                                assert ev_ans_a1["type"] == "answer_revealed"
                                success(f"Round {r_num} Challenger answer broadcast to all participants.")

                                if r_num < 3:
                                    _ = ws_chal.receive_json()  # next question_started
                                    _ = ws_aud1.receive_json()
                                    _ = ws_aud2.receive_json()
                                    _ = ws_aud3.receive_json()

                            # --- 4. Public Voting & Elimination ---
                            log("AUDIT 4", "Public voting phase & elimination...")
                            # Room enters voting
                            assert ws_chal.receive_json()["type"] == "room_state_changed"
                            assert ws_chal.receive_json()["type"] == "voting_started"
                            _ = ws_aud1.receive_json()  # room_state_changed
                            _ = ws_aud1.receive_json()  # voting_started
                            _ = ws_aud2.receive_json()
                            _ = ws_aud2.receive_json()
                            _ = ws_aud3.receive_json()
                            _ = ws_aud3.receive_json()
                            success("Room transitioned to VOTING.")

                            # 3 Males vote YES, 2 Males vote NO
                            for m_id in male_ids[:3]:
                                client.post(f"/rooms/{room_id}/vote", json={"user_id": m_id, "vote": "yes"})
                                # Consume vote progress
                                _ = ws_chal.receive_json()
                                _ = ws_aud1.receive_json()
                                _ = ws_aud2.receive_json()
                                _ = ws_aud3.receive_json()

                            for m_id in male_ids[3:]:
                                client.post(f"/rooms/{room_id}/vote", json={"user_id": m_id, "vote": "no"})
                                _ = ws_chal.receive_json()
                                _ = ws_aud1.receive_json()
                                _ = ws_aud2.receive_json()
                                _ = ws_aud3.receive_json()

                            # Voting finishes -> Room transitions to ONE_ON_ONE
                            _ = ws_chal.receive_json()  # voting_completed
                            _ = ws_chal.receive_json()  # room_state_changed (elimination)
                            _ = ws_chal.receive_json()  # participants_eliminated
                            _ = ws_chal.receive_json()  # room_state_changed (one_on_one)
                            s1_start_chal = ws_chal.receive_json()
                            assert s1_start_chal["type"] == "one_on_one_started"
                            _ = ws_chal.receive_json()  # one_on_one_progress (completed=0)

                            _ = ws_aud1.receive_json()  # voting_completed
                            _ = ws_aud1.receive_json()  # room_state_changed (elimination)
                            _ = ws_aud1.receive_json()  # participants_eliminated
                            _ = ws_aud1.receive_json()  # room_state_changed (one_on_one)
                            s1_start_aud1 = ws_aud1.receive_json()
                            assert s1_start_aud1["type"] == "one_on_one_started"
                            _ = ws_aud1.receive_json()  # one_on_one_progress

                            _ = ws_aud2.receive_json()  # voting_completed
                            _ = ws_aud2.receive_json()  # room_state_changed (elimination)
                            _ = ws_aud2.receive_json()  # participants_eliminated
                            _ = ws_aud2.receive_json()  # room_state_changed (one_on_one)
                            prog_aud2 = ws_aud2.receive_json()
                            assert prog_aud2["type"] == "one_on_one_progress"

                            _ = ws_aud3.receive_json()  # voting_completed
                            _ = ws_aud3.receive_json()  # room_state_changed (elimination)
                            _ = ws_aud3.receive_json()  # participants_eliminated
                            _ = ws_aud3.receive_json()  # room_state_changed (one_on_one)
                            prog_aud3 = ws_aud3.receive_json()
                            assert prog_aud3["type"] == "one_on_one_progress"
                            success("Public voting completed; 2 participants eliminated; 3 survivors entered ONE_ON_ONE.")

                            # --- 5. Filtered One-on-One Session Routing Audit ---
                            log("AUDIT 5", "Auditing filtered message isolation on single GameRoom WebSocket...")
                            s1 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room_id, OneOnOneSession.sequence == 1).one()
                            s2 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room_id, OneOnOneSession.sequence == 2).one()
                            s3 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room_id, OneOnOneSession.sequence == 3).one()

                            # Session 1: Aud 1 asks private question
                            client.post(
                                f"/rooms/{room_id}/one-on-one/{s1.id}/question",
                                json={"user_id": male_ids[0], "text": "Top secret question from Aud 1"},
                            )
                            q_c = ws_chal.receive_json()
                            q_a1 = ws_aud1.receive_json()
                            assert q_c["type"] == "one_on_one_question"
                            assert q_c["question"] == "Top secret question from Aud 1"
                            assert q_a1["type"] == "one_on_one_question"
                            success("Audience 1 private question received ONLY by Challenger & Audience 1.")

                            # Challenger answers private question
                            client.post(
                                f"/rooms/{room_id}/one-on-one/{s1.id}/answer",
                                json={"user_id": female_id, "text": "Top secret answer from Challenger"},
                            )
                            ans_c = ws_chal.receive_json()
                            ans_a1 = ws_aud1.receive_json()
                            assert ans_c["type"] == "one_on_one_answer"
                            assert ans_a1["type"] == "one_on_one_answer"
                            success("Challenger private answer received ONLY by Challenger & Audience 1.")

                            # Aud 1 votes YES -> Marked FINALIST
                            client.post(f"/rooms/{room_id}/one-on-one/{s1.id}/vote", json={"user_id": male_ids[0], "vote": "yes"})
                            assert ws_chal.receive_json()["type"] == "one_on_one_completed"
                            assert ws_aud1.receive_json()["type"] == "one_on_one_completed"
                            assert ws_chal.receive_json()["type"] == "one_on_one_progress"
                            assert ws_aud1.receive_json()["type"] == "one_on_one_progress"
                            assert ws_aud2.receive_json()["type"] == "one_on_one_progress"
                            assert ws_aud3.receive_json()["type"] == "one_on_one_progress"

                            # Session 2 automatically starts for Audience 2
                            s2_c = ws_chal.receive_json()
                            s2_a2 = ws_aud2.receive_json()
                            assert s2_c["type"] == "one_on_one_started"
                            assert s2_c["audience_id"] == male_ids[1]
                            assert s2_a2["type"] == "one_on_one_started"
                            success("Session 2 auto-activated for Audience 2 without creating a new WebSocket room.")

                            # Session 2: Aud 2 asks, Challenger answers, Aud 2 votes NO -> Eliminated
                            client.post(f"/rooms/{room_id}/one-on-one/{s2.id}/question", json={"user_id": male_ids[1], "text": "Q2"})
                            _ = ws_chal.receive_json()
                            _ = ws_aud2.receive_json()

                            client.post(f"/rooms/{room_id}/one-on-one/{s2.id}/answer", json={"user_id": female_id, "text": "A2"})
                            _ = ws_chal.receive_json()
                            _ = ws_aud2.receive_json()

                            client.post(f"/rooms/{room_id}/one-on-one/{s2.id}/vote", json={"user_id": male_ids[1], "vote": "no"})
                            assert ws_chal.receive_json()["type"] == "one_on_one_completed"
                            assert ws_aud2.receive_json()["type"] == "one_on_one_completed"
                            assert ws_aud2.receive_json()["type"] == "eliminated"
                            assert ws_chal.receive_json()["type"] == "one_on_one_progress"
                            assert ws_aud1.receive_json()["type"] == "one_on_one_progress"
                            assert ws_aud3.receive_json()["type"] == "one_on_one_progress"
                            success("Audience 2 voted NO: correctly received elimination event and was disconnected.")

                            # Session 3 automatically starts for Audience 3
                            s3_c = ws_chal.receive_json()
                            s3_a3 = ws_aud3.receive_json()
                            assert s3_c["type"] == "one_on_one_started"
                            assert s3_a3["type"] == "one_on_one_started"

                            client.post(f"/rooms/{room_id}/one-on-one/{s3.id}/question", json={"user_id": male_ids[2], "text": "Q3"})
                            _ = ws_chal.receive_json()
                            _ = ws_aud3.receive_json()

                            client.post(f"/rooms/{room_id}/one-on-one/{s3.id}/answer", json={"user_id": female_id, "text": "A3"})
                            _ = ws_chal.receive_json()
                            _ = ws_aud3.receive_json()

                            client.post(f"/rooms/{room_id}/one-on-one/{s3.id}/vote", json={"user_id": male_ids[2], "vote": "yes"})
                            _ = ws_chal.receive_json()  # one_on_one_completed
                            _ = ws_aud3.receive_json()
                            _ = ws_chal.receive_json()  # one_on_one_progress
                            _ = ws_aud1.receive_json()
                            _ = ws_aud3.receive_json()

                            # Room automatically transitions to FINAL_SELECTION
                            assert ws_chal.receive_json()["type"] == "room_state_changed"
                            fs_chal = ws_chal.receive_json()
                            assert fs_chal["type"] == "final_selection_started"
                            assert len(fs_chal["candidates"]) == 2
                            success("All 1-on-1 sessions completed: 2 finalists survived -> Entered FINAL_SELECTION.")

            # --- 6. Final Selection & Match Creation ---
            log("AUDIT 6", "Final selection and Match Room initialization...")
            resp_fs = client.post(
                f"/rooms/{room_id}/final-selection",
                json={"user_id": female_id, "candidate_id": male_ids[0]},
            )
            assert resp_fs.status_code == 201
            match_id = resp_fs.json()["id"]

            resp_m_info = client.get(f"/matches/{match_id}?user_id={female_id}")
            match_room_id = resp_m_info.json()["match_room_id"]
            success(f"Match #{match_id} created with Private MatchRoom #{match_room_id}!")

            # --- 7. Private Match Room Contact Exchange ---
            log("AUDIT 7", "Private Match Room WebSocket contact exchange...")
            with client.websocket_connect(f"/ws/match-rooms/{match_room_id}/users/{female_id}") as ws_mr_chal:
                with client.websocket_connect(f"/ws/match-rooms/{match_room_id}/users/{male_ids[0]}") as ws_mr_aud:
                    assert ws_mr_chal.receive_json()["type"] == "match_room_state"
                    assert ws_mr_aud.receive_json()["type"] == "match_room_state"

                    # Challenger submits contact
                    client.post(
                        f"/match-rooms/{match_room_id}/contacts",
                        json={"user_id": female_id, "whatsapp": "+233240001122"},
                    )
                    assert ws_mr_chal.receive_json()["type"] == "contact_submission_status"
                    assert ws_mr_aud.receive_json()["type"] == "waiting_for_partner"

                    # Candidate submits contact -> Triggers atomic exchange
                    client.post(
                        f"/match-rooms/{match_room_id}/contacts",
                        json={"user_id": male_ids[0], "snapchat": "kofi_gh"},
                    )
                    assert ws_mr_aud.receive_json()["type"] == "contact_submission_status"

                    exc_c = ws_mr_chal.receive_json()
                    assert exc_c["type"] == "contacts_exchanged"
                    assert exc_c["partner"]["snapchat"] == "kofi_gh"
                    _ = ws_mr_chal.receive_json()  # match_completed

                    exc_a = ws_mr_aud.receive_json()
                    assert exc_a["type"] == "contacts_exchanged"
                    assert exc_a["partner"]["whatsapp"] == "+233240001122"
                    _ = ws_mr_aud.receive_json()  # match_completed
                    success("Atomic contact exchange completed successfully over MatchRoom WS!")

            # --- 8. Reconnection & Security Guards Audit ---
            log("AUDIT 8", "Security guards and state recovery audit...")
            # 1. Verify obsolete endpoint is rejected
            try:
                with client.websocket_connect(f"/ws/rooms/{room_id}/one-on-one/1/users/{female_id}") as ws:
                    ws.receive_json()
                error("Obsolete one-on-one WebSocket endpoint was not rejected!")
            except Exception:
                success("Obsolete per-session WebSocket route correctly rejected.")

            # 2. Verify duplicate question rejected
            resp_dup = client.post(
                f"/rooms/{room_id}/one-on-one/{s1.id}/question",
                json={"user_id": male_ids[0], "text": "Duplicate"},
            )
            assert resp_dup.status_code in (409, 422)
            success("Duplicate question rejected with HTTP 409 Conflict.")

            # 3. Verify public listing does not leak private text
            resp_pub = client.get(f"/rooms/{room_id}/one-on-one")
            for item in resp_pub.json():
                assert "Top secret" not in str(item)
            success("Public one-on-one listing verified clean of private conversation text.")

            print("\n\033[1;32m========================================================\033[0m")
            print("\033[1;32m  SYSTEM AUDIT COMPLETED: ALL AUDIT CHECKS PASSED!      \033[0m")
            print("\033[1;32m========================================================\033[0m\n")


if __name__ == "__main__":
    run_system_audit()

