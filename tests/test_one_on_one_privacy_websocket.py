import pytest
from starlette.websockets import WebSocketDisconnect

from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.one_on_one_session import OneOnOneSession
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.room_state_service import room_state_service


def _seed_one_on_one_room(db) -> tuple[Room, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    aud1 = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    aud2 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
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
    db.refresh(room)
    return room, challenger, aud1, aud2


class TestOneOnOnePrivacyWebSocket:
    @pytest.mark.asyncio
    async def test_private_channel_authorization(self, client, db):
        room, challenger, aud1, aud2 = _seed_one_on_one_room(db)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        s1 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()

        # Challenger CAN connect
        with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{challenger.id}") as ws_chal:
            msg = ws_chal.receive_json()
            assert msg["type"] == "private_session_state"
            assert msg["sequence"] == 1

        # Session audience (aud1) CAN connect
        with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{aud1.id}") as ws_aud:
            msg = ws_aud.receive_json()
            assert msg["type"] == "private_session_state"

        # Non-session audience (aud2) is REJECTED
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{aud2.id}") as ws_intruder:
                ws_intruder.receive_json()

    @pytest.mark.asyncio
    async def test_private_messages_not_leaked_to_public_room(self, client, db):
        room, challenger, aud1, aud2 = _seed_one_on_one_room(db)
        await room_state_service.transition(db, room.id, RoomState.ONE_ON_ONE)

        s1 = db.query(OneOnOneSession).where(OneOnOneSession.room_id == room.id, OneOnOneSession.sequence == 1).one()

        # Connect aud2 to public room WebSocket
        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud2.id}") as ws_public:
            ws_public.receive_json()  # room_state_changed

            # Connect aud1 and challenger to private session WebSocket
            with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{aud1.id}") as ws_p_aud:
                with client.websocket_connect(f"/ws/rooms/{room.id}/one-on-one/{s1.id}/users/{challenger.id}") as ws_p_chal:
                    ws_p_aud.receive_json()  # private_session_state
                    ws_p_chal.receive_json()  # private_session_state

                    # 1. Aud 1 posts private question
                    client.post(
                        f"/rooms/{room.id}/one-on-one/{s1.id}/question",
                        json={"user_id": aud1.id, "text": "Secret private question"},
                    )

                    q_aud = ws_p_aud.receive_json()
                    q_chal = ws_p_chal.receive_json()
                    assert q_aud["type"] == "private_question"
                    assert q_aud["text"] == "Secret private question"
                    assert q_chal["type"] == "private_question"

                    # 2. Challenger posts private answer
                    client.post(
                        f"/rooms/{room.id}/one-on-one/{s1.id}/answer",
                        json={"user_id": challenger.id, "text": "Secret private answer"},
                    )

                    ans_aud = ws_p_aud.receive_json()
                    ans_chal = ws_p_chal.receive_json()
                    assert ans_aud["type"] == "private_answer"
                    assert ans_aud["text"] == "Secret private answer"
                    assert ans_chal["type"] == "private_answer"

                    # 3. Aud 1 votes YES
                    client.post(
                        f"/rooms/{room.id}/one-on-one/{s1.id}/vote",
                        json={"user_id": aud1.id, "vote": "yes"},
                    )

                    comp_aud = ws_p_aud.receive_json()
                    comp_chal = ws_p_chal.receive_json()
                    assert comp_aud["type"] == "session_completed"
                    assert comp_chal["type"] == "session_completed"

            # Check public room received ONLY generic progress, no private texts!
            public_events = []
            while True:
                try:
                    ev = ws_public.receive_json()
                    public_events.append(ev)
                    if ev.get("type") == "one_on_one_started" and ev.get("sequence") == 2:
                        break
                except Exception:
                    break

            for ev in public_events:
                assert "Secret private question" not in str(ev)
                assert "Secret private answer" not in str(ev)

            types = [ev["type"] for ev in public_events]
            assert "one_on_one_progress" in types
