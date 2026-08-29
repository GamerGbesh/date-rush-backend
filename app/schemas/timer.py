"""
Pydantic schemas for room countdown timer queries and synchronization.
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TimerStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: int
    active: bool
    timer_type: str | None = None
    duration_seconds: float | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    remaining_seconds: float | None = None
    session_id: int | None = None
    round: int | None = None
