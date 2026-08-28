from pydantic import BaseModel

from app.enums import Gender, UserState


class QueueJoinRequest(BaseModel):
    name: str
    gender: Gender


class QueueJoinResponse(BaseModel):
    user_id: int
    state: UserState
    room_id: int | None = None


class QueueStatusResponse(BaseModel):
    male: int
    female: int
