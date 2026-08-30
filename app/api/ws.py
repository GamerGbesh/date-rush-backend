from datetime import datetime, timezone
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select

from app.config import settings
from app import database
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
) -> None:
    """
    WebSocket endpoint for public events in a game room.

    1. Validates that the room exists and the user is an active participant.
    2. Accepts the connection and registers with WebSocketManager.
    3. Immediately delivers the room's current state.
    4. Keeps the socket open; unregisters on disconnect without altering persistent DB state.
    """
    logger.info("Incoming WebSocket connection attempt for room %d by user %d", room_id, user_id)
    initial_payloads = []
    with database.SessionLocal() as db:
        # Verify participant membership
        participant = db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id,
                RoomParticipant.left_at.is_(None),
            )
        ).scalars().first()

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
            logger.warning("WebSocket rejected: room %d not found in DB", room_id)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Prepare room state payload
        room_state = room.state.value if hasattr(room.state, "value") else str(room.state)
        initial_payloads.append({
            "type": "room_state_changed",
            "room_id": room.id,
            "previous_state": None,
            "state": room_state,
        })

        # If the room is already in QUESTIONING, deliver the active question immediately
        if room.state == RoomState.QUESTIONING and room.current_question_id is not None:
            question = db.get(Question, room.current_question_id)
            if question:
                initial_payloads.append({
                    "type": "question_started",
                    "room_id": room.id,
                    "round": room.current_round,
                    "question": {
                        "id": question.id,
                        "text": question.text,
                    },
                })

        # If the room is already in VOTING, deliver voting_started immediately
        if room.state == RoomState.VOTING:
            from app.enums import PlayerRole
            active_voters_count = sum(
                1
                for p in room.participants
                if p.left_at is None and p.role == PlayerRole.AUDIENCE
            )
            initial_payloads.append({
                "type": "voting_started",
                "room_id": room.id,
                "total_voters": active_voters_count,
                "timeout_seconds": settings.VOTING_TIMEOUT_SECONDS,
            })

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
                initial_payloads.append({
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
                })
            else:
                initial_payloads.append({
                    "type": "one_on_one_progress",
                    "room_id": room.id,
                    "completed": completed_sessions,
                    "total": total_sessions,
                })

        # If the room is in FINAL_SELECTION, deliver final_selection_started
        if room.state == RoomState.FINAL_SELECTION:
            from app.services.match_service import match_service
            if user_id == room.challenger_id:
                finalist_users = match_service.get_eligible_finalists(db, room.id)
                initial_payloads.append({
                    "type": "final_selection_started",
                    "room_id": room.id,
                    "candidates": [
                        {"id": u.id, "name": u.name} for u in finalist_users
                    ],
                })
            else:
                initial_payloads.append({
                    "type": "final_selection_started",
                    "room_id": room.id,
                })

    await websocket.accept()
    ws_manager.connect(room_id, user_id, websocket)

    for payload in initial_payloads:
        await websocket.send_json(payload)

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
) -> None:
    """
    Private WebSocket channel for the two matched participants in a MatchRoom.
    Unauthorized users and outsiders are strictly rejected.
    """
    logger.info("Incoming Match Room WS connection attempt: match_room_id=%d, user_id=%d", match_room_id, user_id)
    from app.enums import MatchRoomState
    from app.models.match_contact import MatchContact
    from app.models.match_room import MatchRoom
    from app.models.user import User

    initial_payload = None
    with database.SessionLocal() as db:
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

        my_contact = db.execute(
            select(MatchContact).where(
                MatchContact.match_room_id == match_room_id,
                MatchContact.user_id == user_id,
            )
        ).scalars().first()

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
            ).scalars().first()
            partner_user = db.get(User, partner_id)

            initial_payload = {
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
        else:
            initial_payload = {
                "type": "match_room_state",
                "state": match_room.state.value,
                "my_contact_submitted": my_contact is not None,
                "partner_contact_available": False,
            }

    await websocket.accept()
    ws_manager.connect_match_room(match_room_id, user_id, websocket)
    if initial_payload:
        await websocket.send_json(initial_payload)

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
) -> None:
    """
    WebSocket endpoint for the waiting queue.
    
    1. Validates that the user exists.
    2. Accepts connection and registers with ws_manager.connect_queue(user_id, websocket).
    3. If user is already IN_GAME, MATCHED, or COMPLETED, delivers event immediately.
    4. Otherwise places or ensures user is in QUEUED state in DB.
    5. Delivers current queue_status statistics immediately.
    6. Attempts to form rooms if threshold is met (notifying assigned users via WS).
    7. Automatically evicts the user from the queue on disconnect (instant cleanup).
    """
    logger.info("Incoming Queue WS connection attempt: user_id=%d", user_id)
    with database.SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            logger.warning("Queue WS rejected: user %d not found", user_id)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.accept()
        ws_manager.connect_queue(user_id, websocket)

        if user.state == UserState.IN_GAME:
            participant = db.execute(
                select(RoomParticipant).where(
                    RoomParticipant.user_id == user.id,
                    RoomParticipant.left_at.is_(None),
                )
            ).scalars().first()
            if participant:
                role_val = participant.role.value if participant.role else "audience"
                await websocket.send_json(
                    {"type": "room_assigned", "room_id": participant.room_id, "role": role_val}
                )
        elif user.state == UserState.MATCHED:
            from app.models.match import Match
            from sqlalchemy import or_
            match = db.execute(
                select(Match).where(
                    or_(Match.challenger_id == user.id, Match.audience_id == user.id)
                ).order_by(Match.id.desc())
            ).scalars().first()
            await websocket.send_json({"type": "matched", "match_id": match.id if match else None})
        elif user.state == UserState.COMPLETED:
            await websocket.send_json({"type": "completed"})
        else:
            # User is in queue
            if user.state != UserState.QUEUED:
                user.state = UserState.QUEUED
                user.queued_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(user)

            # Broadcast updated queue status to all connected waiting users (including newly connected user)
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
        with database.SessionLocal() as db:
            user = db.get(User, user_id)
            if user and user.state == UserState.QUEUED:
                user.state = UserState.WAITING
                user.queued_at = None
                db.commit()
                logger.info("User %d returned to WAITING on queue disconnect", user_id)
                queue_manager.broadcast_queue_status(db)
    except Exception:
        ws_manager.disconnect_queue(user_id)
        logger.exception("Queue WS exception for user %d", user_id)
        with database.SessionLocal() as db:
            user = db.get(User, user_id)
            if user and user.state == UserState.QUEUED:
                user.state = UserState.WAITING
                user.queued_at = None
                db.commit()
                queue_manager.broadcast_queue_status(db)



