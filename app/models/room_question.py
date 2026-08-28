from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import QuestionPhase


class RoomQuestion(Base):
    __tablename__ = "room_questions"
    __table_args__ = (
        UniqueConstraint("room_id", "position", name="uq_room_question_position"),
        UniqueConstraint("room_id", "question_id", name="uq_room_question_unique"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[QuestionPhase] = mapped_column(
        Enum(QuestionPhase), nullable=False, default=QuestionPhase.PUBLIC
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    room: Mapped["Room"] = relationship("Room", back_populates="room_questions")
    question: Mapped["Question"] = relationship("Question")
