import pytest

from app.enums import Gender, ParticipantStatus, PlayerRole, QuestionPhase, QuestionTarget, RoomState, UserState
from app.models.match import Match
from app.models.match_room import MatchRoom
from app.models.one_on_one_session import OneOnOneSession
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.room_question import RoomQuestion
from app.models.user import User
from app.services.match_room_service import match_room_service
from app.services.room_state_service import room_state_service


def _seed_game_room(db) -> tuple[Room, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    aud1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    aud2 = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, aud1, aud2])
    db.commit()

    questions = [
        Question(text=f"Question {i}", target_gender=QuestionTarget.ANY, active=True)
        for i in range(1, 4)
    ]
    db.add_all(questions)
    db.commit()

    room = Room(
        state=RoomState.QUESTIONING,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
        current_question_id=questions[0].id,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    db.add(RoomParticipant(room_id=room.id, user_id=aud1.id, role=PlayerRole.AUDIENCE))
    db.add(RoomParticipant(room_id=room.id, user_id=aud2.id, role=PlayerRole.AUDIENCE))

    for idx, q in enumerate(questions, start=1):
        db.add(RoomQuestion(room_id=room.id, question_id=q.id, position=idx, phase=QuestionPhase.PUBLIC))

    db.commit()
    db.refresh(room)
    return room, challenger, aud1, aud2


class TestE2EWebSocketLifecycle:
    def test_multi_channel_websocket_events_and_privacy(self, client, db):
        print("STEP 0: Seeding")
        room, challenger, aud1, aud2 = _seed_game_room(db)
        print("STEP 1: Starting room questioning")
        # 1. Connect challenger and aud1 to Public Room WebSocket
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws_pub_chal:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud1.id}") as ws_pub_aud1:
                print("STEP 1.1: WS connected")
                init_chal_state = ws_pub_chal.receive_json()
                init_chal_q = ws_pub_chal.receive_json()
                assert init_chal_state["type"] == "room_state_changed"
                assert init_chal_q["type"] == "question_started"

                init_aud_state = ws_pub_aud1.receive_json()
                init_aud_q = ws_pub_aud1.receive_json()
                assert init_aud_state["type"] == "room_state_changed"
                assert init_aud_q["type"] == "question_started"
                print("STEP 1.2: Initial events received")

                # Challenger answers Question 1 -> public broadcast
                client.post(
                    f"/rooms/{room.id}/answers",
                    json={"user_id": challenger.id, "answer": "I love outdoor sports."},
                )
                print("STEP 1.3: Answer 1 posted")

                ans_ev_chal = ws_pub_chal.receive_json()
                ans_ev_aud1 = ws_pub_aud1.receive_json()
                # Receive auto transition to Question 2 (only question_started broadcast)
                next_q_chal = ws_pub_chal.receive_json()
                assert next_q_chal["type"] == "question_started"
                assert next_q_chal["round"] == 2

                next_q_aud1 = ws_pub_aud1.receive_json()
                assert next_q_aud1["type"] == "question_started"
                assert next_q_aud1["round"] == 2

        # Answer remaining questions -> Room enters VOTING
        client.post(f"/rooms/{room.id}/answers", json={"user_id": challenger.id, "answer": "Ans 2"})
        client.post(f"/rooms/{room.id}/answers", json={"user_id": challenger.id, "answer": "Ans 3"})

        # Both vote YES -> Room enters ONE_ON_ONE
        client.post(f"/rooms/{room.id}/vote", json={"user_id": aud1.id, "vote": "yes"})
        client.post(f"/rooms/{room.id}/vote", json={"user_id": aud2.id, "vote": "yes"})

        db.refresh(room)
        assert room.state == RoomState.ONE_ON_ONE

        # Query session IDs
        s1 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()
        s2 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 2).one()

        # 2. Private 1-on-1 Channel for Session 1 (Aud 1)
        with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{aud1.id}") as ws_ooo_aud1:
            with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{challenger.id}") as ws_ooo_chal:
                # Initial private state
                s_state_a = ws_ooo_aud1.receive_json()
                assert s_state_a["type"] == "private_session_state"

                s_state_c = ws_ooo_chal.receive_json()
                assert s_state_c["type"] == "private_session_state"

                # Aud 1 posts private question
                client.post(f"/rooms/{room.id}/one-on-one/{s1.id}/question", json={"user_id": aud1.id, "text": "Secret Q"})
                q_ev_c = ws_ooo_chal.receive_json()
                assert q_ev_c["type"] == "private_question"
                assert q_ev_c["text"] == "Secret Q"

                _ = ws_ooo_aud1.receive_json()

                # Challenger posts private answer
                client.post(f"/rooms/{room.id}/one-on-one/{s1.id}/answer", json={"user_id": challenger.id, "text": "Secret A"})
                a_ev_a = ws_ooo_aud1.receive_json()
                assert a_ev_a["type"] == "private_answer"
                assert a_ev_a["text"] == "Secret A"

                _ = ws_ooo_chal.receive_json()

                # Aud 1 votes YES
                client.post(f"/rooms/{room.id}/one-on-one/{s1.id}/vote", json={"user_id": aud1.id, "vote": "yes"})
                comp_ev_a = ws_ooo_aud1.receive_json()
                assert comp_ev_a["type"] == "session_completed"

                comp_ev_c = ws_ooo_chal.receive_json()
                assert comp_ev_c["type"] == "session_completed"

        # Session 2 (Aud 2) votes YES
        client.post(f"/rooms/{room.id}/one-on-one/{s2.id}/question", json={"user_id": aud2.id, "text": "Q2"})
        client.post(f"/rooms/{room.id}/one-on-one/{s2.id}/answer", json={"user_id": challenger.id, "text": "A2"})
        client.post(f"/rooms/{room.id}/one-on-one/{s2.id}/vote", json={"user_id": aud2.id, "vote": "yes"})

        # Room enters FINAL_SELECTION
        db.refresh(room)
        assert room.state == RoomState.FINAL_SELECTION

        # 3. Challenger selects Aud 1
        resp_match = client.post(f"/rooms/{room.id}/final-selection", json={"user_id": challenger.id, "candidate_id": aud1.id})
        assert resp_match.status_code == 201

        match = db.query(Match).where(Match.room_id == room.id).one()
        mr = db.query(MatchRoom).where(MatchRoom.match_id == match.id).one()

        # 4. Private Match Room WebSocket
        with client.websocket_connect(f"/ws/match-rooms/{mr.id}/users/{challenger.id}") as ws_mr_chal:
            with client.websocket_connect(f"/ws/match-rooms/{mr.id}/users/{aud1.id}") as ws_mr_aud1:
                mr_init_c = ws_mr_chal.receive_json()
                assert mr_init_c["type"] == "match_room_state"
                assert mr_init_c["state"] == "waiting_for_contacts"

                mr_init_a = ws_mr_aud1.receive_json()
                assert mr_init_a["type"] == "match_room_state"

                # Challenger submits WhatsApp
                client.post(f"/match-rooms/{mr.id}/contacts", json={"user_id": challenger.id, "whatsapp": "+233500000000"})
                sub_c = ws_mr_chal.receive_json()
                assert sub_c["type"] == "contact_submission_status"

                wait_a = ws_mr_aud1.receive_json()
                assert wait_a["type"] == "waiting_for_partner"

                # Aud 1 submits Snapchat -> Triggers exchange!
                client.post(f"/match-rooms/{mr.id}/contacts", json={"user_id": aud1.id, "snapchat": "kofi_snapchat"})
                sub_a = ws_mr_aud1.receive_json()
                assert sub_a["type"] == "contact_submission_status"

                exc_c = ws_mr_chal.receive_json()
                assert exc_c["type"] == "contacts_exchanged"
                assert exc_c["partner"]["name"] == "Kofi"
                assert exc_c["partner"]["snapchat"] == "kofi_snapchat"

                _ = ws_mr_chal.receive_json()  # match_completed

                exc_a = ws_mr_aud1.receive_json()
                assert exc_a["type"] == "contacts_exchanged"
                assert exc_a["partner"]["name"] == "Ama"
                assert exc_a["partner"]["whatsapp"] == "+233500000000"

                _ = ws_mr_aud1.receive_json()  # match_completed
