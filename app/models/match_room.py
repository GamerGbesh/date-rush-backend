from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import MatchRoomState


class MatchRoom(Base):
    __tablename__ = "match_rooms"

    __table_args__ = (
        UniqueConstraint("match_id", name="uq_match_room_match_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), nullable=False, unique=True, index=True
    )
    state: Mapped[MatchRoomState] = mapped_column(
        Enum(MatchRoomState),
        nullable=False,
        default=MatchRoomState.WAITING_FOR_CONTACTS,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Relationships
    match = relationship("Match", back_populates="match_room")
    contacts = relationship("MatchContact", back_populates="match_room", cascade="all, delete-orphan")
