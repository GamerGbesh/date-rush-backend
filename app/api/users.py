from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    """
    Register a new user.

    The user starts in WAITING state.  To enter the matchmaking queue,
    a subsequent call to the queue endpoint will be needed (not yet implemented).
    """
    user = User(name=payload.name, gender=payload.gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)
