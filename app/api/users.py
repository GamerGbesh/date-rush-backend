from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.match import Match
from app.models.room import RoomParticipant
from app.models.user import User
from app.schemas.user import UserCreate, UserProfileResponse, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    """
    Register a new user.
    The user starts in WAITING state.
    """
    user = User(name=payload.name, gender=payload.gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(
    user_id: int = Query(..., description="Authenticated user ID"),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    """
    Retrieve the current user's profile and event/game state.
    Used by frontend on app load, refresh, or reconnect to derive screen state.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found."
        )

    # Check active room participation
    room_id: int | None = None
    role: str | None = None
    participant = db.execute(
        select(RoomParticipant)
        .where(
            RoomParticipant.user_id == user.id,
            RoomParticipant.left_at.is_(None),
        )
        .order_by(RoomParticipant.joined_at.desc())
    ).scalars().first()

    if participant:
        room_id = participant.room_id
        role = participant.role.value

    # Check match & match room
    match_id: int | None = None
    match_room_id: int | None = None
    match = db.execute(
        select(Match).where(
            or_(Match.challenger_id == user.id, Match.audience_id == user.id)
        ).order_by(Match.id.desc())
    ).scalars().first()

    if match:
        match_id = match.id
        if match.match_room:
            match_room_id = match.match_room.id

    return UserProfileResponse(
        id=user.id,
        name=user.name,
        gender=user.gender,
        state=user.state,
        queued_at=user.queued_at,
        room_id=room_id,
        role=role,
        match_id=match_id,
        match_room_id=match_room_id,
    )


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)) -> UserRead:
    """Retrieve public user profile by ID."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found."
        )
    return UserRead.model_validate(user)

