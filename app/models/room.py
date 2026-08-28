from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import Gender, ParticipantStatus, PlayerRole, RoomState


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    state: Mapped[RoomState] = mapped_column(
        Enum(RoomState), nullable=False, default=RoomState.WAITING
    )

    # The challenger is nullable until the room is properly initialized.
    challenger_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    challenger_gender: Mapped[Gender | None] = mapped_column(
        Enum(Gender), nullable=True
    )

    # Tracks progress through the question list.
    current_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True
    )
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships (lazy-loaded by default)
    participants: Mapped[list["RoomParticipant"]] = relationship(
        "RoomParticipant", back_populates="room", lazy="select"
    )
    history: Mapped[list["RoomStateHistory"]] = relationship(
        "RoomStateHistory", back_populates="room", lazy="select", order_by="RoomStateHistory.id"
    )
    room_questions: Mapped[list["RoomQuestion"]] = relationship(
        "RoomQuestion", back_populates="room", lazy="select", order_by="RoomQuestion.position"
    )
    current_question: Mapped["Question | None"] = relationship(
        "Question", foreign_keys=[current_question_id], lazy="select"
    )


class RoomParticipant(Base):
    __tablename__ = "room_participants"

    # Composite primary key — a user can only appear once per room.
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )

    role: Mapped[PlayerRole] = mapped_column(Enum(PlayerRole), nullable=False)
    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(ParticipantStatus), nullable=False, default=ParticipantStatus.ACTIVE
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # left_at is null while the participant is still active in the room.
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    room: Mapped["Room"] = relationship("Room", back_populates="participants")
