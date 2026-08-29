"""
VotingService — manages public YES/NO voting, mandatory voting tracking,
vote finalization, NO-voter elimination, returning eliminated users to queues,
and automatic progression to ONE_ON_ONE, FINAL, or COMPLETED.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import (
    ParticipantStatus,
    PlayerRole,
    RoomState,
    UserState,
    VoteChoice,
)
from app.exceptions import (
    DuplicateVoteError,
    InvalidVoterError,
    InvalidVotingStateError,
    RoomNotFoundError,
)
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.models.vote import Vote
from app.schemas.vote import VotingStatusResponse
from app.services.room_state_service import room_state_service
from app.services.websocket_manager import ws_manager

from app.services.timer_service import timer_service

logger = logging.getLogger(__name__)

# Lock to prevent race conditions during vote finalization across async tasks / threads
_finalization_locks: dict[int, asyncio.Lock] = {}


def _get_room_lock(room_id: int) -> asyncio.Lock:
    if room_id not in _finalization_locks:
        _finalization_locks[room_id] = asyncio.Lock()
    return _finalization_locks[room_id]


class VotingService:
    """Manages public voting lifecycle and elimination processing."""

    def start_voting_timer(
        self,
        room_id: int,
        round_number: int,
        duration_seconds: float | None = None,
    ) -> None:
        """Start a background countdown timer via timer_service to auto-finalize voting."""
        duration = duration_seconds if duration_seconds is not None else float(settings.VOTING_TIMEOUT_SECONDS)

        async def _on_timeout():
            from app.database import SessionLocal
            with SessionLocal() as db:
                room = db.get(Room, room_id)
                if room and room.state == RoomState.VOTING and room.current_round == round_number:
                    logger.info(
                        "Voting timer expired for room %d (round=%d). Finalizing voting automatically.",
                        room_id,
                        round_number,
                    )
                    await self.finalize_voting(db, room_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="voting",
            duration_seconds=duration,
            on_timeout=_on_timeout,
            round=round_number,
        )

    def cancel_voting_timer(self, room_id: int) -> None:
        """Cancel any pending voting timer for this room."""
        timer_service.cancel_timer(room_id, "voting")

    def get_voting_status(
        self, db: Session, room_id: int, user_id: int | None = None
    ) -> VotingStatusResponse:
        """Get aggregate voting progress and optionally check if user_id has voted."""
        room = db.get(Room, room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        active_participants = [
            p
            for p in room.participants
            if p.left_at is None and p.role == PlayerRole.AUDIENCE
        ]
        total_voters = len(active_participants)

        votes_submitted = db.execute(
            select(func.count(Vote.id)).where(
                Vote.room_id == room.id,
                Vote.round == room.current_round,
            )
        ).scalar_one()

        has_voted: bool | None = None
        if user_id is not None:
            user_vote = db.execute(
                select(Vote).where(
                    Vote.room_id == room.id,
                    Vote.round == room.current_round,
                    Vote.voter_id == user_id,
                )
            ).scalar_one_or_none()
            has_voted = user_vote is not None

        votes_remaining = max(0, total_voters - votes_submitted)

        return VotingStatusResponse(
            state=room.state,
            total_voters=total_voters,
            votes_submitted=votes_submitted,
            votes_remaining=votes_remaining,
            has_voted=has_voted,
        )

    async def submit_vote(
        self,
        db: Session,
        room_id: int,
        voter_id: int,
        vote_choice: VoteChoice,
    ) -> Vote:
        """
        Record a public YES/NO vote from an active audience participant.

        Validates voter eligibility, enforces room state and duplicate constraints,
        broadcasts vote_progress, and automatically finalizes voting when all votes
        have been submitted.
        """
        room = db.get(Room, room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        # 1. Verify room is in VOTING state
        if room.state != RoomState.VOTING:
            raise InvalidVotingStateError(room_id=room.id, current_state=room.state.value)

        # 2. Verify voter is NOT the challenger
        if voter_id == room.challenger_id:
            raise InvalidVoterError(
                room_id=room.id, user_id=voter_id, reason="Challenger cannot submit an audience vote."
            )

        # 3. Verify voter is an active AUDIENCE participant
        participant = db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room.id,
                RoomParticipant.user_id == voter_id,
                RoomParticipant.left_at.is_(None),
                RoomParticipant.role == PlayerRole.AUDIENCE,
            )
        ).scalar_one_or_none()

        if not participant:
            raise InvalidVoterError(
                room_id=room.id,
                user_id=voter_id,
                reason="User is not an active audience participant in this room.",
            )

        # 4. Check for duplicate vote in this round
        existing_vote = db.execute(
            select(Vote).where(
                Vote.room_id == room.id,
                Vote.round == room.current_round,
                Vote.voter_id == voter_id,
            )
        ).scalar_one_or_none()

        if existing_vote:
            raise DuplicateVoteError(
                room_id=room.id,
                round_number=room.current_round,
                user_id=voter_id,
            )

        # 5. Persist the vote
        vote_record = Vote(
            room_id=room.id,
            round=room.current_round,
            voter_id=voter_id,
            target_id=room.challenger_id,
            vote=vote_choice,
        )
        db.add(vote_record)
        db.commit()
        db.refresh(vote_record)

        logger.info(
            "Vote recorded for room %d (round=%d, voter=%d, choice=%s)",
            room.id,
            room.current_round,
            voter_id,
            vote_choice,
        )

        # 6. Check progress and broadcast
        active_audience = [
            p
            for p in room.participants
            if p.left_at is None and p.role == PlayerRole.AUDIENCE
        ]
        total_voters = len(active_audience)

        votes_submitted = db.execute(
            select(func.count(Vote.id)).where(
                Vote.room_id == room.id,
                Vote.round == room.current_round,
            )
        ).scalar_one()

        await ws_manager.broadcast(
            room.id,
            {
                "type": "vote_progress",
                "room_id": room.id,
                "submitted": votes_submitted,
                "total": total_voters,
            },
        )

        # 7. If all votes are received, finalize automatically
        if votes_submitted >= total_voters:
            await self.finalize_voting(db, room.id)

        return vote_record

    async def finalize_voting(self, db: Session, room_id: int) -> None:
        """
        Finalize voting phase atomically:
        - Broadcast voting_completed
        - Transition room to ELIMINATION
        - Eliminate NO voters and return them to the queue
        - Broadcast participants_eliminated
        - Determine and transition to next state (ONE_ON_ONE, FINAL, or COMPLETED)
        - Trigger QueueManager room creation check
        """
        # Cancel any active countdown timer for this room
        self.cancel_voting_timer(room_id)

        lock = _get_room_lock(room_id)
        async with lock:
            room = db.get(Room, room_id)
            if not room or room.state not in (RoomState.VOTING, RoomState.ELIMINATION):
                return

            # Broadcast voting_completed
            await ws_manager.broadcast(room.id, {"type": "voting_completed", "room_id": room.id})

            # Transition to ELIMINATION
            if room.state == RoomState.VOTING:
                await room_state_service.transition(db, room.id, RoomState.ELIMINATION)

            # Fetch all active audience participants
            active_participants = [
                p
                for p in room.participants
                if p.left_at is None and p.role == PlayerRole.AUDIENCE
            ]

            # Fetch votes submitted for this round
            votes = list(
                db.execute(
                    select(Vote).where(
                        Vote.room_id == room.id,
                        Vote.round == room.current_round,
                    )
                ).scalars()
            )
            vote_map = {v.voter_id: v.vote for v in votes}

            eliminated_users: list[User] = []
            survivors: list[RoomParticipant] = []

            for p in active_participants:
                choice = vote_map.get(p.user_id)
                if choice == VoteChoice.YES:
                    p.status = ParticipantStatus.ACTIVE
                    survivors.append(p)
                else:
                    # Participant voted NO or failed to vote before timeout
                    p.status = ParticipantStatus.ELIMINATED
                    p.left_at = datetime.now(timezone.utc)

                    user = db.get(User, p.user_id)
                    if user:
                        user.state = UserState.WAITING
                        eliminated_users.append(user)

            # If zero survivors remain, also eliminate the challenger
            if len(survivors) == 0 and room.challenger_id is not None:
                p_challenger = next(
                    (
                        p
                        for p in room.participants
                        if p.user_id == room.challenger_id and p.left_at is None
                    ),
                    None,
                )
                if p_challenger:
                    p_challenger.status = ParticipantStatus.ELIMINATED
                    p_challenger.left_at = datetime.now(timezone.utc)
                    challenger_user = db.get(User, p_challenger.user_id)
                    if challenger_user:
                        challenger_user.state = UserState.WAITING
                        eliminated_users.append(challenger_user)

            db.commit()
            db.refresh(room)

            # Notify and disconnect eliminated participants
            for user in eliminated_users:
                await ws_manager.send_to_user(
                    room.id, user.id, {"type": "eliminated", "room_id": room.id}
                )
                ws_manager.disconnect(room.id, user.id)

            logger.info(
                "Elimination completed for room %d: %d eliminated, %d surviving",
                room.id,
                len(eliminated_users),
                len(survivors),
            )

            # Broadcast elimination result to remaining participants
            await ws_manager.broadcast(
                room.id,
                {
                    "type": "participants_eliminated",
                    "room_id": room.id,
                    "remaining_count": len(survivors),
                },
            )

            # Determine next phase
            if len(survivors) >= 1:
                next_state = RoomState.ONE_ON_ONE
            else:
                next_state = RoomState.COMPLETED

            await room_state_service.transition(db, room.id, next_state)


voting_service = VotingService()
