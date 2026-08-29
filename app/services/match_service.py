"""
MatchService — handles candidate eligibility, challenger final selection,
atomic match creation, finalist elimination & queue re-entry, single-survivor shortcuts,
and room completion.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import (
    MatchStatus,
    ParticipantStatus,
    PlayerRole,
    RoomState,
    UserState,
)
from app.exceptions import (
    FinalSelectionUnauthorizedError,
    InvalidFinalSelectionStateError,
    MatchAlreadyExistsError,
    NotEligibleFinalistError,
    RoomNotFoundError,
)
from app.models.match import Match
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.schemas.match import FinalCandidateRead, FinalSelectionStatusResponse
from app.config import settings
from app.services.room_state_service import room_state_service
from app.services.timer_service import timer_service
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

_match_locks: dict[int, asyncio.Lock] = {}


def _get_room_lock(room_id: int) -> asyncio.Lock:
    if room_id not in _match_locks:
        _match_locks[room_id] = asyncio.Lock()
    return _match_locks[room_id]


class MatchService:
    """Service managing final selection and match creation with phase timer."""

    def start_final_selection_timer(
        self, room_id: int, duration_seconds: float | None = None
    ) -> None:
        """Start countdown for challenger to pick a finalist."""
        duration = (
            duration_seconds
            if duration_seconds is not None
            else float(settings.FINAL_SELECTION_TIMEOUT_SECONDS)
        )

        async def _on_timeout():
            await self.handle_final_selection_timeout(room_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="final_selection",
            duration_seconds=duration,
            on_timeout=_on_timeout,
        )

    def cancel_final_selection_timer(self, room_id: int) -> None:
        """Cancel active final selection timer."""
        timer_service.cancel_timer(room_id, "final_selection")

    async def handle_final_selection_timeout(self, room_id: int) -> None:
        """Challenger failed to make final selection in time -> auto-select first finalist."""
        from app.database import SessionLocal
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room or room.state != RoomState.FINAL_SELECTION:
                return

            finalists = self.get_eligible_finalists(db, room.id)
            if not finalists:
                logger.warning("Final selection timeout for room %d but no eligible finalists found", room.id)
                return

            selected_candidate = finalists[0]
            logger.info(
                "Final selection timeout for room %d -> auto-selecting candidate %d (%s)",
                room.id,
                selected_candidate.id,
                selected_candidate.name,
            )
            await self.create_match(
                db=db,
                room_id=room.id,
                challenger_id=room.challenger_id,
                candidate_id=selected_candidate.id,
            )

    def get_eligible_finalists(self, db: Session, room_id: int) -> list[User]:
        """Fetch all active audience participants marked as FINALIST for a room."""
        participants = list(
            db.execute(
                select(RoomParticipant).where(
                    RoomParticipant.room_id == room_id,
                    RoomParticipant.left_at.is_(None),
                    RoomParticipant.role == PlayerRole.AUDIENCE,
                    RoomParticipant.status == ParticipantStatus.FINALIST,
                )
            ).scalars()
        )
        user_ids = [p.user_id for p in participants]
        if not user_ids:
            return []
        users = list(db.execute(select(User).where(User.id.in_(user_ids))).scalars())
        return users

    def get_final_selection_status(
        self, db: Session, room_id: int, user_id: int | None = None
    ) -> FinalSelectionStatusResponse:
        """Get final selection status, providing candidate list only to the challenger."""
        room = db.get(Room, room_id)
        if not room:
            raise RoomNotFoundError(room_id)

        match = db.execute(
            select(Match).where(Match.room_id == room.id)
        ).scalar_one_or_none()

        is_challenger = (user_id == room.challenger_id) if user_id is not None else False
        candidates: list[FinalCandidateRead] | None = None

        if is_challenger:
            finalist_users = self.get_eligible_finalists(db, room.id)
            candidates = [
                FinalCandidateRead(id=u.id, name=u.name, gender=u.gender)
                for u in finalist_users
            ]

        return FinalSelectionStatusResponse(
            state=room.state,
            is_challenger=is_challenger,
            candidates=candidates,
            selected=match is not None,
            match_id=match.id if match else None,
        )

    async def create_match(
        self,
        db: Session,
        room_id: int,
        challenger_id: int,
        candidate_id: int,
    ) -> Match:
        """
        Record challenger final selection atomically:
        - Validate room state and challenger authorization
        - Validate candidate is an active FINALIST
        - Create persistent Match record
        - Mark challenger & candidate as MATCHED (they do not return to queue)
        - Mark non-selected finalists as ELIMINATED and return them to the queue
        - Complete room and trigger QueueManager check
        """
        lock = _get_room_lock(room_id)
        async with lock:
            self.cancel_final_selection_timer(room_id)
            room = db.get(Room, room_id)
            if not room:
                raise RoomNotFoundError(room_id)

            # 1. State validation
            if room.state != RoomState.FINAL_SELECTION:
                raise InvalidFinalSelectionStateError(
                    room_id=room.id, current_state=room.state.value
                )

            # 2. Challenger authorization
            if challenger_id != room.challenger_id:
                raise FinalSelectionUnauthorizedError(
                    room_id=room.id, user_id=challenger_id
                )

            # 3. Candidate validation
            if candidate_id == challenger_id:
                raise NotEligibleFinalistError(
                    room_id=room.id,
                    candidate_id=candidate_id,
                    reason="Challenger cannot select themselves.",
                )

            candidate_p = db.execute(
                select(RoomParticipant).where(
                    RoomParticipant.room_id == room.id,
                    RoomParticipant.user_id == candidate_id,
                    RoomParticipant.left_at.is_(None),
                    RoomParticipant.role == PlayerRole.AUDIENCE,
                    RoomParticipant.status == ParticipantStatus.FINALIST,
                )
            ).scalar_one_or_none()

            if not candidate_p:
                raise NotEligibleFinalistError(
                    room_id=room.id,
                    candidate_id=candidate_id,
                    reason="User is not an active finalist in this room.",
                )

            # 4. Idempotency / duplicate check
            existing_match = db.execute(
                select(Match).where(Match.room_id == room.id)
            ).scalar_one_or_none()

            if existing_match:
                raise MatchAlreadyExistsError(room_id=room.id)

            # 5. Create Match
            now = datetime.now(timezone.utc)
            match = Match(
                room_id=room.id,
                challenger_id=room.challenger_id,
                audience_id=candidate_id,
                status=MatchStatus.CREATED,
                created_at=now,
            )
            db.add(match)

            # 6. Update challenger & candidate
            challenger_user = db.get(User, room.challenger_id)
            if challenger_user:
                challenger_user.state = UserState.MATCHED
            challenger_p = db.get(RoomParticipant, (room.id, room.challenger_id))
            if challenger_p:
                challenger_p.status = ParticipantStatus.SELECTED

            candidate_user = db.get(User, candidate_id)
            if candidate_user:
                candidate_user.state = UserState.MATCHED
            candidate_p.status = ParticipantStatus.SELECTED

            # 7. Eliminate other finalists and return them to the queue
            other_finalists = list(
                db.execute(
                    select(RoomParticipant).where(
                        RoomParticipant.room_id == room.id,
                        RoomParticipant.user_id != candidate_id,
                        RoomParticipant.left_at.is_(None),
                        RoomParticipant.role == PlayerRole.AUDIENCE,
                        RoomParticipant.status == ParticipantStatus.FINALIST,
                    )
                ).scalars()
            )

            eliminated_users: list[User] = []
            for p in other_finalists:
                p.status = ParticipantStatus.ELIMINATED
                p.left_at = now
                u = db.get(User, p.user_id)
                if u:
                    u.state = UserState.WAITING
                    eliminated_users.append(u)

            db.commit()
            db.refresh(match)
            logger.info(
                "Match %d created for room %d (challenger=%d, candidate=%d, eliminated_count=%d)",
                match.id,
                room.id,
                room.challenger_id,
                candidate_id,
                len(eliminated_users),
            )

            # Create private MatchRoom for contact exchange
            from app.services.match_room_service import match_room_service
            match_room = match_room_service.create_match_room(db, match.id)

            # 8. Send private elimination events to non-selected finalists
            for u in eliminated_users:
                await ws_manager.send_to_user(
                    room.id, u.id, {"type": "eliminated", "room_id": room.id}
                )
                ws_manager.disconnect(room.id, u.id)

            # 9. Private match_created event to both matched users
            if challenger_user and candidate_user:
                await ws_manager.send_to_user(
                    room.id,
                    challenger_user.id,
                    {
                        "type": "match_created",
                        "match_id": match.id,
                        "match_room_id": match_room.id,
                        "partner": {
                            "id": candidate_user.id,
                            "name": candidate_user.name,
                        },
                    },
                )
                await ws_manager.send_to_user(
                    room.id,
                    candidate_user.id,
                    {
                        "type": "match_created",
                        "match_id": match.id,
                        "match_room_id": match_room.id,
                        "partner": {
                            "id": challenger_user.id,
                            "name": challenger_user.name,
                        },
                    },
                )

            # 10. Room-wide events & completion
            await ws_manager.broadcast(
                room.id, {"type": "final_selection_completed", "room_id": room.id}
            )

            await room_state_service.transition(db, room.id, RoomState.MATCHED)
            await room_state_service.transition(db, room.id, RoomState.COMPLETED)

            await ws_manager.broadcast(
                room.id, {"type": "room_completed", "room_id": room.id}
            )

            # Trigger queue check for newly re-queued users
            from app.services.queue_manager import queue_manager

            queue_manager.try_create_rooms(db)

            return match

    async def create_match_for_single_survivor(
        self, db: Session, room: Room, survivor_id: int
    ) -> Match:
        """
        Automatic match creation for single survivor shortcut (bypasses FINAL_SELECTION).
        """
        lock = _get_room_lock(room.id)
        async with lock:
            existing_match = db.execute(
                select(Match).where(Match.room_id == room.id)
            ).scalar_one_or_none()
            if existing_match:
                return existing_match

            now = datetime.now(timezone.utc)
            match = Match(
                room_id=room.id,
                challenger_id=room.challenger_id,
                audience_id=survivor_id,
                status=MatchStatus.CREATED,
                created_at=now,
            )
            db.add(match)

            challenger_user = db.get(User, room.challenger_id)
            if challenger_user:
                challenger_user.state = UserState.MATCHED
            challenger_p = db.get(RoomParticipant, (room.id, room.challenger_id))
            if challenger_p:
                challenger_p.status = ParticipantStatus.SELECTED

            survivor_user = db.get(User, survivor_id)
            if survivor_user:
                survivor_user.state = UserState.MATCHED
            survivor_p = db.get(RoomParticipant, (room.id, survivor_id))
            if survivor_p:
                survivor_p.status = ParticipantStatus.SELECTED

            db.commit()
            db.refresh(match)
            logger.info(
                "Single-survivor Match %d created for room %d (challenger=%d, survivor=%d)",
                match.id,
                room.id,
                room.challenger_id,
                survivor_id,
            )

            from app.services.match_room_service import match_room_service
            match_room = match_room_service.create_match_room(db, match.id)

            # Private match_created events
            if challenger_user and survivor_user:
                await ws_manager.send_to_user(
                    room.id,
                    challenger_user.id,
                    {
                        "type": "match_created",
                        "match_id": match.id,
                        "match_room_id": match_room.id,
                        "partner": {
                            "id": survivor_user.id,
                            "name": survivor_user.name,
                        },
                    },
                )
                await ws_manager.send_to_user(
                    room.id,
                    survivor_user.id,
                    {
                        "type": "match_created",
                        "match_id": match.id,
                        "match_room_id": match_room.id,
                        "partner": {
                            "id": challenger_user.id,
                            "name": challenger_user.name,
                        },
                    },
                )

            await room_state_service.transition(db, room.id, RoomState.MATCHED)
            await room_state_service.transition(db, room.id, RoomState.COMPLETED)

            await ws_manager.broadcast(
                room.id, {"type": "room_completed", "room_id": room.id}
            )

            from app.services.queue_manager import queue_manager

            queue_manager.try_create_rooms(db)

            return match


match_service = MatchService()
