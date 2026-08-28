from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import RoomState


class RoomStateHistory(Base):
    __tablename__ = "room_state_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"), nullable=False, index=True
    )
    from_state: Mapped[RoomState] = mapped_column(
        Enum(RoomState), nullable=False
    )
    to_state: Mapped[RoomState] = mapped_column(
        Enum(RoomState), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    room: Mapped["Room"] = relationship("Room", back_populates="history")
