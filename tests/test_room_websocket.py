import pytest
from starlette.websockets import WebSocketDisconnect

from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.websocket_manager import ws_manager


def _seed_game_room(db, state: RoomState = RoomState.READY) -> tuple[Room, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, audience])
    db.commit()

    room = Room(
        state=state,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=0,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    db.add(RoomParticipant(room_id=room.id, user_id=audience.id, role=PlayerRole.AUDIENCE))
    db.commit()
    db.refresh(room)
    return room, challenger, audience


class TestRoomWebSocket:
    def test_connect_receives_current_state_immediately(self, client, db):
        room, challenger, _ = _seed_game_room(db, RoomState.VOTING)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws:
            data = ws.receive_json()
            assert data["type"] == "room_state_changed"
            assert data["room_id"] == room.id
            assert data["state"] == "voting"

    def test_state_transition_broadcasts_to_connected_client(self, client, db):
        room, challenger, audience = _seed_game_room(db, RoomState.READY)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws_chal:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{audience.id}") as ws_aud:
                # Initial states received
                init_chal = ws_chal.receive_json()
                init_aud = ws_aud.receive_json()
                assert init_chal["state"] == "ready"
                assert init_aud["state"] == "ready"

                # Transition via admin API
                resp = client.post(f"/admin/rooms/{room.id}/start")
                assert resp.status_code == 200

                # Both should receive broadcast
                chal_event = ws_chal.receive_json()
                aud_event = ws_aud.receive_json()

                assert chal_event["type"] == "room_state_changed"
                assert chal_event["previous_state"] == "ready"
                assert chal_event["state"] == "intro"

                assert aud_event["type"] == "room_state_changed"
                assert aud_event["previous_state"] == "ready"
                assert aud_event["state"] == "intro"

    def test_non_participant_is_rejected(self, client, db):
        room, _, _ = _seed_game_room(db, RoomState.READY)
        outsider = User(name="Outsider", gender=Gender.MALE, state=UserState.WAITING)
        db.add(outsider)
        db.commit()

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{outsider.id}"):
                pass

    def test_disconnect_removes_from_ws_manager_preserves_db_state(self, client, db):
        room, challenger, _ = _seed_game_room(db, RoomState.READY)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}"):
            assert challenger.id in ws_manager._connections.get(room.id, {})

        # After exiting context manager (disconnect)
        assert challenger.id not in ws_manager._connections.get(room.id, {})

        # User in DB remains IN_GAME
        db.refresh(challenger)
        assert challenger.state == UserState.IN_GAME
