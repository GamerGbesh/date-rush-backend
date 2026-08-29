from datetime import datetime

from pydantic import BaseModel, Field

from app.enums import OneOnOneSessionState, VoteChoice


class PrivateQuestionSubmitRequest(BaseModel):
    user_id: int
    text: str = Field(..., min_length=1, max_length=500)


class PrivateAnswerSubmitRequest(BaseModel):
    user_id: int
    text: str = Field(..., min_length=1, max_length=1000)


class PrivateVoteSubmitRequest(BaseModel):
    user_id: int
    vote: VoteChoice


class OneOnOneSessionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    audience_id: int
    challenger_id: int
    sequence: int
    state: OneOnOneSessionState
    question: str | None = None
    answer: str | None = None
    vote: VoteChoice | None = None
    started_at: datetime | None = None
    answered_at: datetime | None = None
    voted_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class OneOnOneSessionPublicSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    audience_id: int | None = None
    challenger_id: int | None = None
    sequence: int
    state: OneOnOneSessionState


class OneOnOneRoomStatusResponse(BaseModel):
    room_id: int
    total_sessions: int
    completed_sessions: int
    active_session: OneOnOneSessionRead | None = None
