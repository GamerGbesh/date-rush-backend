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
