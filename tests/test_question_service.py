import pytest

from app.enums import Gender, QuestionTarget
from app.exceptions import InsufficientQuestionsError, QuestionNotFoundError
from app.models.question import Question
from app.schemas.question import QuestionCreate, QuestionUpdate
from app.services.question_service import question_service


class TestQuestionCRUD:
    def test_create_and_get_question(self, db):
        payload = QuestionCreate(
            text="What is your favorite travel destination?",
            target_gender=QuestionTarget.ANY,
            active=True,
        )
        q = question_service.create_question(db, payload)
        assert q.id is not None
        assert q.text == "What is your favorite travel destination?"
        assert q.target_gender == QuestionTarget.ANY
        assert q.active is True
        assert q.created_at is not None

        fetched = question_service.get_question(db, q.id)
        assert fetched.id == q.id
        assert fetched.text == q.text

    def test_get_nonexistent_question_raises_404_domain_error(self, db):
        with pytest.raises(QuestionNotFoundError):
            question_service.get_question(db, 99999)

    def test_list_questions_with_active_filter(self, db):
        # Clear out any existing questions first
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        q1 = question_service.create_question(
            db, QuestionCreate(text="Active Q", active=True)
        )
        q2 = question_service.create_question(
            db, QuestionCreate(text="Inactive Q", active=False)
        )

        all_q = question_service.list_questions(db)
        assert len(all_q) == 2

        active_q = question_service.list_questions(db, active=True)
        assert len(active_q) == 1
        assert active_q[0].id == q1.id

        inactive_q = question_service.list_questions(db, active=False)
        assert len(inactive_q) == 1
        assert inactive_q[0].id == q2.id

    def test_update_question(self, db):
        q = question_service.create_question(
            db, QuestionCreate(text="Initial Text", target_gender=QuestionTarget.ANY, active=True)
        )
        updated = question_service.update_question(
            db, q.id, QuestionUpdate(text="Updated Text", active=False)
        )
        assert updated.text == "Updated Text"
        assert updated.active is False
        assert updated.target_gender == QuestionTarget.ANY

    def test_delete_question(self, db):
        q = question_service.create_question(
            db, QuestionCreate(text="To be deleted", target_gender=QuestionTarget.ANY)
        )
        question_service.delete_question(db, q.id)
        with pytest.raises(QuestionNotFoundError):
            question_service.get_question(db, q.id)


class TestGenderFiltering:
    def test_female_challenger_gets_any_and_female_only(self, db):
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        q_any = question_service.create_question(
            db, QuestionCreate(text="Any Q", target_gender=QuestionTarget.ANY)
        )
        q_female = question_service.create_question(
            db, QuestionCreate(text="Female Q", target_gender=QuestionTarget.FEMALE)
        )
        q_male = question_service.create_question(
            db, QuestionCreate(text="Male Q", target_gender=QuestionTarget.MALE)
        )

        eligible = question_service.get_eligible_questions(db, Gender.FEMALE)
        eligible_ids = [q.id for q in eligible]
        assert q_any.id in eligible_ids
        assert q_female.id in eligible_ids
        assert q_male.id not in eligible_ids

    def test_male_challenger_gets_any_and_male_only(self, db):
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        q_any = question_service.create_question(
            db, QuestionCreate(text="Any Q", target_gender=QuestionTarget.ANY)
        )
        q_female = question_service.create_question(
            db, QuestionCreate(text="Female Q", target_gender=QuestionTarget.FEMALE)
        )
        q_male = question_service.create_question(
            db, QuestionCreate(text="Male Q", target_gender=QuestionTarget.MALE)
        )

        eligible = question_service.get_eligible_questions(db, Gender.MALE)
        eligible_ids = [q.id for q in eligible]
        assert q_any.id in eligible_ids
        assert q_male.id in eligible_ids
        assert q_female.id not in eligible_ids

    def test_inactive_questions_are_excluded(self, db):
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        question_service.create_question(
            db, QuestionCreate(text="Inactive Q", target_gender=QuestionTarget.ANY, active=False)
        )
        eligible = question_service.get_eligible_questions(db, Gender.FEMALE)
        assert len(eligible) == 0


class TestQuestionSelection:
    def test_insufficient_questions_raises_error(self, db):
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        question_service.create_question(
            db, QuestionCreate(text="Only One Q", target_gender=QuestionTarget.ANY, active=True)
        )
        with pytest.raises(InsufficientQuestionsError) as exc_info:
            question_service.select_questions_for_room(db, Gender.FEMALE, count=3)
        assert exc_info.value.required == 3
        assert exc_info.value.available == 1

    def test_selects_exact_count_uniquely(self, db):
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        for i in range(10):
            question_service.create_question(
                db, QuestionCreate(text=f"Question {i}", target_gender=QuestionTarget.ANY, active=True)
            )

        selected = question_service.select_questions_for_room(db, Gender.FEMALE, count=3)
        assert len(selected) == 3
        assert len(set(q.id for q in selected)) == 3
