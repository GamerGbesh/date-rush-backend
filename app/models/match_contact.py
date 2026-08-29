from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MatchContact(Base):
    __tablename__ = "match_contacts"

    __table_args__ = (
        UniqueConstraint("match_room_id", "user_id", name="uq_match_room_user_contact"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    match_room_id: Mapped[int] = mapped_column(
        ForeignKey("match_rooms.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    whatsapp: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    snapchat: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    match_room = relationship("MatchRoom", back_populates="contacts")
    user = relationship("User")
