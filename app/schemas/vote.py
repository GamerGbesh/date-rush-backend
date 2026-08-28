from datetime import datetime

from pydantic import BaseModel

from app.enums import RoomState, VoteChoice


class VoteSubmitRequest(BaseModel):
    user_id: int
    vote: VoteChoice


class VoteRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    room_id: int
    round: int
    voter_id: int
    target_id: int
    vote: VoteChoice
    created_at: datetime


class VotingStatusResponse(BaseModel):
    state: RoomState
    total_voters: int
    votes_submitted: int
    votes_remaining: int
    has_voted: bool | None = None
