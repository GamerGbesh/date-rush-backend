from app.enums import Gender, PlayerRole, RoomState
from app.models.room import Room
from app.models.user import User
from app.services.room_manager import RoomManager


class TestGetRoomEndpoint:
    def test_returns_404_for_missing_room(self, client):
        response = client.get("/rooms/99999")
        assert response.status_code == 404

    def test_returns_room_detail(self, client, db):
        rm = RoomManager()
        room = rm.create_room(db, Gender.FEMALE)

        response = client.get(f"/rooms/{room.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["room"]["id"] == room.id
        assert data["room"]["state"] == RoomState.WAITING
        assert data["participants"] == []

    def test_returns_active_participants(self, client, db):
        rm = RoomManager()
        room = rm.create_room(db, Gender.MALE)
        user = User(name="Player", gender=Gender.FEMALE)
        db.add(user)
        db.commit()
        db.refresh(user)
        rm.add_participant(db, room, user, PlayerRole.AUDIENCE)
        db.refresh(room)

        response = client.get(f"/rooms/{room.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["participants"]) == 1
        p = data["participants"][0]
        assert p["user_id"] == user.id
        assert p["role"] == PlayerRole.AUDIENCE
        assert p["name"] == "Player"
        assert p["gender"] == Gender.FEMALE

    def test_excludes_departed_participants(self, client, db):
        rm = RoomManager()
        room = rm.create_room(db, Gender.MALE)

        active_user = User(name="Active", gender=Gender.FEMALE)
        left_user = User(name="Left", gender=Gender.FEMALE)
        db.add_all([active_user, left_user])
        db.commit()
        db.refresh(active_user)
        db.refresh(left_user)

        rm.add_participant(db, room, active_user, PlayerRole.AUDIENCE)
        rm.add_participant(db, room, left_user, PlayerRole.AUDIENCE)
        rm.remove_participant(db, room, left_user)
        db.refresh(room)

        response = client.get(f"/rooms/{room.id}")
        data = response.json()
        participant_ids = {p["user_id"] for p in data["participants"]}
        assert active_user.id in participant_ids
        assert left_user.id not in participant_ids
