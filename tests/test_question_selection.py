from app.config import settings
from app.enums import Gender, QuestionPhase, QuestionTarget, RoomState, UserState
from app.models.question import Question
from app.models.room import Room
from app.models.room_question import RoomQuestion
from app.models.user import User
from app.services.queue_manager import queue_manager
from app.services.room_manager import room_manager


def _enqueue_user(db, name: str, gender: Gender) -> User:
    user = User(name=name, gender=gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    queue_manager.add(db, user)
    return user


class TestQuestionSelectionAtRoomCreation:
    def test_room_creation_persists_question_sequence(self, db):
        for i in range(5):
            _enqueue_user(db, f"M{i}", Gender.MALE)
        female = _enqueue_user(db, "F0", Gender.FEMALE)

        rooms = queue_manager.try_create_rooms(db)
        assert len(rooms) == 1
        room = rooms[0]

        rqs = db.query(RoomQuestion).where(RoomQuestion.room_id == room.id).order_by(RoomQuestion.position).all()
        assert len(rqs) == settings.PUBLIC_QUESTION_ROUNDS
        assert [rq.position for rq in rqs] == [1, 2, 3]
        for rq in rqs:
            assert rq.phase == QuestionPhase.PUBLIC
            # Verify the question exists and is active
            q = db.get(Question, rq.question_id)
            assert q is not None
            assert q.active is True
            assert q.target_gender in [QuestionTarget.ANY, QuestionTarget.FEMALE]

    def test_independent_rooms_have_independent_sequences(self, db):
        for i in range(10):
            _enqueue_user(db, f"M{i}", Gender.MALE)
        _enqueue_user(db, "F0", Gender.FEMALE)
        _enqueue_user(db, "F1", Gender.FEMALE)

        rooms = queue_manager.try_create_rooms(db)
        assert len(rooms) == 2

        seq1 = [rq.question_id for rq in rooms[0].room_questions]
        seq2 = [rq.question_id for rq in rooms[1].room_questions]
        assert len(seq1) == 3
        assert len(seq2) == 3

    def test_insufficient_questions_fails_room_creation_safely(self, db):
        # Delete all questions to make count insufficient
        db.query(Question).delete()
        db.commit()
        db.expunge_all()

        # Add only 1 question (threshold is 3)
        db.add(Question(text="Solo Q", target_gender=QuestionTarget.ANY, active=True))
        db.commit()

        users = [_enqueue_user(db, f"M{i}", Gender.MALE) for i in range(5)]
        female = _enqueue_user(db, "F0", Gender.FEMALE)

        rooms = queue_manager.try_create_rooms(db)
        assert len(rooms) == 0

        # Verify users remain QUEUED
        for u in users:
            db.refresh(u)
            assert u.state == UserState.QUEUED
        db.refresh(female)
        assert female.state == UserState.QUEUED

        # Verify no partial room created
        assert db.query(Room).count() == 0
