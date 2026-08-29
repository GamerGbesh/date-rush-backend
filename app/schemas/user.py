from datetime import datetime

from pydantic import BaseModel

from app.enums import Gender, UserState


class UserCreate(BaseModel):
    name: str
    gender: Gender


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    gender: Gender
    state: UserState
    created_at: datetime
    queued_at: datetime | None = None


class UserProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    gender: Gender
    state: UserState
    queued_at: datetime | None = None
    room_id: int | None = None
    role: str | None = None
    match_id: int | None = None
    match_room_id: int | None = None

