from datetime import datetime

from pydantic import BaseModel

from app.enums import Gender, MatchStatus, RoomState


class FinalCandidateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    gender: Gender


class FinalSelectionRequest(BaseModel):
    user_id: int
    candidate_id: int


class FinalSelectionStatusResponse(BaseModel):
    state: RoomState
    is_challenger: bool
    candidates: list[FinalCandidateRead] | None = None
    selected: bool = False
    match_id: int | None = None


class PartnerInfo(BaseModel):
    id: int
    name: str
    gender: Gender


class MatchRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    challenger_id: int
    audience_id: int
    status: MatchStatus
    created_at: datetime


class MatchDetailResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    status: MatchStatus
    created_at: datetime
    partner: PartnerInfo
    match_room_id: int | None = None

