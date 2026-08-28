"""
QuestionService — question CRUD and room-level question selection.
"""

import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import Gender, QuestionTarget
from app.exceptions import InsufficientQuestionsError, QuestionNotFoundError
from app.models.question import Question
from app.schemas.question import QuestionCreate, QuestionUpdate

logger = logging.getLogger(__name__)


class QuestionService:
    """Manages question pool and dynamic selection for rooms."""

    def create_question(self, db: Session, payload: QuestionCreate) -> Question:
        """Create and persist a new question."""
        question = Question(
            text=payload.text,
            target_gender=payload.target_gender,
            active=payload.active,
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        logger.info("Created question %d (%s, target=%s)", question.id, question.text, question.target_gender)
        return question

    def get_question(self, db: Session, question_id: int) -> Question:
        """Fetch a question by ID or raise QuestionNotFoundError."""
        question = db.get(Question, question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        return question

    def list_questions(self, db: Session, active: bool | None = None) -> list[Question]:
        """List questions, optionally filtering by active status."""
        stmt = select(Question).order_by(Question.id.asc())
        if active is not None:
            stmt = stmt.where(Question.active == active)
        result = db.execute(stmt)
        return list(result.scalars().all())

    def update_question(
        self, db: Session, question_id: int, payload: QuestionUpdate
    ) -> Question:
        """Update an existing question."""
        question = self.get_question(db, question_id)
        if payload.text is not None:
            question.text = payload.text
        if payload.target_gender is not None:
            question.target_gender = payload.target_gender
        if payload.active is not None:
            question.active = payload.active
        question.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(question)
        logger.info("Updated question %d", question.id)
        return question

    def delete_question(self, db: Session, question_id: int) -> None:
        """Delete a question by ID."""
        question = self.get_question(db, question_id)
        db.delete(question)
        db.commit()
        logger.info("Deleted question %d", question_id)

    def get_eligible_questions(
        self, db: Session, challenger_gender: Gender
    ) -> list[Question]:
        """
        Return active questions eligible for a given challenger gender.
        Female challenger -> ANY, FEMALE
        Male challenger   -> ANY, MALE
        """
        gender_target = (
            QuestionTarget.FEMALE
            if challenger_gender == Gender.FEMALE
            else QuestionTarget.MALE
        )
        stmt = (
            select(Question)
            .where(
                Question.active.is_(True),
                Question.target_gender.in_([QuestionTarget.ANY, gender_target]),
            )
            .order_by(Question.id.asc())
        )
        result = db.execute(stmt)
        return list(result.scalars().all())

    def select_questions_for_room(
        self, db: Session, challenger_gender: Gender, count: int
    ) -> list[Question]:
        """
        Randomly select exactly *count* unique active questions matching
        the challenger's gender.

        Raises InsufficientQuestionsError if fewer than *count* questions exist.
        """
        eligible = self.get_eligible_questions(db, challenger_gender)
        if len(eligible) < count:
            raise InsufficientQuestionsError(
                required=count,
                available=len(eligible),
                gender=challenger_gender.value,
            )

        return random.sample(eligible, count)


question_service = QuestionService()
