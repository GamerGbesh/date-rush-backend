from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.room import Room, RoomParticipant
from app.models.user import User


def _seed_voting_room(db) -> tuple[Room, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    aud1 = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
    aud2 = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, aud1, aud2])
    db.commit()

    room = Room(
        state=RoomState.VOTING,
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


class TestVotingWebSocketEvents:
    def test_voting_lifecycle_websocket_events(self, client, db):
        room, challenger, aud1, aud2 = _seed_voting_room(db)

        with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud1.id}") as ws1:
            with client.websocket_connect(f"/ws/rooms/{room.id}/users/{aud2.id}") as ws2:
                # 1. Verify initial events on connect in VOTING state
                init1_state = ws1.receive_json()
                init1_voting = ws1.receive_json()
                assert init1_state["type"] == "room_state_changed"
                assert init1_state["state"] == "voting"
                assert init1_voting["type"] == "voting_started"
                assert init1_voting["total_voters"] == 2

                init2_state = ws2.receive_json()
                init2_voting = ws2.receive_json()
                assert init2_state["state"] == "voting"
                assert init2_voting["type"] == "voting_started"

                # 2. Aud 1 votes YES -> vote_progress broadcast
                resp1 = client.post(
                    f"/rooms/{room.id}/vote",
                    json={"user_id": aud1.id, "vote": "yes"},
                )
                assert resp1.status_code == 201

                prog1_ws1 = ws1.receive_json()
                prog1_ws2 = ws2.receive_json()
                assert prog1_ws1["type"] == "vote_progress"
                assert prog1_ws1["submitted"] == 1
                assert prog1_ws1["total"] == 2
                assert prog1_ws2["type"] == "vote_progress"

                # 3. Aud 2 votes NO -> final vote!
                resp2 = client.post(
                    f"/rooms/{room.id}/vote",
                    json={"user_id": aud2.id, "vote": "no"},
                )
                assert resp2.status_code == 201

                # Events on ws1 (survivor) and ws2 (eliminated)
                # ws1 receives: vote_progress -> voting_completed -> room_state_changed (elimination) -> participants_eliminated -> room_state_changed (final)
                events_ws1 = [ws1.receive_json() for _ in range(5)]
                types_ws1 = [e["type"] for e in events_ws1]

                assert "vote_progress" in types_ws1
                assert "voting_completed" in types_ws1
                assert "participants_eliminated" in types_ws1
                elim_event = next(e for e in events_ws1 if e["type"] == "participants_eliminated")
                assert elim_event["remaining_count"] == 1

                # ws2 (eliminated) receives personalized "eliminated" event
                events_ws2 = []
                while True:
                    try:
                        e = ws2.receive_json()
                        events_ws2.append(e)
                        if e["type"] == "eliminated":
                            break
                    except Exception:
                        break

                types_ws2 = [e["type"] for e in events_ws2]
                assert "eliminated" in types_ws2
