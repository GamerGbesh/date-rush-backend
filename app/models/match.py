from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import MatchStatus


class Match(Base):
    __tablename__ = "matches"

    __table_args__ = (
        UniqueConstraint("room_id", name="uq_match_room_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, unique=True, index=True)
    challenger_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    audience_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus),
        nullable=False,
        default=MatchStatus.CREATED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    room = relationship("Room")
    challenger = relationship("User", foreign_keys=[challenger_id])
    audience = relationship("User", foreign_keys=[audience_id])
    match_room = relationship("MatchRoom", back_populates="match", uselist=False, cascade="all, delete-orphan")
