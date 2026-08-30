import pytest
from app.enums import Gender, UserState
from app.models.user import User
from app.models.room import Room, RoomParticipant


def _create_user(db, name: str, gender: Gender) -> User:
    user = User(name=name, gender=gender, state=UserState.WAITING)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_queue_websocket_connect_and_disconnect(client, db):
    u1 = _create_user(db, "Alice", Gender.FEMALE)

    # 1. Connect to queue WebSocket
    with client.websocket_connect(f"/ws/queue/users/{u1.id}") as ws:
        init_event = ws.receive_json()
        assert init_event["type"] == "queue_status"
        assert "male" in init_event
        assert "female" in init_event

        db.refresh(u1)
        assert u1.state == UserState.QUEUED

    # 2. On disconnect, user is evicted back to WAITING
    db.refresh(u1)
    assert u1.state == UserState.WAITING


def test_queue_websocket_in_game_user_receives_room_assigned(client, db):
    u1 = _create_user(db, "Alice", Gender.FEMALE)
    u1.state = UserState.IN_GAME
    db.commit()

    room = Room(challenger_id=u1.id, challenger_gender=Gender.FEMALE)
    db.add(room)
    db.flush()

    participant = RoomParticipant(room_id=room.id, user_id=u1.id, role="challenger")
    db.add(participant)
    db.commit()

    with client.websocket_connect(f"/ws/queue/users/{u1.id}") as ws:
        event = ws.receive_json()
        assert event["type"] == "room_assigned"
        assert event["room_id"] == room.id


def test_queue_websocket_room_formed_notifies_all_users(client, db):
    # Create female challenger and 5 male audience members
    female = _create_user(db, "Female1", Gender.FEMALE)
    males = [_create_user(db, f"Male{i}", Gender.MALE) for i in range(1, 6)]

    # Connect female first
    with client.websocket_connect(f"/ws/queue/users/{female.id}") as ws_f:
        ev_f = ws_f.receive_json()
        assert ev_f["type"] == "queue_status"
        assert ev_f["female"] == 1
        assert ev_f["male"] == 0

        # Connect 4 males
        ws_males = []
        for idx, m in enumerate(males[:4], start=1):
            ws_m = client.websocket_connect(f"/ws/queue/users/{m.id}")
            ws_males.append(ws_m)
            ws_m_conn = ws_m.__enter__()
            _ = ws_m_conn.receive_json()  # male's own initial queue_status
            
            # Female receives live broadcast of updated queue status
            broadcast_ev = ws_f.receive_json()
            assert broadcast_ev["type"] == "queue_status"
            assert broadcast_ev["male"] == idx

        # Connect 5th male (triggers threshold of 5 + 1)
        with client.websocket_connect(f"/ws/queue/users/{males[4].id}") as ws_m5:
            m5_events = [ws_m5.receive_json(), ws_m5.receive_json()]
            f_events = [ws_f.receive_json(), ws_f.receive_json()]

            m5_types = {e["type"] for e in m5_events}
            f_types = {e["type"] for e in f_events}

            assert "room_assigned" in m5_types
            assert "queue_status" in m5_types
            assert "room_assigned" in f_types
            assert "queue_status" in f_types

            m5_room_assigned = next(e for e in m5_events if e["type"] == "room_assigned")
            f_room_assigned = next(e for e in f_events if e["type"] == "room_assigned")

            assert m5_room_assigned["room_id"] == f_room_assigned["room_id"]
            assert f_room_assigned["room_id"] is not None

        # Clean up male websockets
        for ws_m in ws_males:
            ws_m.__exit__(None, None, None)

