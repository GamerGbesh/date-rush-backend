"""
RoomManager — room lifecycle and participant management.

All room state transitions and participant management lives here, keeping
API route handlers free of business logic.
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import Gender, PlayerRole, QuestionPhase, RoomState, UserState
from app.models.room import Room, RoomParticipant
from app.models.room_question import RoomQuestion
from app.models.user import User
from app.services.question_service import question_service

logger = logging.getLogger(__name__)


class RoomManager:
    """Manages room lifecycle and participant membership."""

    def create_room(self, db: Session, challenger_gender: Gender) -> Room:
        """Create and persist a new room in WAITING state (scaffold / test helper)."""
        room = Room(
            state=RoomState.WAITING,
            challenger_gender=challenger_gender,
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    def create_room_with_participants(
        self,
        db: Session,
        challenger: User,
        audience: list[User],
    ) -> Room:
        """
        Atomically create a fully-formed game room.

        In a single transaction:
          1. Select questions for the room based on challenger gender.
          2. Transition challenger and all audience members QUEUED → IN_GAME.
          3. Clear their queued_at timestamps.
          4. Create the Room record (state=READY).
          5. Create all RoomParticipant records.
          6. Create all RoomQuestion records for the selected questions.
          7. Commit — or roll back on any failure, leaving users in QUEUED.

        Returns the newly created and refreshed Room.
        """
        # 1. Select questions upfront before modifying user states.
        questions = question_service.select_questions_for_room(
            db, challenger.gender, settings.PUBLIC_QUESTION_ROUNDS
        )

        try:
            # -- State transitions ----------------------------------------
            challenger.state = UserState.IN_GAME
            challenger.queued_at = None
            for user in audience:
                user.state = UserState.IN_GAME
                user.queued_at = None

            # -- Room record -------------------------------------------------
            room = Room(
                state=RoomState.READY,
                challenger_id=challenger.id,
                challenger_gender=challenger.gender,
                current_round=0,
            )
            db.add(room)
            db.flush()  # Populate room.id without committing yet.

            # -- Participant records -----------------------------------------
            db.add(
                RoomParticipant(
                    room_id=room.id,
                    user_id=challenger.id,
                    role=PlayerRole.CHALLENGER,
                )
            )
            for user in audience:
                db.add(
                    RoomParticipant(
                        room_id=room.id,
                        user_id=user.id,
                        role=PlayerRole.AUDIENCE,
                    )
                )

            # -- Room Questions sequence -------------------------------------
            for idx, q in enumerate(questions, start=1):
                db.add(
                    RoomQuestion(
                        room_id=room.id,
                        question_id=q.id,
                        position=idx,
                        phase=QuestionPhase.PUBLIC,
                    )
                )

            db.commit()
            db.refresh(room)
            logger.info(
                "Created room %d  challenger=%d  audience=%s  questions=%s",
                room.id,
                challenger.id,
                [u.id for u in audience],
                [q.id for q in questions],
            )
            return room

        except Exception:
            db.rollback()
            logger.exception("Room creation failed — rolled back.")
            raise

    def get_room(self, db: Session, room_id: int) -> Room:
        """Fetch a room by ID, raising 404 if not found."""
        room = db.get(Room, room_id)
        if room is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Room {room_id} not found.",
            )
        return room

    def add_participant(
        self, db: Session, room: Room, user: User, role: PlayerRole
    ) -> RoomParticipant:
        """
        Add a user to a room with the given role and set the user's state to
        IN_GAME.  Raises an error if the user is already an active participant.
        """
        participant = RoomParticipant(
            room_id=room.id,
            user_id=user.id,
            role=role,
        )
        db.add(participant)
        user.state = UserState.IN_GAME
        db.commit()
        db.refresh(participant)
        db.refresh(user)
        return participant

    def remove_participant(
        self, db: Session, room: Room, user: User
    ) -> RoomParticipant:
        """
        Mark a participant as having left the room (set left_at) and return
        the user to the QUEUED state.
        """
        participant = db.get(RoomParticipant, (room.id, user.id))
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user.id} is not a participant in room {room.id}.",
            )
        participant.left_at = datetime.now(timezone.utc)
        user.state = UserState.QUEUED
        db.commit()
        db.refresh(participant)
        db.refresh(user)
        return participant

    def set_state(self, db: Session, room: Room, new_state: RoomState) -> Room:
        """Transition a room to a new state."""
        room.state = new_state
        db.commit()
        db.refresh(room)
        return room

    def get_active_participants(
        self, db: Session, room: Room
    ) -> list[RoomParticipant]:
        """Return participants who are still active in the room (left_at is null)."""
        return [p for p in room.participants if p.left_at is None]


room_manager = RoomManager()
