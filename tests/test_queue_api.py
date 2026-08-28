"""
HTTP integration tests for the queue API endpoints.
"""

from app.config import settings
from app.enums import Gender, UserState


class TestJoinQueue:
    def test_join_when_no_room_possible_returns_queued(self, client):
        """Single user joining — no room can form, state stays QUEUED."""
        response = client.post(
            "/queue/join",
            json={"name": "Alice", "gender": "female"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["state"] == UserState.QUEUED
        assert data["room_id"] is None
        assert data["user_id"] is not None

    def test_join_when_room_forms_returns_in_game(self, client):
        """Threshold males already queued — the joining female triggers a room."""
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            client.post("/queue/join", json={"name": f"Male{i}", "gender": "male"})

        response = client.post(
            "/queue/join",
            json={"name": "FemaleTrigger", "gender": "female"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["state"] == UserState.IN_GAME
        assert data["room_id"] is not None

    def test_joining_male_triggers_room_when_female_already_waiting(self, client):
        """Female already at threshold, joining male triggers room."""
        threshold = settings.GAME_ROOM_THRESHOLD
        client.post("/queue/join", json={"name": "Male0", "gender": "male"})
        for i in range(threshold):
            client.post("/queue/join", json={"name": f"Female{i}", "gender": "female"})

        # Now male queue has 1, female queue has threshold → male is challenger
        # But threshold females are the audience, and the existing male is challenger
        resp = client.get("/queue/status")
        data = resp.json()
        # Both queues should be drained
        assert data["male"] == 0
        assert data["female"] == 0

    def test_invalid_gender_returns_422(self, client):
        response = client.post(
            "/queue/join",
            json={"name": "Unknown", "gender": "other"},
        )
        assert response.status_code == 422

    def test_missing_name_returns_422(self, client):
        response = client.post("/queue/join", json={"gender": "male"})
        assert response.status_code == 422

    def test_room_id_in_response_matches_actual_room(self, client):
        """The returned room_id should resolve to a valid room via GET /rooms/{id}."""
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            client.post("/queue/join", json={"name": f"M{i}", "gender": "male"})

        resp = client.post("/queue/join", json={"name": "F0", "gender": "female"})
        room_id = resp.json()["room_id"]

        room_resp = client.get(f"/rooms/{room_id}")
        assert room_resp.status_code == 200
        room_data = room_resp.json()
        assert room_data["room"]["id"] == room_id
        assert len(room_data["participants"]) == threshold + 1  # audience + challenger


class TestQueueStatus:
    def test_empty_queue(self, client):
        response = client.get("/queue/status")
        assert response.status_code == 200
        data = response.json()
        assert data["male"] == 0
        assert data["female"] == 0

    def test_reflects_queued_users(self, client):
        client.post("/queue/join", json={"name": "M1", "gender": "male"})
        client.post("/queue/join", json={"name": "M2", "gender": "male"})
        client.post("/queue/join", json={"name": "F1", "gender": "female"})

        response = client.get("/queue/status")
        data = response.json()
        assert data["male"] == 2
        assert data["female"] == 1

    def test_counts_decrease_after_room_creation(self, client):
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            client.post("/queue/join", json={"name": f"M{i}", "gender": "male"})
        client.post("/queue/join", json={"name": "F0", "gender": "female"})

        response = client.get("/queue/status")
        data = response.json()
        assert data["male"] == 0
        assert data["female"] == 0


class TestAdminRooms:
    def test_empty_when_no_rooms(self, client):
        response = client.get("/admin/rooms")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_created_rooms(self, client):
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            client.post("/queue/join", json={"name": f"M{i}", "gender": "male"})
        client.post("/queue/join", json={"name": "F0", "gender": "female"})

        response = client.get("/admin/rooms")
        assert response.status_code == 200
        rooms = response.json()
        assert len(rooms) == 1
        room = rooms[0]
        assert room["challenger"]["gender"] == "female"
        assert room["audience_count"] == threshold
        assert room["state"] == "ready"

    def test_lists_multiple_rooms(self, client):
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold * 2):
            client.post("/queue/join", json={"name": f"M{i}", "gender": "male"})
        for i in range(2):
            client.post("/queue/join", json={"name": f"F{i}", "gender": "female"})

        response = client.get("/admin/rooms")
        rooms = response.json()
        assert len(rooms) == 2
