import pytest

from app.enums import Gender, PlayerRole, QuestionPhase, QuestionTarget, RoomState, UserState
from app.models.answer import Answer
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.room_question import RoomQuestion
from app.models.user import User
from app.services.room_state_service import room_state_service


def _seed_ready_room(db) -> tuple[Room, User, list[User], list[Question]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
        for i in range(5)
    ]
    db.add_all([challenger] + audience)
    db.commit()

    questions = [
        Question(text=f"Question {i}", target_gender=QuestionTarget.ANY, active=True)
        for i in range(1, 4)
    ]
    db.add_all(questions)
    db.commit()

    room = Room(
        state=RoomState.READY,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=0,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    for a in audience:
        db.add(RoomParticipant(room_id=room.id, user_id=a.id, role=PlayerRole.AUDIENCE))

    for idx, q in enumerate(questions, start=1):
        db.add(RoomQuestion(room_id=room.id, question_id=q.id, position=idx, phase=QuestionPhase.PUBLIC))

    db.commit()
    db.refresh(room)
    return room, challenger, audience, questions


class TestPublicQuestioningFlow:
    @pytest.mark.asyncio
    async def test_full_questioning_and_automatic_voting_transition(self, client, db):
        room, challenger, audience, questions = _seed_ready_room(db)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws_chal:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{audience[0].id}") as ws_aud:
                # Flush initial connection events
                ws_chal.receive_json()
                ws_aud.receive_json()

                # 1. Start room: READY -> INTRO
                client.post(f"/admin/rooms/{room.id}/start")
                assert ws_chal.receive_json()["state"] == "intro"
                assert ws_aud.receive_json()["state"] == "intro"

                # 2. INTRO -> QUESTIONING (auto-starts Question 1)
                client.post(f"/admin/rooms/{room.id}/start-questioning")

                # Should receive room_state_changed
                assert ws_chal.receive_json()["state"] == "questioning"
                assert ws_aud.receive_json()["state"] == "questioning"

                # Should receive question_started for round 1
                q1_chal = ws_chal.receive_json()
                q1_aud = ws_aud.receive_json()
                assert q1_chal["type"] == "question_started"
                assert q1_chal["round"] == 1
                assert q1_chal["question"]["id"] == questions[0].id
                assert q1_aud["type"] == "question_started"
                assert q1_aud["round"] == 1

                # 3. Challenger submits Answer 1 -> reveals answer and auto-starts Question 2
                resp1 = client.post(
                    f"/rooms/{room.id}/answers",
                    json={"user_id": challenger.id, "answer": "My answer to question 1"},
                )
                assert resp1.status_code == 201

                # Answer revealed event
                ans1_chal = ws_chal.receive_json()
                ans1_aud = ws_aud.receive_json()
                assert ans1_chal["type"] == "answer_revealed"
                assert ans1_chal["round"] == 1
                assert ans1_chal["answer"] == "My answer to question 1"
                assert ans1_aud["type"] == "answer_revealed"

                # Next question (Question 2) started event
                q2_chal = ws_chal.receive_json()
                q2_aud = ws_aud.receive_json()
                assert q2_chal["type"] == "question_started"
                assert q2_chal["round"] == 2
                assert q2_chal["question"]["id"] == questions[1].id
                assert q2_aud["type"] == "question_started"
                assert q2_aud["round"] == 2

                # 4. Challenger submits Answer 2 -> reveals answer and auto-starts Question 3
                resp2 = client.post(
                    f"/rooms/{room.id}/answers",
                    json={"user_id": challenger.id, "answer": "My answer to question 2"},
                )
                assert resp2.status_code == 201

                assert ws_chal.receive_json()["type"] == "answer_revealed"
                assert ws_aud.receive_json()["type"] == "answer_revealed"

                q3_chal = ws_chal.receive_json()
                q3_aud = ws_aud.receive_json()
                assert q3_chal["type"] == "question_started"
                assert q3_chal["round"] == 3
                assert q3_chal["question"]["id"] == questions[2].id
                assert q3_aud["type"] == "question_started"
                assert q3_aud["round"] == 3

                # 5. Challenger submits Answer 3 (Final Public Answer) -> reveals answer and auto-transitions to VOTING
                resp3 = client.post(
                    f"/rooms/{room.id}/answers",
                    json={"user_id": challenger.id, "answer": "My final answer"},
                )
                assert resp3.status_code == 201

                assert ws_chal.receive_json()["type"] == "answer_revealed"
                assert ws_aud.receive_json()["type"] == "answer_revealed"

                # Room automatically transitioned to VOTING!
                voting_chal = ws_chal.receive_json()
                voting_aud = ws_aud.receive_json()
                assert voting_chal["type"] == "room_state_changed"
                assert voting_chal["state"] == "voting"
                assert voting_aud["type"] == "room_state_changed"
                assert voting_aud["state"] == "voting"

                # Verify database state
                db.refresh(room)
                assert room.state == RoomState.VOTING
                assert db.query(Answer).filter(Answer.room_id == room.id).count() == 3


class TestAnswerValidations:
    def test_audience_cannot_submit_answer(self, client, db):
        room, challenger, audience, _ = _seed_ready_room(db)
        client.post(f"/admin/rooms/{room.id}/start")
        client.post(f"/admin/rooms/{room.id}/start-questioning")

        resp = client.post(
            f"/rooms/{room.id}/answers",
            json={"user_id": audience[0].id, "answer": "Audience trying to answer"},
        )
        assert resp.status_code == 403
        assert "not the challenger" in resp.json()["detail"]

    def test_cannot_answer_in_non_questioning_state(self, client, db):
        room, challenger, _, _ = _seed_ready_room(db)
        # Room is in READY
        resp = client.post(
            f"/rooms/{room.id}/answers",
            json={"user_id": challenger.id, "answer": "Too early answer"},
        )
        assert resp.status_code == 409
        assert "is in state 'ready'" in resp.json()["detail"]

    def test_duplicate_answer_rejected(self, client, db):
        room, challenger, _, questions = _seed_ready_room(db)
        client.post(f"/admin/rooms/{room.id}/start")
        client.post(f"/admin/rooms/{room.id}/start-questioning")

        # First answer OK
        resp1 = client.post(
            f"/rooms/{room.id}/answers",
            json={"user_id": challenger.id, "answer": "Answer 1"},
        )
        assert resp1.status_code == 201

        # Direct insertion of a duplicate attempt or duplicate check
        db.add(Answer(room_id=room.id, question_id=questions[1].id, user_id=challenger.id, answer="Already answered"))
        db.commit()

        # Attempt to answer question 2 again
        resp2 = client.post(
            f"/rooms/{room.id}/answers",
            json={"user_id": challenger.id, "answer": "Duplicate Answer 2"},
        )
        assert resp2.status_code == 409
        assert "already answered" in resp2.json()["detail"]


class TestWebSocketReconnectInQuestioning:
    def test_reconnecting_client_receives_current_question(self, client, db):
        room, challenger, _, questions = _seed_ready_room(db)
        client.post(f"/admin/rooms/{room.id}/start")
        client.post(f"/admin/rooms/{room.id}/start-questioning")

        # New connection while in QUESTIONING
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws:
            msg1 = ws.receive_json()
            assert msg1["type"] == "room_state_changed"
            assert msg1["state"] == "questioning"

            msg2 = ws.receive_json()
            assert msg2["type"] == "question_started"
            assert msg2["round"] == 1
            assert msg2["question"]["id"] == questions[0].id
