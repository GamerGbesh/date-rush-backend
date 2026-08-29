from datetime import datetime

from pydantic import BaseModel


class AnswerSubmitRequest(BaseModel):
    user_id: int
    answer: str


class AnswerRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    question_id: int
    user_id: int
    answer: str
    created_at: datetime


class RoomAnswerItem(BaseModel):
    round: int
    question: str
    question_id: int | None = None
    answer: str

