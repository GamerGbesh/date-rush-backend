import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.room import RoomParticipant
from app.models.user import User
from app.schemas.queue import QueueJoinRequest, QueueJoinResponse, QueueStatusResponse
from app.services.queue_manager import queue_manager
from app.enums import Gender, UserState

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/queue", tags=["queue"])


@router.post("/join", response_model=QueueJoinResponse, status_code=201)
def join_queue(payload: QueueJoinRequest, db: Session = Depends(get_db)) -> QueueJoinResponse:
    """
    Register a new user and immediately place them in their gender queue.

    After queuing the user, the system attempts to create any game rooms
    that are now possible.  If the joining user is assigned to a room, the
    response reflects their IN_GAME state and the room ID.

    Flow:
        Create user (WAITING)
            → queue_manager.add()  (QUEUED)
            → queue_manager.try_create_rooms()
            → return current state + room_id (if assigned)
    """
    logger.info("Join queue request received: name='%s', gender=%s", payload.name, payload.gender)
    # 1. Create the user record.
    user = User(name=payload.name, gender=payload.gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User created: id=%d, name='%s', gender=%s", user.id, user.name, user.gender.value)

    # 2. Move into the queue.
    queue_manager.add(db, user)

    # 3. Attempt room creation — may consume this user.
    created_rooms = queue_manager.try_create_rooms(db)
    if created_rooms:
        logger.info("Room creation triggered: %d room(s) formed", len(created_rooms))

    # 4. Refresh to get the latest state (might now be IN_GAME).
    db.refresh(user)

    # 5. Determine room_id if the user was placed in a room.
    room_id: int | None = None
    if user.state == UserState.IN_GAME:
        participant = db.execute(
            select(RoomParticipant).where(
                RoomParticipant.user_id == user.id,
                RoomParticipant.left_at.is_(None),
            )
        ).scalar_one_or_none()
        if participant:
            room_id = participant.room_id

    logger.info("User %d join_queue result: state=%s, room_id=%s", user.id, user.state.value, room_id)
    return QueueJoinResponse(user_id=user.id, state=user.state, room_id=room_id)


@router.get("/status", response_model=QueueStatusResponse)
def queue_status(db: Session = Depends(get_db)) -> QueueStatusResponse:
    """Return the current number of queued users per gender."""
    male_count = queue_manager.get_size(db, Gender.MALE)
    female_count = queue_manager.get_size(db, Gender.FEMALE)
    logger.debug("Queue status queried: male=%d, female=%d", male_count, female_count)
    return QueueStatusResponse(
        male=male_count,
        female=female_count,
    )

