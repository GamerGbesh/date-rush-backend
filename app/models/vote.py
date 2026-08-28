from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import VoteChoice


class Vote(Base):
    __tablename__ = "votes"

    # Enforce one vote per voter per round per room.
    __table_args__ = (
        UniqueConstraint("room_id", "round", "voter_id", name="uq_vote_per_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    voter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vote: Mapped[VoteChoice] = mapped_column(Enum(VoteChoice), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    room = relationship("Room")
    voter = relationship("User", foreign_keys=[voter_id])
    target = relationship("User", foreign_keys=[target_id])
