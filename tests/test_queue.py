import pytest

from app.enums import Gender, UserState
from app.models.user import User
from app.services.queue_manager import QueueManager


@pytest.fixture()
def qm():
    return QueueManager()


def _make_user(db, name, gender):
    user = User(name=name, gender=gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestQueueManagerAdd:
    def test_add_sets_state_to_queued(self, db, qm):
        user = _make_user(db, "Alice", Gender.FEMALE)
        assert user.state == UserState.WAITING
        qm.add(db, user)
        assert user.state == UserState.QUEUED

    def test_add_increments_queue_size(self, db, qm):
        assert qm.get_size(db, Gender.MALE) == 0
        user = _make_user(db, "Bob", Gender.MALE)
        qm.add(db, user)
        assert qm.get_size(db, Gender.MALE) == 1


class TestQueueManagerRemove:
    def test_remove_sets_state_to_waiting(self, db, qm):
        user = _make_user(db, "Carol", Gender.FEMALE)
        qm.add(db, user)
        qm.remove(db, user)
        assert user.state == UserState.WAITING

    def test_remove_decrements_queue_size(self, db, qm):
        user = _make_user(db, "Dave", Gender.MALE)
        qm.add(db, user)
        assert qm.get_size(db, Gender.MALE) == 1
        qm.remove(db, user)
        assert qm.get_size(db, Gender.MALE) == 0


class TestQueueManagerGetUsers:
    def test_get_users_returns_only_correct_gender(self, db, qm):
        alice = _make_user(db, "Alice", Gender.FEMALE)
        bob = _make_user(db, "Bob", Gender.MALE)
        qm.add(db, alice)
        qm.add(db, bob)

        female_users = qm.get_users(db, Gender.FEMALE)
        assert len(female_users) == 1
        assert female_users[0].id == alice.id

    def test_get_users_returns_empty_when_none_queued(self, db, qm):
        assert qm.get_users(db, Gender.MALE) == []

    def test_get_size_is_gender_specific(self, db, qm):
        for i in range(3):
            u = _make_user(db, f"F{i}", Gender.FEMALE)
            qm.add(db, u)
        for i in range(2):
            u = _make_user(db, f"M{i}", Gender.MALE)
            qm.add(db, u)

        assert qm.get_size(db, Gender.FEMALE) == 3
        assert qm.get_size(db, Gender.MALE) == 2


class TestQueueManagerPopMany:
    def test_pop_many_returns_correct_count(self, db, qm):
        for i in range(5):
            u = _make_user(db, f"User{i}", Gender.MALE)
            qm.add(db, u)

        popped = qm.pop_many(db, Gender.MALE, 3)
        assert len(popped) == 3

    def test_pop_many_sets_state_to_in_game(self, db, qm):
        users = []
        for i in range(3):
            u = _make_user(db, f"User{i}", Gender.FEMALE)
            qm.add(db, u)
            users.append(u)

        popped = qm.pop_many(db, Gender.FEMALE, 3)
        for u in popped:
            assert u.state == UserState.IN_GAME

    def test_pop_many_reduces_queue_size(self, db, qm):
        for i in range(4):
            u = _make_user(db, f"User{i}", Gender.MALE)
            qm.add(db, u)

        qm.pop_many(db, Gender.MALE, 2)
        assert qm.get_size(db, Gender.MALE) == 2

    def test_pop_many_capped_at_available(self, db, qm):
        for i in range(2):
            u = _make_user(db, f"User{i}", Gender.FEMALE)
            qm.add(db, u)

        popped = qm.pop_many(db, Gender.FEMALE, 10)
        assert len(popped) == 2
