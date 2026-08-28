from app.enums import Gender, UserState


class TestCreateUser:
    def test_creates_user_with_correct_fields(self, client):
        response = client.post(
            "/users",
            json={"name": "Alice", "gender": "female"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Alice"
        assert data["gender"] == "female"
        assert data["id"] is not None
        assert data["created_at"] is not None

    def test_new_user_starts_in_waiting_state(self, client):
        response = client.post(
            "/users",
            json={"name": "Bob", "gender": "male"},
        )
        assert response.status_code == 201
        assert response.json()["state"] == UserState.WAITING

    def test_invalid_gender_returns_422(self, client):
        response = client.post(
            "/users",
            json={"name": "Charlie", "gender": "nonbinary"},
        )
        assert response.status_code == 422

    def test_missing_name_returns_422(self, client):
        response = client.post("/users", json={"gender": "male"})
        assert response.status_code == 422

    def test_multiple_users_same_name_allowed(self, client):
        for _ in range(3):
            resp = client.post("/users", json={"name": "Twin", "gender": "female"})
            assert resp.status_code == 201
