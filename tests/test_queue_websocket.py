import pytest
from app.enums import Gender, UserState
from app.models.user import User


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
