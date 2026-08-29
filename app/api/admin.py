"""
Admin API router.

Endpoints:
    GET    /admin/rooms                       List all active (non-completed) rooms
    GET    /admin/rooms/{room_id}             Get comprehensive room state & audience details
    POST   /admin/rooms/{room_id}/transition  Transition room to a specified state
    POST   /admin/rooms/{room_id}/start       Convenience endpoint: READY -> INTRO
    POST   /admin/rooms/{room_id}/start-questioning Convenience endpoint: INTRO -> QUESTIONING
    GET    /admin/rooms/{room_id}/history     Get room state transition audit log

    POST   /admin/questions                   Create a new question
    GET    /admin/questions                   List questions
    GET    /admin/questions/{question_id}     Get question by ID
    PATCH  /admin/questions/{question_id}     Update question text, target_gender, or active
    DELETE /admin/questions/{question_id}     Delete a question
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import PlayerRole, RoomState
from app.exceptions import (
    InvalidRoomTransitionError,
    QuestionNotFoundError,
    RoomNotFoundError,
)
from app.models.room import Room
from app.models.user import User
from app.schemas.question import QuestionCreate, QuestionRead, QuestionUpdate
from app.schemas.room import (
    AudienceParticipantInfo,
    ChallengerInfo,
    RoomAdminDetail,
    RoomAdminSummary,
    RoomStateHistoryRead,
    RoomTransitionRequest,
)
from app.services.question_service import question_service
from app.services.room_state_service import room_state_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _build_room_admin_detail(db: Session, room: Room) -> RoomAdminDetail:
    """Helper to assemble a RoomAdminDetail schema from a Room model."""
    challenger_info: ChallengerInfo | None = None
    if room.challenger_id is not None:
        user = db.get(User, room.challenger_id)
        if user:
            challenger_info = ChallengerInfo(
                id=user.id,
                name=user.name,
                gender=user.gender,
            )

    active_participants = [p for p in room.participants if p.left_at is None]
    audience: list[AudienceParticipantInfo] = []
    for p in active_participants:
        if p.role == PlayerRole.AUDIENCE:
            user = db.get(User, p.user_id)
            if user:
                audience.append(
                    AudienceParticipantInfo(
                        id=user.id,
                        name=user.name,
                        state=user.state.value if hasattr(user.state, "value") else str(user.state),
                    )
                )

    votes_submitted: int | None = None
    votes_remaining: int | None = None
    if room.state == RoomState.VOTING:
        from app.models.vote import Vote
        from sqlalchemy import func
        votes_count = db.execute(
            select(func.count(Vote.id)).where(
                Vote.room_id == room.id,
                Vote.round == room.current_round,
            )
        ).scalar_one()
        votes_submitted = votes_count
        votes_remaining = max(0, len(audience) - votes_count)

    return RoomAdminDetail(
        id=room.id,
        state=room.state,
        challenger=challenger_info,
        audience=audience,
        audience_count=len(audience),
        current_round=room.current_round,
        votes_submitted=votes_submitted,
        votes_remaining=votes_remaining,
    )


# ---------------------------------------------------------------------------
# Room administration endpoints
# ---------------------------------------------------------------------------


@router.get("/rooms", response_model=list[RoomAdminSummary])
def list_rooms(db: Session = Depends(get_db)) -> list[RoomAdminSummary]:
    """List all active (non-completed) rooms with key details."""
    logger.debug("Admin listing all active rooms")
    rooms = list(
        db.execute(
            select(Room).where(Room.state != RoomState.COMPLETED).order_by(Room.id)
        ).scalars()
    )

    summaries: list[RoomAdminSummary] = []
    for room in rooms:
        challenger_info: ChallengerInfo | None = None
        if room.challenger_id is not None:
            user = db.get(User, room.challenger_id)
            if user:
                challenger_info = ChallengerInfo(
                    id=user.id,
                    name=user.name,
                    gender=user.gender,
                )

        active_participants = [p for p in room.participants if p.left_at is None]
        audience_count = sum(
            1 for p in active_participants if p.role == PlayerRole.AUDIENCE
        )

        summaries.append(
            RoomAdminSummary(
                id=room.id,
                state=room.state,
                challenger=challenger_info,
                audience_count=audience_count,
                created_at=room.created_at,
            )
        )

    return summaries


@router.get("/rooms/{room_id}", response_model=RoomAdminDetail)
def get_room_admin(room_id: int, db: Session = Depends(get_db)) -> RoomAdminDetail:
    """Retrieve comprehensive room details for admin inspection."""
    logger.debug("Admin inspecting room_id=%d", room_id)
    room = db.get(Room, room_id)
    if room is None:
        logger.warning("Admin inspect failed: Room %d not found", room_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    return _build_room_admin_detail(db, room)


@router.post("/rooms/{room_id}/transition", response_model=RoomAdminDetail)
async def transition_room(
    room_id: int,
    payload: RoomTransitionRequest,
    db: Session = Depends(get_db),
) -> RoomAdminDetail:
    """Transition a room to the requested state."""
    logger.info("Admin requesting transition for room %d to state %s", room_id, payload.state.value)
    try:
        room = await room_state_service.transition(db, room_id, payload.state)
        logger.info("Admin transition successful for room %d: state is now %s", room.id, room.state.value)
        return _build_room_admin_detail(db, room)
    except RoomNotFoundError as exc:
        logger.warning("Admin transition failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRoomTransitionError as exc:
        logger.warning("Admin transition invalid: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)


@router.post("/rooms/{room_id}/start", response_model=RoomAdminDetail)
async def start_room(
    room_id: int,
    db: Session = Depends(get_db),
) -> RoomAdminDetail:
    """Convenience endpoint to start a room (READY -> INTRO)."""
    logger.info("Admin start room requested: room_id=%d", room_id)
    try:
        room = await room_state_service.transition(db, room_id, RoomState.INTRO)
        logger.info("Room %d started successfully (state=INTRO)", room.id)
        return _build_room_admin_detail(db, room)
    except RoomNotFoundError as exc:
        logger.warning("Admin start room failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRoomTransitionError as exc:
        logger.warning("Admin start room invalid transition: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)


@router.post("/rooms/{room_id}/start-questioning", response_model=RoomAdminDetail)
async def start_questioning(
    room_id: int,
    db: Session = Depends(get_db),
) -> RoomAdminDetail:
    """Convenience endpoint to move room into questioning (INTRO -> QUESTIONING)."""
    logger.info("Admin start questioning requested: room_id=%d", room_id)
    try:
        room = await room_state_service.transition(db, room_id, RoomState.QUESTIONING)
        logger.info("Room %d moved to questioning successfully (round=%d)", room.id, room.current_round)
        return _build_room_admin_detail(db, room)
    except RoomNotFoundError as exc:
        logger.warning("Admin start questioning failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidRoomTransitionError as exc:
        logger.warning("Admin start questioning invalid transition: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)


@router.get("/rooms/{room_id}/history", response_model=list[RoomStateHistoryRead])
def get_room_history(
    room_id: int,
    db: Session = Depends(get_db),
) -> list[RoomStateHistoryRead]:
    """Retrieve the state transition history audit log for a room."""
    logger.debug("Admin history requested: room_id=%d", room_id)
    room = db.get(Room, room_id)
    if room is None:
        logger.warning("Admin get room history failed: Room %d not found", room_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room {room_id} not found.",
        )
    history_entries = room_state_service.get_history(db, room_id)
    return [RoomStateHistoryRead.model_validate(h) for h in history_entries]


# ---------------------------------------------------------------------------
# Question CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/questions", response_model=QuestionRead, status_code=status.HTTP_201_CREATED)
def create_question(
    payload: QuestionCreate, db: Session = Depends(get_db)
) -> QuestionRead:
    """Create a new question in the question pool."""
    logger.info("Admin creating question: target=%s, text='%s'", payload.target_gender, payload.text)
    question = question_service.create_question(db, payload)
    return QuestionRead.model_validate(question)


@router.get("/questions", response_model=list[QuestionRead])
def list_questions(
    active: bool | None = None, db: Session = Depends(get_db)
) -> list[QuestionRead]:
    """List questions in the question pool with optional active status filter."""
    logger.debug("Admin listing questions (active=%s)", active)
    questions = question_service.list_questions(db, active=active)
    return [QuestionRead.model_validate(q) for q in questions]


@router.get("/questions/{question_id}", response_model=QuestionRead)
def get_question(
    question_id: int, db: Session = Depends(get_db)
) -> QuestionRead:
    """Retrieve a specific question by ID."""
    logger.debug("Admin get question: question_id=%d", question_id)
    try:
        question = question_service.get_question(db, question_id)
        return QuestionRead.model_validate(question)
    except QuestionNotFoundError as exc:
        logger.warning("Get question %d failed: %s", question_id, exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/questions/{question_id}", response_model=QuestionRead)
def update_question(
    question_id: int,
    payload: QuestionUpdate,
    db: Session = Depends(get_db),
) -> QuestionRead:
    """Update question text, target_gender, or active status."""
    logger.info("Admin updating question %d", question_id)
    try:
        question = question_service.update_question(db, question_id, payload)
        return QuestionRead.model_validate(question)
    except QuestionNotFoundError as exc:
        logger.warning("Update question %d failed: %s", question_id, exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    question_id: int, db: Session = Depends(get_db)
) -> None:
    """Delete a question from the pool."""
    logger.info("Admin deleting question %d", question_id)
    try:
        question_service.delete_question(db, question_id)
    except QuestionNotFoundError as exc:
        logger.warning("Delete question %d failed: %s", question_id, exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

