import pytest

from app.enums import Gender, ParticipantStatus, PlayerRole, RoomState, UserState
from app.models.room import Room, RoomParticipant
from app.models.user import User


def _seed_selection_room(db) -> tuple[Room, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand1 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    cand2 = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand1, cand2])
    db.commit()

    room = Room(
        state=RoomState.FINAL_SELECTION,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    db.add(RoomParticipant(room_id=room.id, user_id=cand1.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))
    db.add(RoomParticipant(room_id=room.id, user_id=cand2.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))
    db.commit()
    db.refresh(room)
    return room, challenger, cand1, cand2


class TestMatchWebSocketEvents:
    def test_match_websocket_event_isolation_and_delivery(self, client, db):
        room, challenger, cand1, cand2 = _seed_selection_room(db)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{challenger.id}") as ws_chal:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{cand1.id}") as ws_c1:
                with client.websocket_connect(f"/ws/rooms/{room.id}/users/{cand2.id}") as ws_c2:
                    # 1. Initial connect events in FINAL_SELECTION state
                    ev_chal_state = ws_chal.receive_json()
                    ev_chal_start = ws_chal.receive_json()
                    assert ev_chal_state["state"] == "final_selection"
                    assert ev_chal_start["type"] == "final_selection_started"
                    assert "candidates" in ev_chal_start
                    assert len(ev_chal_start["candidates"]) == 2

                    ev_c1_state = ws_c1.receive_json()
                    ev_c1_start = ws_c1.receive_json()
                    assert ev_c1_state["state"] == "final_selection"
                    assert ev_c1_start["type"] == "final_selection_started"
                    assert "candidates" not in ev_c1_start  # non-challenger has no candidate list

                    ev_c2_state = ws_c2.receive_json()
                    ev_c2_start = ws_c2.receive_json()
                    assert ev_c2_state["state"] == "final_selection"
                    assert ev_c2_start["type"] == "final_selection_started"
                    assert "candidates" not in ev_c2_start

                    # 2. Challenger selects Cand 1
                    resp = client.post(
                        f"/rooms/{room.id}/final-selection",
                        json={"user_id": challenger.id, "candidate_id": cand1.id},
                    )
                    assert resp.status_code == 201

                    # 3. Challenger receives private match_created followed by room completion broadcasts
                    ev1_chal = ws_chal.receive_json()
                    assert ev1_chal["type"] == "match_created"
                    assert ev1_chal["partner"]["id"] == cand1.id
                    assert ev1_chal["partner"]["name"] == "Kofi"

                    ev2_chal = ws_chal.receive_json()
                    assert ev2_chal["type"] == "final_selection_completed"

                    # 4. Cand 1 (selected) receives private match_created followed by completion broadcasts
                    ev1_c1 = ws_c1.receive_json()
                    assert ev1_c1["type"] == "match_created"
                    assert ev1_c1["partner"]["id"] == challenger.id
                    assert ev1_c1["partner"]["name"] == "Ama"

                    ev2_c1 = ws_c1.receive_json()
                    assert ev2_c1["type"] == "final_selection_completed"

                    # 5. Cand 2 (eliminated) receives personalized "eliminated" event
                    ev1_c2 = ws_c2.receive_json()
                    assert ev1_c2["type"] == "eliminated"
