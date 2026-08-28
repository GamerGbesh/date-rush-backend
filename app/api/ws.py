"""
WebSocket API router for live room event connections.
"""

import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import RoomState
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
    WebSocket endpoint for participants in a game room.

    1. Validates that the room exists and the user is an active participant.
    2. Accepts the connection and registers with WebSocketManager.
    3. Immediately delivers the room's current state (and active question if in QUESTIONING).
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
