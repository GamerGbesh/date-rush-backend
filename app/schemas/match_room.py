from datetime import datetime

from pydantic import BaseModel

from app.enums import MatchRoomState


class ContactSubmitRequest(BaseModel):
    user_id: int
    whatsapp: str | None = None
    snapchat: str | None = None


class PartnerContactRead(BaseModel):
    name: str
    whatsapp: str | None = None
    snapchat: str | None = None


class MatchRoomContactsResponse(BaseModel):
    state: MatchRoomState
    submitted: bool
    partner: PartnerContactRead | None = None


class MatchRoomRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    match_id: int
    state: MatchRoomState
    created_at: datetime
    completed_at: datetime | None = None


class MatchRoomDetailResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    match_id: int
    state: MatchRoomState
    my_contact_submitted: bool
    partner_contact_available: bool
    created_at: datetime
    completed_at: datetime | None = None

