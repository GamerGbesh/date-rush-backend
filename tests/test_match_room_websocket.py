import pytest
from starlette.websockets import WebSocketDisconnect

from app.enums import Gender, MatchStatus, ParticipantStatus, PlayerRole, RoomState, UserState
from app.models.match import Match
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.match_room_service import match_room_service


def _seed_match_room_for_ws(db) -> tuple[int, User, User, User]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    cand = User(name="Kofi", gender=Gender.MALE, state=UserState.IN_GAME)
    outsider = User(name="Yaw", gender=Gender.MALE, state=UserState.IN_GAME)
    db.add_all([challenger, cand, outsider])
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
    db.add(RoomParticipant(room_id=room.id, user_id=cand.id, role=PlayerRole.AUDIENCE, status=ParticipantStatus.FINALIST))
    db.commit()

    match = Match(room_id=room.id, challenger_id=challenger.id, audience_id=cand.id, status=MatchStatus.CREATED)
    db.add(match)
    db.commit()

    match_room = match_room_service.create_match_room(db, match.id)
    return match_room.id, challenger, cand, outsider


class TestMatchRoomWebSocket:
    def test_unauthorized_user_rejected(self, client, db):
        mr_id, _, _, outsider = _seed_match_room_for_ws(db)

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/match-rooms/{mr_id}/users/{outsider.id}") as ws:
                ws.receive_json()

    def test_contact_exchange_websocket_events(self, client, db):
        mr_id, challenger, cand, _ = _seed_match_room_for_ws(db)

        with client.websocket_connect(f"/ws/match-rooms/{mr_id}/users/{challenger.id}") as ws_chal:
            with client.websocket_connect(f"/ws/match-rooms/{mr_id}/users/{cand.id}") as ws_cand:
                # 1. Initial connect state
                ev_chal_init = ws_chal.receive_json()
                assert ev_chal_init["type"] == "match_room_state"
                assert ev_chal_init["state"] == "waiting_for_contacts"
                assert ev_chal_init["my_contact_submitted"] is False
                assert ev_chal_init["partner_contact_available"] is False

                ev_cand_init = ws_cand.receive_json()
                assert ev_cand_init["type"] == "match_room_state"
                assert ev_cand_init["my_contact_submitted"] is False

                # 2. Challenger submits WhatsApp
                client.post(
                    f"/match-rooms/{mr_id}/contacts",
                    json={"user_id": challenger.id, "whatsapp": "+233201111111", "snapchat": None},
                )

                # Challenger receives confirmation
                ev_chal_sub = ws_chal.receive_json()
                assert ev_chal_sub["type"] == "contact_submission_status"
                assert ev_chal_sub["submitted"] is True

                # Candidate receives waiting notification
                ev_cand_wait = ws_cand.receive_json()
                assert ev_cand_wait["type"] == "waiting_for_partner"

                # 3. Candidate submits Snapchat -> Triggers exchange!
                client.post(
                    f"/match-rooms/{mr_id}/contacts",
                    json={"user_id": cand.id, "whatsapp": None, "snapchat": "kofi_snap"},
                )

                # Candidate receives submission confirmation
                ev_cand_sub = ws_cand.receive_json()
                assert ev_cand_sub["type"] == "contact_submission_status"

                # Challenger receives Candidate's contact info
                ev_chal_exc = ws_chal.receive_json()
                assert ev_chal_exc["type"] == "contacts_exchanged"
                assert ev_chal_exc["partner"]["name"] == "Kofi"
                assert ev_chal_exc["partner"]["snapchat"] == "kofi_snap"

                # Challenger receives match_completed
                ev_chal_comp = ws_chal.receive_json()
                assert ev_chal_comp["type"] == "match_completed"

                # Candidate receives Challenger's contact info
                ev_cand_exc = ws_cand.receive_json()
                assert ev_cand_exc["type"] == "contacts_exchanged"
                assert ev_cand_exc["partner"]["name"] == "Ama"
                assert ev_cand_exc["partner"]["whatsapp"] == "+233201111111"

                # Candidate receives match_completed
                ev_cand_comp = ws_cand.receive_json()
                assert ev_cand_comp["type"] == "match_completed"

        # 4. Reconnection post-exchange delivers partner info immediately
        with client.websocket_connect(f"/ws/match-rooms/{mr_id}/users/{challenger.id}") as ws_reconnect:
            ev_reconnect = ws_reconnect.receive_json()
            assert ev_reconnect["type"] == "match_room_state"
            assert ev_reconnect["state"] == "completed"
            assert ev_reconnect["partner_contact_available"] is True
            assert ev_reconnect["partner"]["name"] == "Kofi"
            assert ev_reconnect["partner"]["snapchat"] == "kofi_snap"
