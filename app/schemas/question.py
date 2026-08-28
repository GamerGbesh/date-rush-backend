from datetime import datetime

from pydantic import BaseModel

from app.enums import QuestionTarget


class QuestionCreate(BaseModel):
    text: str
    target_gender: QuestionTarget = QuestionTarget.ANY
    active: bool = True


class QuestionUpdate(BaseModel):
    text: str | None = None
    target_gender: QuestionTarget | None = None
    active: bool | None = None


class QuestionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    text: str
    target_gender: QuestionTarget
    active: bool
    created_at: datetime
    updated_at: datetime | None = None

