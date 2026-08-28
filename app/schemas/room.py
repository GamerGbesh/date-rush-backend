from datetime import datetime

from pydantic import BaseModel

from app.enums import Gender, PlayerRole, RoomState


class RoomRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    state: RoomState
    challenger_id: int | None
    challenger_gender: Gender | None
    current_question_id: int | None
    current_round: int
    created_at: datetime


class RoomParticipantRead(BaseModel):
    model_config = {"from_attributes": True}

    room_id: int
    user_id: int
    role: PlayerRole
    joined_at: datetime
    left_at: datetime | None


class ParticipantDetail(BaseModel):
    """Participant info enriched with the user's name and gender."""

    user_id: int
    name: str
    gender: Gender
    role: PlayerRole
    joined_at: datetime
    left_at: datetime | None = None


class RoomDetail(BaseModel):
    """Room with its currently active participants (left_at is null)."""

    room: RoomRead
    participants: list[ParticipantDetail]


class ChallengerInfo(BaseModel):
    """Minimal challenger info for the admin room listing."""

    id: int
    name: str
    gender: Gender


class AudienceParticipantInfo(BaseModel):
    """Audience member summary for admin room inspection."""

    id: int
    name: str
    state: str


class RoomAdminSummary(BaseModel):
    """Compact room summary for the admin endpoint."""

    id: int
    state: RoomState
    challenger: ChallengerInfo | None
    audience_count: int
    created_at: datetime


class RoomAdminDetail(BaseModel):
    """Comprehensive room detail for admin inspection."""

    id: int
    state: RoomState
    challenger: ChallengerInfo | None
    audience: list[AudienceParticipantInfo]
    audience_count: int
    current_round: int
    votes_submitted: int | None = None
    votes_remaining: int | None = None



class RoomTransitionRequest(BaseModel):
    """Request payload to manually transition room state."""

    state: RoomState


class RoomStateHistoryRead(BaseModel):
    """Audit log entry for room state transitions."""

    model_config = {"from_attributes": True}

    id: int
    room_id: int
    from_state: RoomState
    to_state: RoomState
    created_at: datetime

