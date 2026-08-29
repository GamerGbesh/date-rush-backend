"""
OneOnOneService — manages sequential 1-on-1 private sessions, question asking,
challenger answering, mandatory private voting, elimination, and auto progression.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import (
    OneOnOneSessionState,
    ParticipantStatus,
    PlayerRole,
    RoomState,
    UserState,
    VoteChoice,
)
from app.exceptions import (
    DuplicateSessionAnswerError,
    DuplicateSessionQuestionError,
    DuplicateSessionVoteError,
    InvalidQuestionPayloadError,
    InvalidSessionStateError,
    RoomNotFoundError,
    SessionNotFoundError,
    SessionUnauthorizedError,
)
from app.models.one_on_one_session import OneOnOneSession
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.room_state_service import room_state_service
from app.services.timer_service import timer_service
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Room-level locks to ensure sequential session activations and race-condition safety
_session_locks: dict[int, asyncio.Lock] = {}


def _get_room_lock(room_id: int) -> asyncio.Lock:
    if room_id not in _session_locks:
        _session_locks[room_id] = asyncio.Lock()
    return _session_locks[room_id]


class OneOnOneService:
    """Service handling sequential one-on-one session lifecycle with phase timers."""

    def start_question_timer(
        self, room_id: int, session_id: int, duration_seconds: float | None = None
    ) -> None:
        """Start countdown for audience member to submit private question."""
        duration = (
            duration_seconds
            if duration_seconds is not None
            else float(settings.ONE_ON_ONE_QUESTION_TIMEOUT_SECONDS)
        )

        async def _on_timeout():
            await self.handle_question_timeout(room_id, session_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="one_on_one_question",
            duration_seconds=duration,
            on_timeout=_on_timeout,
            session_id=session_id,
        )

    def start_answer_timer(
        self, room_id: int, session_id: int, duration_seconds: float | None = None
    ) -> None:
        """Start countdown for challenger to answer private question."""
        duration = (
            duration_seconds
            if duration_seconds is not None
            else float(settings.ONE_ON_ONE_ANSWER_TIMEOUT_SECONDS)
        )

        async def _on_timeout():
            await self.handle_answer_timeout(room_id, session_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="one_on_one_answer",
            duration_seconds=duration,
            on_timeout=_on_timeout,
            session_id=session_id,
        )

    def start_vote_timer(
        self, room_id: int, session_id: int, duration_seconds: float | None = None
    ) -> None:
        """Start countdown for audience member to submit private vote."""
        duration = (
            duration_seconds
            if duration_seconds is not None
            else float(settings.ONE_ON_ONE_VOTE_TIMEOUT_SECONDS)
        )

        async def _on_timeout():
            await self.handle_vote_timeout(room_id, session_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="one_on_one_vote",
            duration_seconds=duration,
            on_timeout=_on_timeout,
            session_id=session_id,
        )

    def cancel_session_timer(self, room_id: int) -> None:
        """Cancel active timer for this room."""
        timer_service.cancel_timer(room_id)

    async def handle_question_timeout(self, room_id: int, session_id: int) -> None:
        """Audience member failed to ask private question in time -> eliminate and advance."""
        from app.database import SessionLocal
        with SessionLocal() as db:
            session = db.get(OneOnOneSession, session_id)
            if not session or session.state != OneOnOneSessionState.ACTIVE or session.question is not None:
                return

            logger.info("1-on-1 question timeout for session %d (audience=%d)", session.id, session.audience_id)
            now = datetime.now(timezone.utc)
            session.state = OneOnOneSessionState.COMPLETED
            session.completed_at = now

            p = db.get(RoomParticipant, (session.room_id, session.audience_id))
            if p:
                p.status = ParticipantStatus.ELIMINATED
                p.left_at = now

            user = db.get(User, session.audience_id)
            if user:
                user.state = UserState.QUEUED
                user.queued_at = now

            db.commit()

            # Notify audience member of elimination
            await ws_manager.send_to_user(
                room_id, session.audience_id, {"type": "eliminated", "room_id": room_id}
            )
            ws_manager.disconnect(room_id, session.audience_id)

            await self.activate_next_session(db, room_id)

    async def handle_answer_timeout(self, room_id: int, session_id: int) -> None:
        """Challenger failed to answer private question in time -> auto-fill '[No Response]' and begin voting."""
        from app.database import SessionLocal
        with SessionLocal() as db:
            session = db.get(OneOnOneSession, session_id)
            if not session or session.answer is not None:
                return

            logger.info("1-on-1 answer timeout for session %d -> auto-filling '[No Response]'", session.id)
            session.answer = "[No Response]"
            session.answered_at = datetime.now(timezone.utc)
            session.state = OneOnOneSessionState.VOTING
            db.commit()
            db.refresh(session)

            await ws_manager.send_to_users(
                room_id,
                [session.challenger_id, session.audience_id],
                {
                    "type": "one_on_one_answer",
                    "room_id": room_id,
                    "session_id": session.id,
                    "sequence": session.sequence,
                    "answer": "[No Response]",
                    "text": "[No Response]",
                },
            )

            # Start voting timer
            self.start_vote_timer(room_id, session.id)

    async def handle_vote_timeout(self, room_id: int, session_id: int) -> None:
        """Audience member failed to vote in time -> auto-submit NO vote."""
        from app.database import SessionLocal
        with SessionLocal() as db:
            session = db.get(OneOnOneSession, session_id)
            if not session or session.state != OneOnOneSessionState.VOTING or session.vote is not None:
                return

            logger.info("1-on-1 vote timeout for session %d -> auto-submitting NO vote", session.id)
            await self.submit_vote(db, room_id, session.id, session.audience_id, VoteChoice.NO)

    async def initialize_sessions_for_room(
        self, db: Session, room: Room
    ) -> list[OneOnOneSession]:
        """
        Create OneOnOneSession records for all surviving active audience participants.
        Orders participants deterministically by joined_at.
        Activates the first session; leaves remainder PENDING.
        """
        existing = list(
            db.execute(
                select(OneOnOneSession)
                .where(OneOnOneSession.room_id == room.id)
                .order_by(OneOnOneSession.sequence.asc())
            ).scalars()
        )
        if existing:
            return existing

        active_participants = [
            p
            for p in room.participants
            if p.left_at is None and p.role == PlayerRole.AUDIENCE
        ]
        # Deterministic sort by joined_at, then user_id
        active_participants.sort(key=lambda p: (p.joined_at, p.user_id))

        sessions: list[OneOnOneSession] = []
        now = datetime.now(timezone.utc)

        for idx, p in enumerate(active_participants, start=1):
            is_first = idx == 1
            session = OneOnOneSession(
                room_id=room.id,
                audience_id=p.user_id,
                challenger_id=room.challenger_id,
                sequence=idx,
                state=OneOnOneSessionState.ACTIVE if is_first else OneOnOneSessionState.PENDING,
                started_at=now if is_first else None,
            )
            db.add(session)
            sessions.append(session)

        db.commit()
        for s in sessions:
            db.refresh(s)

        logger.info(
            "Initialized %d one-on-one sessions for room %d", len(sessions), room.id
        )

        # Send targeted one_on_one_started to the active participants and public progress to room
        if sessions:
            first_session = sessions[0]
            total_count = len(sessions)
            await ws_manager.send_to_users(
                room.id,
                [first_session.challenger_id, first_session.audience_id],
                {
                    "type": "one_on_one_started",
                    "room_id": room.id,
                    "session_id": first_session.id,
                    "sequence": first_session.sequence,
                    "total": total_count,
                    "audience_id": first_session.audience_id,
                    "challenger_id": first_session.challenger_id,
                },
            )
            await ws_manager.broadcast(
                room.id,
                {
                    "type": "one_on_one_progress",
                    "room_id": room.id,
                    "completed": 0,
                    "total": total_count,
                },
            )
            # Start timer for audience member to ask the private question
            self.start_question_timer(room.id, first_session.id)

        return sessions

    def get_active_session(
        self, db: Session, room_id: int
    ) -> OneOnOneSession | None:
        """Fetch the currently active one-on-one session for a room."""
        return db.execute(
            select(OneOnOneSession).where(
                OneOnOneSession.room_id == room_id,
                OneOnOneSession.state.in_(
                    [
                        OneOnOneSessionState.ACTIVE,
                        OneOnOneSessionState.ANSWERED,
                        OneOnOneSessionState.VOTING,
                    ]
                ),
            )
        ).scalar_one_or_none()

    def get_sessions_for_room(
        self, db: Session, room_id: int
    ) -> list[OneOnOneSession]:
        """Fetch all sessions for a room ordered by sequence."""
        return list(
            db.execute(
                select(OneOnOneSession)
                .where(OneOnOneSession.room_id == room_id)
                .order_by(OneOnOneSession.sequence.asc())
            ).scalars()
        )

    def get_session(self, db: Session, session_id: int) -> OneOnOneSession:
        """Fetch a session by ID or raise SessionNotFoundError."""
        session = db.get(OneOnOneSession, session_id)
        if not session:
            raise SessionNotFoundError(session_id)
        return session

    async def submit_question(
        self,
        db: Session,
        room_id: int,
        session_id: int,
        user_id: int,
        text: str,
    ) -> OneOnOneSession:
        """
        Submit a free-form question from the session audience member.
        Routes the question strictly to the challenger and the active audience member.
        """
        session = self.get_session(db, session_id)
        if session.room_id != room_id:
            raise SessionNotFoundError(session_id)

        # 1. Verify user is the audience member of this session
        if user_id != session.audience_id:
            raise SessionUnauthorizedError(
                session_id=session.id,
                user_id=user_id,
                reason="Only the active audience member can ask a question.",
            )

        # 2. Verify state
        if session.state != OneOnOneSessionState.ACTIVE:
            raise InvalidSessionStateError(
                session_id=session.id,
                current_state=session.state.value,
                action="submit_question",
            )

        if session.question is not None:
            raise DuplicateSessionQuestionError(session_id=session.id)

        # 3. Validate text
        cleaned_text = text.strip()
        if not cleaned_text:
            raise InvalidQuestionPayloadError("Question text cannot be empty.")
        if len(cleaned_text) > settings.PRIVATE_QUESTION_MAX_LENGTH:
            raise InvalidQuestionPayloadError(
                f"Question exceeds maximum length of {settings.PRIVATE_QUESTION_MAX_LENGTH} characters."
            )

        session.question = cleaned_text
        db.commit()
        db.refresh(session)

        logger.info(
            "Private question submitted for session %d by user %d", session.id, user_id
        )

        # Cancel question timer and start challenger answer timer
        self.cancel_session_timer(room_id)
        self.start_answer_timer(room_id, session.id)

        # Send private question strictly to session participants over the GameRoom channel
        await ws_manager.send_to_users(
            room_id,
            [session.challenger_id, session.audience_id],
            {
                "type": "one_on_one_question",
                "room_id": room_id,
                "session_id": session.id,
                "sequence": session.sequence,
                "question": cleaned_text,
                "text": cleaned_text,
            },
        )

        return session

    async def submit_answer(
        self,
        db: Session,
        room_id: int,
        session_id: int,
        user_id: int,
        text: str,
    ) -> OneOnOneSession:
        """
        Submit an answer from the challenger.
        Routes the answer strictly to the active audience member and challenger.
        """
        session = self.get_session(db, session_id)
        if session.room_id != room_id:
            raise SessionNotFoundError(session_id)

        # 1. Verify user is the challenger
        if user_id != session.challenger_id:
            raise SessionUnauthorizedError(
                session_id=session.id,
                user_id=user_id,
                reason="Only the challenger can answer the private question.",
            )

        # 2. Verify question exists and session is active
        if session.question is None:
            raise InvalidSessionStateError(
                session_id=session.id,
                current_state=session.state.value,
                action="submit_answer (no question asked yet)",
            )

        if session.answer is not None:
            raise DuplicateSessionAnswerError(session_id=session.id)

        if session.state not in (
            OneOnOneSessionState.ACTIVE,
            OneOnOneSessionState.ANSWERED,
        ):
            raise InvalidSessionStateError(
                session_id=session.id,
                current_state=session.state.value,
                action="submit_answer",
            )

        cleaned_text = text.strip()
        if not cleaned_text:
            raise InvalidQuestionPayloadError("Answer text cannot be empty.")

        session.answer = cleaned_text
        session.answered_at = datetime.now(timezone.utc)
        session.state = OneOnOneSessionState.VOTING
        db.commit()
        db.refresh(session)

        logger.info(
            "Private answer submitted for session %d by challenger %d",
            session.id,
            user_id,
        )

        # Cancel answer timer and start audience private vote timer
        self.cancel_session_timer(room_id)
        self.start_vote_timer(room_id, session.id)

        # Send private answer strictly to session participants over the GameRoom channel
        await ws_manager.send_to_users(
            room_id,
            [session.challenger_id, session.audience_id],
            {
                "type": "one_on_one_answer",
                "room_id": room_id,
                "session_id": session.id,
                "sequence": session.sequence,
                "answer": cleaned_text,
                "text": cleaned_text,
            },
        )

        return session

    async def submit_vote(
        self,
        db: Session,
        room_id: int,
        session_id: int,
        user_id: int,
        vote_choice: VoteChoice,
    ) -> OneOnOneSession:
        """
        Submit mandatory private YES/NO vote from the audience member.
        Completes session, handles elimination if NO, and triggers next session.
        """
        session = self.get_session(db, session_id)
        if session.room_id != room_id:
            raise SessionNotFoundError(session_id)

        # 1. Verify user is the audience member
        if user_id != session.audience_id:
            raise SessionUnauthorizedError(
                session_id=session.id,
                user_id=user_id,
                reason="Only the audience member can vote in this session.",
            )

        # 2. Verify state is VOTING
        if session.state != OneOnOneSessionState.VOTING:
            raise InvalidSessionStateError(
                session_id=session.id,
                current_state=session.state.value,
                action="submit_vote",
            )

        if session.vote is not None:
            raise DuplicateSessionVoteError(session_id=session.id)

        # Cancel voting timer
        self.cancel_session_timer(room_id)

        now = datetime.now(timezone.utc)
        session.vote = vote_choice
        session.voted_at = now
        session.completed_at = now
        session.state = OneOnOneSessionState.COMPLETED

        logger.info(
            "Private vote recorded for session %d: %s", session.id, vote_choice.value
        )

        # Send completion event strictly to session participants
        await ws_manager.send_to_users(
            room_id,
            [session.challenger_id, session.audience_id],
            {
                "type": "one_on_one_completed",
                "room_id": room_id,
                "session_id": session.id,
                "sequence": session.sequence,
                "result": "accepted" if vote_choice == VoteChoice.YES else "rejected",
            },
        )

        # Handle YES vs NO
        if vote_choice == VoteChoice.NO:
            # Participant is eliminated from room
            p = db.get(RoomParticipant, (session.room_id, session.audience_id))
            if p:
                p.status = ParticipantStatus.ELIMINATED
                p.left_at = now

            user = db.get(User, session.audience_id)
            if user:
                user.state = UserState.QUEUED
                user.queued_at = now

            db.commit()
            db.refresh(session)

            # Notify audience member of elimination and disconnect socket
            await ws_manager.send_to_user(
                room_id, session.audience_id, {"type": "eliminated", "room_id": room_id}
            )
            ws_manager.disconnect(room_id, session.audience_id)
        else:
            # Participant survives 1-on-1 as a FINALIST
            p = db.get(RoomParticipant, (session.room_id, session.audience_id))
            if p:
                p.status = ParticipantStatus.FINALIST
            db.commit()
            db.refresh(session)

        # Broadcast progress to public room channel
        total_sessions = db.execute(
            select(func.count(OneOnOneSession.id)).where(
                OneOnOneSession.room_id == room_id
            )
        ).scalar_one()

        completed_sessions = db.execute(
            select(func.count(OneOnOneSession.id)).where(
                OneOnOneSession.room_id == room_id,
                OneOnOneSession.state == OneOnOneSessionState.COMPLETED,
            )
        ).scalar_one()

        await ws_manager.broadcast(
            room_id,
            {
                "type": "one_on_one_progress",
                "room_id": room_id,
                "completed": completed_sessions,
                "total": total_sessions,
            },
        )

        # Automatically activate the next session or finalize 1-on-1 phase
        await self.activate_next_session(db, room_id)

        return session

    async def activate_next_session(self, db: Session, room_id: int) -> None:
        """
        Find and activate the next pending session for an active audience member.
        If all sessions are finished, evaluate survivors and transition room.
        """
        lock = _get_room_lock(room_id)
        async with lock:
            room = db.get(Room, room_id)
            if not room or room.state != RoomState.ONE_ON_ONE:
                return

            # Check if there is already an active session
            active_session = self.get_active_session(db, room_id)
            if active_session:
                return

            pending_sessions = list(
                db.execute(
                    select(OneOnOneSession)
                    .where(
                        OneOnOneSession.room_id == room_id,
                        OneOnOneSession.state == OneOnOneSessionState.PENDING,
                    )
                    .order_by(OneOnOneSession.sequence.asc())
                ).scalars()
            )

            total_sessions = db.execute(
                select(func.count(OneOnOneSession.id)).where(
                    OneOnOneSession.room_id == room_id
                )
            ).scalar_one()

            next_session: OneOnOneSession | None = None
            now = datetime.now(timezone.utc)

            for s in pending_sessions:
                # Verify audience participant is still active
                p = db.get(RoomParticipant, (room_id, s.audience_id))
                if p and p.left_at is None and p.status in (ParticipantStatus.ACTIVE, ParticipantStatus.FINALIST):
                    s.state = OneOnOneSessionState.ACTIVE
                    s.started_at = now
                    next_session = s
                    break
                else:
                    # Stale session for an already eliminated participant
                    s.state = OneOnOneSessionState.COMPLETED
                    s.completed_at = now

            db.commit()

            if next_session:
                logger.info(
                    "Activated session %d (sequence=%d) for room %d",
                    next_session.id,
                    next_session.sequence,
                    room_id,
                )
                # Deliver one_on_one_started strictly to the new session participants
                await ws_manager.send_to_users(
                    room_id,
                    [next_session.challenger_id, next_session.audience_id],
                    {
                        "type": "one_on_one_started",
                        "room_id": room.id,
                        "session_id": next_session.id,
                        "audience_id": next_session.audience_id,
                        "challenger_id": next_session.challenger_id,
                        "sequence": next_session.sequence,
                        "total": total_sessions,
                    },
                )
                # Start question timer for the newly activated session
                self.start_question_timer(room_id, next_session.id)
            else:
                # All sessions completed!
                self.cancel_session_timer(room_id)
                finalists = [
                    p
                    for p in room.participants
                    if p.left_at is None
                    and p.role == PlayerRole.AUDIENCE
                    and p.status == ParticipantStatus.FINALIST
                ]
                survivor_count = len(finalists)
                logger.info(
                    "One-on-one phase finished for room %d with %d finalists",
                    room_id,
                    survivor_count,
                )

                if survivor_count > 1:
                    await room_state_service.transition(db, room.id, RoomState.FINAL_SELECTION)
                elif survivor_count == 1:
                    from app.services.match_service import match_service
                    await match_service.create_match_for_single_survivor(db, room, finalists[0].user_id)
                else:
                    if room.challenger_id is not None:
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
                            c_user = db.get(User, p_challenger.user_id)
                            if c_user:
                                c_user.state = UserState.QUEUED
                                c_user.queued_at = datetime.now(timezone.utc)
                            db.commit()
                            await ws_manager.send_to_user(
                                room.id,
                                p_challenger.user_id,
                                {"type": "eliminated", "room_id": room.id},
                            )
                            ws_manager.disconnect(room.id, p_challenger.user_id)

                    await room_state_service.transition(db, room.id, RoomState.COMPLETED)

                # Trigger queue manager room creation check for newly re-queued users
                from app.services.queue_manager import queue_manager

                queue_manager.try_create_rooms(db)


one_on_one_service = OneOnOneService()
