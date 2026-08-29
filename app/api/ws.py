"""
WebSocket API router for live public room events and private 1-on-1 session channels.
"""

import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.enums import RoomState
from app.models.one_on_one_session import OneOnOneSession
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/rooms/{room_id}/users/{user_id}")
async def room_websocket_endpoint(
    websocket: WebSocket,
    room_id: int,
    user_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for public events in a game room.

    1. Validates that the room exists and the user is an active participant.
    2. Accepts the connection and registers with WebSocketManager.
    3. Immediately delivers the room's current state.
    4. Keeps the socket open; unregisters on disconnect without altering persistent DB state.
    """
    # Verify participant membership
    participant = db.execute(
        select(RoomParticipant).where(
            RoomParticipant.room_id == room_id,
            RoomParticipant.user_id == user_id,
            RoomParticipant.left_at.is_(None),
        )
    ).scalar_one_or_none()

    if not participant:
        logger.warning(
            "WebSocket rejected: user %d is not an active participant in room %d",
            user_id,
            room_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    room = db.get(Room, room_id)
    if not room:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ws_manager.connect(room_id, user_id, websocket)

    # Immediately push current room state
    initial_payload = {
        "type": "room_state_changed",
        "room_id": room.id,
        "previous_state": None,
        "state": room.state.value if hasattr(room.state, "value") else str(room.state),
    }
    await websocket.send_json(initial_payload)

    # If the room is already in QUESTIONING, deliver the active question immediately
    if room.state == RoomState.QUESTIONING and room.current_question_id is not None:
        question = db.get(Question, room.current_question_id)
        if question:
            await websocket.send_json(
                {
                    "type": "question_started",
                    "room_id": room.id,
                    "round": room.current_round,
                    "question": {
                        "id": question.id,
                        "text": question.text,
                    },
                }
            )

    # If the room is already in VOTING, deliver voting_started immediately
    if room.state == RoomState.VOTING:
        from app.enums import PlayerRole
        active_voters_count = sum(
            1
            for p in room.participants
            if p.left_at is None and p.role == PlayerRole.AUDIENCE
        )
        await websocket.send_json(
            {
                "type": "voting_started",
                "room_id": room.id,
                "total_voters": active_voters_count,
                "timeout_seconds": settings.VOTING_TIMEOUT_SECONDS,
            }
        )

    # If the room is in FINAL_SELECTION, deliver final_selection_started
    if room.state == RoomState.FINAL_SELECTION:
        from app.services.match_service import match_service
        if user_id == room.challenger_id:
            finalist_users = match_service.get_eligible_finalists(db, room.id)
            await websocket.send_json(
                {
                    "type": "final_selection_started",
                    "room_id": room.id,
                    "candidates": [
                        {"id": u.id, "name": u.name} for u in finalist_users
                    ],
                }
            )
        else:
            await websocket.send_json(
                {
                    "type": "final_selection_started",
                    "room_id": room.id,
                }
            )

    try:
        while True:
            # Keep alive and receive any client-sent text
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room_id, user_id)
        logger.info(
            "WebSocket disconnected cleanly for room %d user %d", room_id, user_id
        )
    except Exception:
        ws_manager.disconnect(room_id, user_id)
        logger.exception(
            "WebSocket exception occurred for room %d user %d", room_id, user_id
        )


@router.websocket("/rooms/{room_id}/one-on-one/{session_id}/users/{user_id}")
async def private_one_on_one_websocket_endpoint(
    websocket: WebSocket,
    room_id: int,
    session_id: int,
    user_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Private WebSocket endpoint for 1-on-1 interaction.
    Strictly restricted to the challenger and the active audience member of this session.
    """
    session = db.get(OneOnOneSession, session_id)
    if not session or session.room_id != room_id:
        logger.warning(
            "Private WS rejected: session %d not found for room %d",
            session_id,
            room_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Strictly authorize ONLY the challenger and session audience member
    if user_id not in (session.challenger_id, session.audience_id):
        logger.warning(
            "Private WS rejected: user %d is neither challenger nor audience in session %d",
            user_id,
            session_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ws_manager.connect_session(session_id, user_id, websocket)

    # Deliver current private session state immediately upon connection
    initial_payload = {
        "type": "private_session_state",
        "session_id": session.id,
        "state": session.state.value if hasattr(session.state, "value") else str(session.state),
        "sequence": session.sequence,
        "audience_id": session.audience_id,
        "challenger_id": session.challenger_id,
        "question": session.question,
        "answer": session.answer,
        "vote": session.vote.value if session.vote else None,
    }
    await websocket.send_json(initial_payload)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_session(session_id, user_id)
        logger.info(
            "Private WebSocket disconnected cleanly for session %d user %d",
            session_id,
            user_id,
        )
    except Exception:
        ws_manager.disconnect_session(session_id, user_id)
        logger.exception(
            "Private WebSocket exception for session %d user %d",
            session_id,
            user_id,
        )


@router.websocket("/match-rooms/{match_room_id}/users/{user_id}")
async def match_room_websocket_endpoint(
    websocket: WebSocket,
    match_room_id: int,
    user_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Private WebSocket channel for the two matched participants in a MatchRoom.
    Unauthorized users and outsiders are strictly rejected.
    """
    from app.enums import MatchRoomState
    from app.models.match_contact import MatchContact
    from app.models.match_room import MatchRoom
    from app.models.user import User

    match_room = db.get(MatchRoom, match_room_id)
    if not match_room:
        logger.warning(
            "Match room WS rejected: match room %d does not exist", match_room_id
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    match = match_room.match
    if not match or user_id not in (match.challenger_id, match.audience_id):
        logger.warning(
            "Match room WS rejected: user %d is not a participant in match room %d",
            user_id,
            match_room_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ws_manager.connect_match_room(match_room_id, user_id, websocket)

    my_contact = db.execute(
        select(MatchContact).where(
            MatchContact.match_room_id == match_room_id,
            MatchContact.user_id == user_id,
        )
    ).scalar_one_or_none()

    partner_id = (
        match.audience_id if user_id == match.challenger_id else match.challenger_id
    )

    if match_room.state in (
        MatchRoomState.CONTACTS_EXCHANGED,
        MatchRoomState.COMPLETED,
    ):
        partner_contact = db.execute(
            select(MatchContact).where(
                MatchContact.match_room_id == match_room_id,
                MatchContact.user_id == partner_id,
            )
        ).scalar_one_or_none()
        partner_user = db.get(User, partner_id)

        await websocket.send_json(
            {
                "type": "match_room_state",
                "state": match_room.state.value,
                "my_contact_submitted": True,
                "partner_contact_available": True,
                "partner": {
                    "name": partner_user.name if partner_user else "",
                    "whatsapp": partner_contact.whatsapp if partner_contact else None,
                    "snapchat": partner_contact.snapchat if partner_contact else None,
                },
            }
        )
    else:
        await websocket.send_json(
            {
                "type": "match_room_state",
                "state": match_room.state.value,
                "my_contact_submitted": my_contact is not None,
                "partner_contact_available": False,
            }
        )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_match_room(match_room_id, user_id)
        logger.info(
            "Match room WS disconnected cleanly for match room %d user %d",
            match_room_id,
            user_id,
        )
    except Exception:
        ws_manager.disconnect_match_room(match_room_id, user_id)
        logger.exception(
            "Match room WS exception for match room %d user %d",
            match_room_id,
            user_id,
        )

