from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import OneOnOneSessionState, VoteChoice


class OneOnOneSession(Base):
    __tablename__ = "one_on_one_sessions"

    __table_args__ = (
        UniqueConstraint("room_id", "sequence", name="uq_one_on_one_room_sequence"),
        UniqueConstraint("room_id", "audience_id", name="uq_one_on_one_room_audience"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    audience_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    challenger_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[OneOnOneSessionState] = mapped_column(
        Enum(OneOnOneSessionState),
        nullable=False,
        default=OneOnOneSessionState.PENDING,
    )

    question: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answer: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    vote: Mapped[VoteChoice | None] = mapped_column(Enum(VoteChoice), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    room = relationship("Room", back_populates="one_on_one_sessions")
    audience = relationship("User", foreign_keys=[audience_id])
    challenger = relationship("User", foreign_keys=[challenger_id])
