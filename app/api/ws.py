from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.enums import Gender, RoomState, UserState
from app.models.one_on_one_session import OneOnOneSession
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.queue_manager import queue_manager
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

    # If the room is already in ONE_ON_ONE, deliver one-on-one session info
    if room.state == RoomState.ONE_ON_ONE:
        from app.enums import OneOnOneSessionState
        from app.services.one_on_one_service import one_on_one_service
        active_session = one_on_one_service.get_active_session(db, room.id)
        total_sessions = db.execute(
            select(func.count(OneOnOneSession.id)).where(
                OneOnOneSession.room_id == room.id
            )
        ).scalar_one()
        completed_sessions = db.execute(
            select(func.count(OneOnOneSession.id)).where(
                OneOnOneSession.room_id == room.id,
                OneOnOneSession.state == OneOnOneSessionState.COMPLETED,
            )
        ).scalar_one()

        if active_session and user_id in (active_session.challenger_id, active_session.audience_id):
            await websocket.send_json(
                {
                    "type": "one_on_one_started",
                    "room_id": room.id,
                    "session_id": active_session.id,
                    "audience_id": active_session.audience_id,
                    "challenger_id": active_session.challenger_id,
                    "sequence": active_session.sequence,
                    "total": total_sessions,
                    "state": active_session.state.value if hasattr(active_session.state, "value") else str(active_session.state),
                    "question": active_session.question,
                    "answer": active_session.answer,
                }
            )
        else:
            await websocket.send_json(
                {
                    "type": "one_on_one_progress",
                    "room_id": room.id,
                    "completed": completed_sessions,
                    "total": total_sessions,
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
        ws_manager.disconnect(room_id, user_id, websocket)
        logger.info(
            "WebSocket disconnected cleanly for room %d user %d", room_id, user_id
        )
    except Exception:
        ws_manager.disconnect(room_id, user_id, websocket)
        logger.exception(
            "WebSocket exception occurred for room %d user %d", room_id, user_id
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


@router.websocket("/queue/users/{user_id}")
async def queue_websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for the waiting queue.
    
    1. Validates that the user exists.
    2. Registers the connection with ws_manager.connect_queue(user_id, websocket).
    3. Places or ensures user is in QUEUED state in DB.
    4. Delivers current queue_status statistics immediately.
    5. Attempts to form rooms if threshold is met.
    6. Automatically evicts the user from the queue on disconnect (instant cleanup).
    """
    user = db.get(User, user_id)
    if not user:
        logger.warning("Queue WS rejected: user %d not found", user_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ws_manager.connect_queue(user_id, websocket)

    # If user is already in game, notify immediately
    if user.state == UserState.IN_GAME:
        participant = db.execute(
            select(RoomParticipant).where(
                RoomParticipant.user_id == user.id,
                RoomParticipant.left_at.is_(None),
            )
        ).scalar_one_or_none()
        if participant:
            await websocket.send_json(
                {"type": "room_assigned", "room_id": participant.room_id}
            )
    elif user.state not in (UserState.MATCHED, UserState.COMPLETED):
        # Ensure user is queued in DB
        if user.state != UserState.QUEUED:
            user.state = UserState.QUEUED
            user.queued_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(user)

    # Deliver immediate queue statistics
    active_rooms = db.execute(
        select(func.count(Room.id)).where(Room.state != RoomState.COMPLETED)
    ).scalar_one()

    male_count = queue_manager.get_size(db, Gender.MALE)
    female_count = queue_manager.get_size(db, Gender.FEMALE)

    await websocket.send_json(
        {
            "type": "queue_status",
            "male": male_count,
            "female": female_count,
            "active_rooms": active_rooms,
        }
    )

    # Broadcast updated queue status to everyone in the waiting room
    queue_manager.broadcast_queue_status(db)

    # Check if rooms can now be formed
    queue_manager.try_create_rooms(db)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_queue(user_id)
        logger.info("Queue WS disconnected cleanly for user %d", user_id)
        # Re-fetch user to check if they were assigned to a room before disconnecting
        db.refresh(user)
        if user.state == UserState.QUEUED:
            user.state = UserState.WAITING
            user.queued_at = None
            db.commit()
            logger.info("User %d returned to WAITING on queue disconnect", user_id)
            queue_manager.broadcast_queue_status(db)
    except Exception:
        ws_manager.disconnect_queue(user_id)
        logger.exception("Queue WS exception for user %d", user_id)
        db.refresh(user)
        if user.state == UserState.QUEUED:
            user.state = UserState.WAITING
            user.queued_at = None
            db.commit()
            queue_manager.broadcast_queue_status(db)


