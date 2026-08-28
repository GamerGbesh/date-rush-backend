from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.room import Room, RoomParticipant
from app.models.user import User


def _seed_room(db, state: RoomState = RoomState.READY) -> Room:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    aud1 = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    aud2 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, aud1, aud2])
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
    db.add(RoomParticipant(room_id=room.id, user_id=aud1.id, role=PlayerRole.AUDIENCE))
    db.add(RoomParticipant(room_id=room.id, user_id=aud2.id, role=PlayerRole.AUDIENCE))
    db.commit()
    db.refresh(room)
    return room


class TestAdminRoomInspection:
    def test_get_room_admin_details(self, client, db):
        room = _seed_room(db, RoomState.QUESTIONING)
        room.current_round = 1
        db.commit()

        resp = client.get(f"/admin/rooms/{room.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == room.id
        assert data["state"] == "questioning"
        assert data["current_round"] == 1
        assert data["audience_count"] == 2
        assert data["challenger"]["name"] == "Ama"
        assert len(data["audience"]) == 2
        audience_names = [a["name"] for a in data["audience"]]
        assert "Kwame" in audience_names
        assert "Kofi" in audience_names

    def test_get_nonexistent_room_returns_404(self, client):
        resp = client.get("/admin/rooms/99999")
        assert resp.status_code == 404


class TestAdminTransitionAPI:
    def test_valid_transition_returns_updated_room(self, client, db):
        room = _seed_room(db, RoomState.READY)
        resp = client.post(
            f"/admin/rooms/{room.id}/transition",
            json={"state": "intro"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "intro"

    def test_invalid_transition_returns_409_conflict(self, client, db):
        room = _seed_room(db, RoomState.READY)
        resp = client.post(
            f"/admin/rooms/{room.id}/transition",
            json={"state": "voting"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert "Invalid room transition: ready → voting" in data["detail"]

    def test_start_convenience_endpoint(self, client, db):
        room = _seed_room(db, RoomState.READY)
        resp = client.post(f"/admin/rooms/{room.id}/start")
        assert resp.status_code == 200
        assert resp.json()["state"] == "intro"

    def test_start_questioning_convenience_endpoint(self, client, db):
        room = _seed_room(db, RoomState.INTRO)
        resp = client.post(f"/admin/rooms/{room.id}/start-questioning")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "questioning"
        assert data["current_round"] == 1

    def test_history_endpoint(self, client, db):
        room = _seed_room(db, RoomState.READY)
        client.post(f"/admin/rooms/{room.id}/start")
        client.post(f"/admin/rooms/{room.id}/start-questioning")

        resp = client.get(f"/admin/rooms/{room.id}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 2
        assert history[0]["from_state"] == "ready"
        assert history[0]["to_state"] == "intro"
        assert history[1]["from_state"] == "intro"
        assert history[1]["to_state"] == "questioning"
