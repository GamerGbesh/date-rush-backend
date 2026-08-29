"""
QuestioningService — manages public questioning flow, challenger answer submissions,
and automatic progression between questions.
"""

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import QuestionPhase, RoomState
from app.exceptions import (
    DuplicateAnswerError,
    InvalidAnswerSubmissionError,
    NotChallengerError,
    RoomNotFoundError,
)
from app.models.answer import Answer
from app.models.question import Question
from app.models.room import Room
from app.models.room_question import RoomQuestion
from app.services.room_state_service import room_state_service
from app.services.timer_service import timer_service
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


class QuestioningService:
    """Manages active questioning, answer validation, and automatic round progression."""

    def start_questioning_timer(
        self, room_id: int, duration_seconds: float | None = None
    ) -> None:
        """Start countdown timer for challenger to answer the public questions."""
        duration = (
            duration_seconds
            if duration_seconds is not None
            else float(settings.QUESTIONING_TIMEOUT_SECONDS)
        )

        async def _on_timeout():
            await self.handle_questioning_timeout(room_id)

        timer_service.start_timer(
            room_id=room_id,
            timer_type="questioning",
            duration_seconds=duration,
            on_timeout=_on_timeout,
        )

    def cancel_questioning_timer(self, room_id: int) -> None:
        """Cancel active questioning timer for a room."""
        timer_service.cancel_timer(room_id, "questioning")

    async def handle_questioning_timeout(self, room_id: int) -> None:
        """
        Handle questioning timeout when challenger timer expires:
        - If 0 questions answered: Disqualify challenger, return all participants to queue, complete room.
        - If partial answers: Auto-fill remaining questions with '[No Response]' and advance to VOTING.
        """
        from datetime import datetime, timezone
        from app.database import SessionLocal
        from app.enums import ParticipantStatus, PlayerRole, UserState
        from app.models.room import RoomParticipant
        from app.models.user import User
        from app.services.queue_manager import queue_manager

        with SessionLocal() as db:
            room = db.get(Room, room_id)
            if not room or room.state != RoomState.QUESTIONING:
                return

            answers = list(
                db.execute(
                    select(Answer).where(
                        Answer.room_id == room.id,
                        Answer.user_id == room.challenger_id,
                    )
                ).scalars()
            )

            now = datetime.now(timezone.utc)

            if len(answers) == 0:
                logger.warning(
                    "Challenger %s answered 0 questions before questioning timeout for room %d. Re-queuing all participants.",
                    room.challenger_id,
                    room.id,
                )
                active_participants = [
                    p for p in room.participants if p.left_at is None
                ]
                for p in active_participants:
                    p.status = ParticipantStatus.ELIMINATED
                    p.left_at = now
                    user = db.get(User, p.user_id)
                    if user:
                        user.state = UserState.QUEUED
                        user.queued_at = now

                room.state = RoomState.COMPLETED
                db.commit()

                # Broadcast timeout error to room participants
                await ws_manager.broadcast(
                    room.id,
                    {
                        "type": "questioning_timeout",
                        "room_id": room.id,
                        "error": "Challenger did not respond to any questions in time. All participants have been returned to the queue.",
                    },
                )
                await ws_manager.broadcast(
                    room.id,
                    {
                        "type": "room_completed",
                        "room_id": room.id,
                    },
                )

                # Disconnect sockets
                for p in active_participants:
                    ws_manager.disconnect(room.id, p.user_id)

                queue_manager.try_create_rooms(db)
            else:
                logger.info(
                    "Challenger %s answered %d/%d questions for room %d before timeout. Auto-filling remaining with '[No Response]' and transitioning to VOTING.",
                    room.challenger_id,
                    len(answers),
                    settings.PUBLIC_QUESTION_ROUNDS,
                    room.id,
                )
                answered_question_ids = {a.question_id for a in answers}
                for round_num in range(1, settings.PUBLIC_QUESTION_ROUNDS + 1):
                    rq = self.get_room_question_for_round(db, room.id, round_num)
                    if rq and rq.question_id not in answered_question_ids:
                        missing_answer = Answer(
                            room_id=room.id,
                            question_id=rq.question_id,
                            user_id=room.challenger_id,
                            answer="[No Response]",
                        )
                        db.add(missing_answer)
                        db.commit()
                        await self.broadcast_answer_revealed(
                            room.id, round_num, rq.question_id, "[No Response]"
                        )

                await room_state_service.transition(db, room.id, RoomState.VOTING)

    def get_room_question_for_round(
        self, db: Session, room_id: int, round_number: int
    ) -> RoomQuestion | None:
        """Fetch the RoomQuestion record assigned to a specific round position."""
        stmt = select(RoomQuestion).where(
            RoomQuestion.room_id == room_id,
            RoomQuestion.position == round_number,
            RoomQuestion.phase == QuestionPhase.PUBLIC,
        )
        return db.execute(stmt).scalar_one_or_none()

    async def broadcast_question_started(
        self, room_id: int, round_number: int, question: Question
    ) -> None:
        """Broadcast question_started event to all connected room participants."""
        payload = {
            "type": "question_started",
            "room_id": room_id,
            "round": round_number,
            "question": {
                "id": question.id,
                "text": question.text,
            },
        }
        await ws_manager.broadcast(room_id, payload)
        logger.info(
            "Broadcasted question_started for room %d (round=%d, question=%d)",
            room_id,
            round_number,
            question.id,
        )

    async def broadcast_answer_revealed(
        self, room_id: int, round_number: int, question_id: int, answer_text: str
    ) -> None:
        """Broadcast answer_revealed event to all connected room participants."""
        payload = {
            "type": "answer_revealed",
            "room_id": room_id,
            "round": round_number,
            "question_id": question_id,
            "answer": answer_text,
        }
        await ws_manager.broadcast(room_id, payload)
        logger.info(
            "Broadcasted answer_revealed for room %d (round=%d, question=%d)",
            room_id,
            round_number,
            question_id,
        )

    async def start_questioning_round(self, db: Session, room: Room) -> None:
        """
        Set up the current question for the room's current round and broadcast
        question_started.
        """
        rq = self.get_room_question_for_round(db, room.id, room.current_round)
        if rq is None:
            logger.warning(
                "No RoomQuestion found for room %d at position %d",
                room.id,
                room.current_round,
            )
            return

        question = db.get(Question, rq.question_id)
        if question is None:
            logger.error("Question %d missing from database", rq.question_id)
            return

        room.current_question_id = question.id
        db.commit()
        db.refresh(room)

        await self.broadcast_question_started(room.id, room.current_round, question)

    async def submit_answer(
        self, db: Session, room_id: int, user_id: int, answer_text: str
    ) -> Answer:
        """
        Submit challenger's answer, persist it, broadcast it, and automatically
        advance to the next question or transition to VOTING.
        """
        room = db.get(Room, room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        # 1. Verify room is in QUESTIONING state
        if room.state != RoomState.QUESTIONING:
            raise InvalidAnswerSubmissionError(
                f"Cannot submit answer: room {room_id} is in state '{room.state.value}', not 'questioning'."
            )

        # 2. Verify user is the challenger
        if user_id != room.challenger_id:
            raise NotChallengerError(room_id=room.id, user_id=user_id)

        # 3. Determine current question
        rq = self.get_room_question_for_round(db, room.id, room.current_round)
        if rq is None:
            raise InvalidAnswerSubmissionError(
                f"No active question configured for room {room_id} at round {room.current_round}."
            )
        question = db.get(Question, rq.question_id)
        if question is None:
            raise InvalidAnswerSubmissionError(
                f"Question {rq.question_id} not found."
            )

        # 4. Check for duplicate answer
        existing_answer = db.execute(
            select(Answer).where(
                Answer.room_id == room.id,
                Answer.question_id == question.id,
                Answer.user_id == user_id,
            )
        ).scalar_one_or_none()
        if existing_answer:
            raise DuplicateAnswerError(
                room_id=room.id,
                question_id=question.id,
                user_id=user_id,
            )

        # 5. Persist answer
        answer_record = Answer(
            room_id=room.id,
            question_id=question.id,
            user_id=user_id,
            answer=answer_text,
        )
        db.add(answer_record)
        db.commit()
        db.refresh(answer_record)

        logger.info(
            "Answer recorded for room %d (round=%d, question=%d, challenger=%d)",
            room.id,
            room.current_round,
            question.id,
            user_id,
        )

        # 6. Broadcast answer revealed
        await self.broadcast_answer_revealed(
            room.id, room.current_round, question.id, answer_text
        )

        # 7. Automatic progression
        if room.current_round < settings.PUBLIC_QUESTION_ROUNDS:
            # Advance round and start next question
            room.current_round += 1
            next_rq = self.get_room_question_for_round(db, room.id, room.current_round)
            if next_rq:
                room.current_question_id = next_rq.question_id
                next_question = db.get(Question, next_rq.question_id)
                db.commit()
                db.refresh(room)
                if next_question:
                    await self.broadcast_question_started(
                        room.id, room.current_round, next_question
                    )
        else:
            # All public questions completed -> automatically transition to VOTING
            logger.info(
                "All %d public questions completed for room %d -> transitioning to VOTING",
                settings.PUBLIC_QUESTION_ROUNDS,
                room.id,
            )
            await room_state_service.transition(db, room.id, RoomState.VOTING)

        return answer_record


questioning_service = QuestioningService()
