import pytest
from starlette.websockets import WebSocketDisconnect

from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.one_on_one_session import OneOnOneSession
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.room_state_service import room_state_service


def _seed_one_on_one_room(db) -> tuple[Room, User, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    aud1 = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    aud2 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    aud3 = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, aud1, aud2, aud3])
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
    db.add(RoomParticipant(room_id=room.id, user_id=aud3.id, role=PlayerRole.AUDIENCE))
    db.commit()
    db.refresh(room)
    return room, challenger, aud1, aud2, aud3


class TestOneOnOnePrivacyWebSocket:
    def test_obsolete_one_on_one_endpoint_rejected(self, client, db):
        room, challenger, aud1, aud2, _ = _seed_one_on_one_room(db)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/1/users/{challenger.id}") as ws:
                ws.receive_json()

    @pytest.mark.asyncio
    async def test_single_gameroom_websocket_message_isolation(self, client, db):
        """
        Verify that:
        - All participants remain connected to /ws/rooms/{room_id}/users/{user_id}.
        - During Challenger <-> Aud 1:
          - Aud 1 & Challenger receive one_on_one_question, one_on_one_answer, one_on_one_completed.
          - Aud 2 & Aud 3 do NOT receive any private question, answer, or vote texts.
          - Aud 2 & Aud 3 receive public one_on_one_progress.
        """
        room, challenger, aud1, aud2, aud3 = _seed_one_on_one_room(db)

        # Connect all participants to the SINGLE GameRoom WebSocket
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws_chal:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud1.id}") as ws_aud1:
                with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud2.id}") as ws_aud2:
                    with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud3.id}") as ws_aud3:
                        # Consume initial connection messages (room_state_changed)
                        assert ws_chal.receive_json()["type"] == "room_state_changed"
                        assert ws_aud1.receive_json()["type"] == "room_state_changed"
                        assert ws_aud2.receive_json()["type"] == "room_state_changed"
                        assert ws_aud3.receive_json()["type"] == "room_state_changed"

                        # Transition room to ONE_ON_ONE
                        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

                        # Challenger & Aud1 receive room_state_changed + one_on_one_started + one_on_one_progress
                        _ = ws_chal.receive_json()  # room_state_changed
                        s1_start_chal = ws_chal.receive_json()
                        assert s1_start_chal["type"] == "one_on_one_started"
                        assert s1_start_chal["audience_id"] == aud1.id
                        assert s1_start_chal["sequence"] == 1
                        assert ws_chal.receive_json()["type"] == "one_on_one_progress"

                        _ = ws_aud1.receive_json()  # room_state_changed
                        s1_start_aud1 = ws_aud1.receive_json()
                        assert s1_start_aud1["type"] == "one_on_one_started"
                        assert s1_start_aud1["sequence"] == 1
                        assert ws_aud1.receive_json()["type"] == "one_on_one_progress"

                        # Aud 2 and Aud 3 receive room_state_changed + one_on_one_progress (NOT one_on_one_started with private details)
                        _ = ws_aud2.receive_json()  # room_state_changed
                        prog_aud2 = ws_aud2.receive_json()
                        assert prog_aud2["type"] == "one_on_one_progress"
                        assert prog_aud2["completed"] == 0

                        _ = ws_aud3.receive_json()  # room_state_changed
                        prog_aud3 = ws_aud3.receive_json()
                        assert prog_aud3["type"] == "one_on_one_progress"

                        s1 = db.query(OneOnOneSession).where(
                            OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1
                        ).one()

                        # 1. Aud 1 posts private question
                        client.post(
                            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
                            json={"user_id": aud1.id, "text": "Confidential question from Kwame"},
                        )

                        q_chal = ws_chal.receive_json()
                        assert q_chal["type"] == "one_on_one_question"
                        assert q_chal["question"] == "Confidential question from Kwame"

                        q_aud1 = ws_aud1.receive_json()
                        assert q_aud1["type"] == "one_on_one_question"
                        assert q_aud1["question"] == "Confidential question from Kwame"

                        # 2. Challenger posts private answer
                        client.post(
                            f"/rooms/{room.id}/one-on-one/{s1.id}/answer",
                            json={"user_id": challenger.id, "text": "Confidential answer from Ama"},
                        )

                        ans_chal = ws_chal.receive_json()
                        assert ans_chal["type"] == "one_on_one_answer"
                        assert ans_chal["answer"] == "Confidential answer from Ama"

                        ans_aud1 = ws_aud1.receive_json()
                        assert ans_aud1["type"] == "one_on_one_answer"
                        assert ans_aud1["answer"] == "Confidential answer from Ama"

                        # 3. Aud 1 votes YES
                        client.post(
                            f"/rooms/{room.id}/one-on-one/{s1.id}/vote",
                            json={"user_id": aud1.id, "vote": "yes"},
                        )

                        comp_chal = ws_chal.receive_json()
                        assert comp_chal["type"] == "one_on_one_completed"
                        assert comp_chal["result"] == "accepted"

                        comp_aud1 = ws_aud1.receive_json()
                        assert comp_aud1["type"] == "one_on_one_completed"
                        assert comp_aud1["result"] == "accepted"

                        # Public progress received by all
                        pub_prog_chal = ws_chal.receive_json()
                        assert pub_prog_chal["type"] == "one_on_one_progress"
                        assert pub_prog_chal["completed"] == 1

                        pub_prog_aud1 = ws_aud1.receive_json()
                        assert pub_prog_aud1["type"] == "one_on_one_progress"

                        pub_prog_aud2 = ws_aud2.receive_json()
                        assert pub_prog_aud2["type"] == "one_on_one_progress"
                        assert pub_prog_aud2["completed"] == 1

                        pub_prog_aud3 = ws_aud3.receive_json()
                        assert pub_prog_aud3["type"] == "one_on_one_progress"
                        assert pub_prog_aud3["completed"] == 1

                        # Session 2 automatically activates: Challenger & Aud 2 receive one_on_one_started
                        s2_start_chal = ws_chal.receive_json()
                        assert s2_start_chal["type"] == "one_on_one_started"
                        assert s2_start_chal["audience_id"] == aud2.id
                        assert s2_start_chal["sequence"] == 2

                        s2_start_aud2 = ws_aud2.receive_json()
                        assert s2_start_aud2["type"] == "one_on_one_started"
                        assert s2_start_aud2["sequence"] == 2

    @pytest.mark.asyncio
    async def test_reconnection_restores_logical_session_state(self, client, db):
        room, challenger, aud1, aud2, _ = _seed_one_on_one_room(db)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        s1 = db.query(OneOnOneSession).where(
            OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1
        ).one()

        # Submit question
        client.post(
            f"/rooms/{room.id}/one-on-one/{s1.id}/question",
            json={"user_id": aud1.id, "text": "Saved question"},
        )

        # Reconnect Aud 1 -> Should receive one_on_one_started with existing question
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud1.id}") as ws_reconnect:
            init = ws_reconnect.receive_json()
            assert init["type"] == "room_state_changed"

            state_sync = ws_reconnect.receive_json()
            assert state_sync["type"] == "one_on_one_started"
            assert state_sync["session_id"] == s1.id
            assert state_sync["question"] == "Saved question"

        # Reconnect Aud 2 (inactive audience) -> Should receive generic progress, NOT private question
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud2.id}") as ws_reconnect_aud2:
            init = ws_reconnect_aud2.receive_json()
            assert init["type"] == "room_state_changed"

            prog = ws_reconnect_aud2.receive_json()
            assert prog["type"] == "one_on_one_progress"
            assert "Saved question" not in str(prog)

    def test_current_session_recovery_endpoint_authorization(self, client, db):
        room, challenger, aud1, aud2, _ = _seed_one_on_one_room(db)
        s1 = OneOnOneSession(
            room_id=room.id,
            audience_id=aud1.id,
            challenger_id=challenger.id,
            sequence=1,
            state="active",
            question="Private Q",
            answer="Private A",
        )
        db.add(s1)
        db.commit()

        # Aud 1 (active audience) can view question & answer
        resp_aud1 = client.get(f"/rooms/{room.id}/one-on-one/current?user_id={aud1.id}")
        assert resp_aud1.status_code == 200
        assert resp_aud1.json()["active_session"]["question"] == "Private Q"
        assert resp_aud1.json()["active_session"]["answer"] == "Private A"

        # Aud 2 (inactive audience) has private fields masked
        resp_aud2 = client.get(f"/rooms/{room.id}/one-on-one/current?user_id={aud2.id}")
        assert resp_aud2.status_code == 200
        assert resp_aud2.json()["active_session"]["question"] is None
        assert resp_aud2.json()["active_session"]["answer"] is None
