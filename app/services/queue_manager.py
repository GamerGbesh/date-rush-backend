"""
QueueManager — database-backed, FIFO-ordered gender queues.

The male and female queues are derived by querying users with state=QUEUED,
ordered by queued_at ASC (FIFO). No separate queue table exists.

Concurrency
-----------
try_create_rooms() is serialised with a module-level threading.Lock so that
two simultaneous HTTP requests cannot consume the same queued users twice.
This is the appropriate strategy for a single-process application.
"""

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import Gender, UserState
from app.models.user import User

logger = logging.getLogger(__name__)

# Serialises room-creation across concurrent FastAPI threadpool workers.
_room_creation_lock = threading.Lock()


class QueueManager:
    """Manages the two gender queues backed by the users table."""

    # ------------------------------------------------------------------
    # Public queue operations
    # ------------------------------------------------------------------

    def add(self, db: Session, user: User) -> None:
        """Place a user into their gender queue (state → QUEUED, queued_at set)."""
        user.state = UserState.QUEUED
        user.queued_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)

    def remove(self, db: Session, user: User) -> None:
        """Remove a user from the queue and return them to WAITING."""
        user.state = UserState.WAITING
        user.queued_at = None
        db.commit()
        db.refresh(user)

    def get_size(self, db: Session, gender: Gender) -> int:
        """Return the number of users currently queued for a given gender."""
        result = db.execute(
            select(func.count(User.id)).where(
                User.gender == gender,
                User.state == UserState.QUEUED,
            )
        )
        return result.scalar_one()

    def get_users(self, db: Session, gender: Gender) -> list[User]:
        """Return all queued users for a given gender, FIFO order."""
        result = db.execute(
            select(User)
            .where(User.gender == gender, User.state == UserState.QUEUED)
            .order_by(User.queued_at, User.id)
        )
        return list(result.scalars().all())

    def pop_many(self, db: Session, gender: Gender, count: int) -> list[User]:
        """
        Remove up to *count* users (FIFO) from the queue and mark them IN_GAME.

        Note: the caller is responsible for creating RoomParticipant records.
        In production the room-creation path goes through try_create_rooms(),
        not this method directly.
        """
        users = self.get_users(db, gender)[:count]
        for user in users:
            user.state = UserState.IN_GAME
            user.queued_at = None
        db.commit()
        for user in users:
            db.refresh(user)
        return users

    # ------------------------------------------------------------------
    # Room-creation logic
    # ------------------------------------------------------------------

    def try_create_rooms(self, db: Session) -> list:
        """
        Attempt to create as many valid game rooms as the current queue state
        allows.  Returns the list of Room objects created (may be empty).

        Algorithm
        ---------
        Repeat until no more complete rooms can be formed:

            if male_queue >= threshold and female_queue >= 1:
                create room (female challenger, male audience)

            elif female_queue >= threshold and male_queue >= 1:
                create room (male challenger, female audience)

            else:
                stop

        The threading.Lock ensures two concurrent requests cannot consume
        the same queued users.  Each room is committed atomically before
        the next iteration re-evaluates queue sizes.
        """
        from app.exceptions import InsufficientQuestionsError
        from app.services.room_manager import room_manager

        threshold = settings.GAME_ROOM_THRESHOLD
        created: list = []

        with _room_creation_lock:
            while True:
                male_count = self.get_size(db, Gender.MALE)
                female_count = self.get_size(db, Gender.FEMALE)

                logger.debug(
                    "try_create_rooms: male=%d female=%d threshold=%d",
                    male_count, female_count, threshold,
                )

                try:
                    if male_count >= threshold and female_count >= 1:
                        audience = self._select_for_room(db, Gender.MALE, threshold)
                        challenger = self._select_for_room(db, Gender.FEMALE, 1)[0]
                        room = room_manager.create_room_with_participants(
                            db, challenger, audience
                        )
                        created.append(room)
                        logger.info(
                            "Room %d created: female challenger %d, %d male audience",
                            room.id, challenger.id, len(audience),
                        )
                        continue

                    if female_count >= threshold and male_count >= 1:
                        audience = self._select_for_room(db, Gender.FEMALE, threshold)
                        challenger = self._select_for_room(db, Gender.MALE, 1)[0]
                        room = room_manager.create_room_with_participants(
                            db, challenger, audience
                        )
                        created.append(room)
                        logger.info(
                            "Room %d created: male challenger %d, %d female audience",
                            room.id, challenger.id, len(audience),
                        )
                        continue
                except InsufficientQuestionsError as exc:
                    logger.warning("Room creation stopped: %s", exc)
                    break

                break  # no complete room possible

        return created

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_for_room(self, db: Session, gender: Gender, count: int) -> list[User]:
        """
        Read-only: return the first *count* FIFO-ordered queued users of a gender.

        Does NOT change any state.  State transitions happen inside
        room_manager.create_room_with_participants().
        """
        result = db.execute(
            select(User)
            .where(User.gender == gender, User.state == UserState.QUEUED)
            .order_by(User.queued_at, User.id)
            .limit(count)
        )
        return list(result.scalars().all())


queue_manager = QueueManager()
