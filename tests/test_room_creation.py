"""
Service-layer tests for room creation algorithm.

All tests work directly against QueueManager / RoomManager via the db
fixture — no HTTP involved.
"""

import pytest

from app.config import settings
from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.room import RoomParticipant
from app.models.user import User
from app.services.queue_manager import QueueManager
from app.services.room_manager import RoomManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _join_queue(db, qm: QueueManager, name: str, gender: Gender) -> User:
    """Create and queue a user in one call."""
    user = User(name=name, gender=gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    qm.add(db, user)
    return user


def _active_participants(db, room_id: int) -> list[RoomParticipant]:
    from sqlalchemy import select
    return list(
        db.execute(
            select(RoomParticipant).where(
                RoomParticipant.room_id == room_id,
                RoomParticipant.left_at.is_(None),
            )
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Core creation cases
# ---------------------------------------------------------------------------

class TestBasicRoomCreation:
    def test_5m_1f_creates_one_room(self, db):
        qm = QueueManager()
        for i in range(5):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        female = _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        assert len(rooms) == 1
        room = rooms[0]
        assert room.state == RoomState.READY
        assert room.challenger_gender == Gender.FEMALE

    def test_5m_1f_correct_roles(self, db):
        qm = QueueManager()
        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(5)]
        female = _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)
        participants = _active_participants(db, rooms[0].id)

        challengers = [p for p in participants if p.role == PlayerRole.CHALLENGER]
        audience = [p for p in participants if p.role == PlayerRole.AUDIENCE]

        assert len(challengers) == 1
        assert challengers[0].user_id == female.id
        assert len(audience) == settings.GAME_ROOM_THRESHOLD

    def test_1m_5f_creates_one_room_opposite_direction(self, db):
        qm = QueueManager()
        male = _join_queue(db, qm, "M0", Gender.MALE)
        for i in range(5):
            _join_queue(db, qm, f"F{i}", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        assert len(rooms) == 1
        assert rooms[0].challenger_gender == Gender.MALE

    def test_1m_5f_correct_roles(self, db):
        qm = QueueManager()
        male = _join_queue(db, qm, "M0", Gender.MALE)
        females = [_join_queue(db, qm, f"F{i}", Gender.FEMALE) for i in range(5)]

        rooms = qm.try_create_rooms(db)
        participants = _active_participants(db, rooms[0].id)

        challengers = [p for p in participants if p.role == PlayerRole.CHALLENGER]
        audience = [p for p in participants if p.role == PlayerRole.AUDIENCE]

        assert len(challengers) == 1
        assert challengers[0].user_id == male.id
        assert len(audience) == settings.GAME_ROOM_THRESHOLD
        audience_ids = {p.user_id for p in audience}
        assert all(f.id in audience_ids for f in females)


# ---------------------------------------------------------------------------
# Insufficient queue — no room should be created
# ---------------------------------------------------------------------------

class TestInsufficientQueue:
    def test_4m_1f_no_room(self, db):
        qm = QueueManager()
        for i in range(4):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        assert rooms == []
        assert qm.get_size(db, Gender.MALE) == 4
        assert qm.get_size(db, Gender.FEMALE) == 1

    def test_5m_0f_no_room(self, db):
        qm = QueueManager()
        for i in range(5):
            _join_queue(db, qm, f"M{i}", Gender.MALE)

        rooms = qm.try_create_rooms(db)

        assert rooms == []
        assert qm.get_size(db, Gender.MALE) == 5

    def test_all_users_remain_queued_when_no_room(self, db):
        qm = QueueManager()
        users = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(4)]

        qm.try_create_rooms(db)

        for u in users:
            db.refresh(u)
            assert u.state == UserState.QUEUED


# ---------------------------------------------------------------------------
# Multiple rooms
# ---------------------------------------------------------------------------

class TestMultipleRooms:
    def test_10m_2f_creates_two_rooms(self, db):
        qm = QueueManager()
        for i in range(10):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        for i in range(2):
            _join_queue(db, qm, f"F{i}", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        assert len(rooms) == 2
        for room in rooms:
            assert room.state == RoomState.READY
            assert room.challenger_gender == Gender.FEMALE

    def test_10m_2f_correct_participant_counts(self, db):
        qm = QueueManager()
        for i in range(10):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        for i in range(2):
            _join_queue(db, qm, f"F{i}", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        for room in rooms:
            participants = _active_participants(db, room.id)
            challengers = [p for p in participants if p.role == PlayerRole.CHALLENGER]
            audience = [p for p in participants if p.role == PlayerRole.AUDIENCE]
            assert len(challengers) == 1
            assert len(audience) == settings.GAME_ROOM_THRESHOLD

    def test_10m_2f_queues_empty_after(self, db):
        qm = QueueManager()
        for i in range(10):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        for i in range(2):
            _join_queue(db, qm, f"F{i}", Gender.FEMALE)

        qm.try_create_rooms(db)

        assert qm.get_size(db, Gender.MALE) == 0
        assert qm.get_size(db, Gender.FEMALE) == 0


# ---------------------------------------------------------------------------
# Remainder — partial consumption
# ---------------------------------------------------------------------------

class TestRemainder:
    def test_7m_1f_one_room_2_males_remain(self, db):
        qm = QueueManager()
        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(7)]
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        assert len(rooms) == 1
        assert qm.get_size(db, Gender.MALE) == 2
        assert qm.get_size(db, Gender.FEMALE) == 0

    def test_remainder_users_stay_queued(self, db):
        qm = QueueManager()
        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(7)]
        _join_queue(db, qm, "F0", Gender.FEMALE)

        qm.try_create_rooms(db)

        # Last 2 males should remain QUEUED
        for u in males[-2:]:
            db.refresh(u)
            assert u.state == UserState.QUEUED

        # First 5 males should be IN_GAME
        for u in males[:5]:
            db.refresh(u)
            assert u.state == UserState.IN_GAME


# ---------------------------------------------------------------------------
# FIFO ordering
# ---------------------------------------------------------------------------

class TestFIFOOrdering:
    def test_first_n_users_selected_as_audience(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(threshold + 1)]
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)

        participants = _active_participants(db, rooms[0].id)
        audience_ids = {p.user_id for p in participants if p.role == PlayerRole.AUDIENCE}

        # The first `threshold` males should be in the room
        for m in males[:threshold]:
            assert m.id in audience_ids

        # The last male should remain queued
        db.refresh(males[-1])
        assert males[-1].state == UserState.QUEUED
        assert males[-1].id not in audience_ids

    def test_first_female_is_challenger(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        females = [_join_queue(db, qm, f"F{i}", Gender.FEMALE) for i in range(3)]

        rooms = qm.try_create_rooms(db)

        # First female should be challenger
        participants = _active_participants(db, rooms[0].id)
        challenger_ids = {p.user_id for p in participants if p.role == PlayerRole.CHALLENGER}
        assert females[0].id in challenger_ids


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_waiting_to_queued(self, db):
        qm = QueueManager()
        user = User(name="Alice", gender=Gender.FEMALE)
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.state == UserState.WAITING
        qm.add(db, user)
        assert user.state == UserState.QUEUED
        assert user.queued_at is not None

    def test_queued_to_in_game_on_room_creation(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(threshold)]
        female = _join_queue(db, qm, "F0", Gender.FEMALE)

        qm.try_create_rooms(db)

        for u in males + [female]:
            db.refresh(u)
            assert u.state == UserState.IN_GAME
            assert u.queued_at is None

    def test_queued_at_cleared_on_room_assignment(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        female = _join_queue(db, qm, "F0", Gender.FEMALE)

        qm.try_create_rooms(db)

        db.refresh(female)
        assert female.queued_at is None


# ---------------------------------------------------------------------------
# Idempotency / safety
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_calling_twice_does_not_duplicate_rooms(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms_first = qm.try_create_rooms(db)
        rooms_second = qm.try_create_rooms(db)

        assert len(rooms_first) == 1
        assert len(rooms_second) == 0  # nothing left to form another room

    def test_calling_on_empty_queue_is_harmless(self, db):
        qm = QueueManager()
        rooms = qm.try_create_rooms(db)
        assert rooms == []

    def test_room_has_exactly_one_challenger(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)
        participants = _active_participants(db, rooms[0].id)
        challengers = [p for p in participants if p.role == PlayerRole.CHALLENGER]
        assert len(challengers) == 1

    def test_room_has_exactly_threshold_audience(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        _join_queue(db, qm, "F0", Gender.FEMALE)

        rooms = qm.try_create_rooms(db)
        participants = _active_participants(db, rooms[0].id)
        audience = [p for p in participants if p.role == PlayerRole.AUDIENCE]
        assert len(audience) == threshold

    def test_challenger_gender_opposite_to_audience(self, db):
        qm = QueueManager()
        threshold = settings.GAME_ROOM_THRESHOLD
        for i in range(threshold):
            _join_queue(db, qm, f"M{i}", Gender.MALE)
        _join_queue(db, qm, "F0", Gender.FEMALE)

        from sqlalchemy import select as sa_select
        rooms = qm.try_create_rooms(db)
        room = rooms[0]

        challenger_user = db.get(User, room.challenger_id)
        participants = _active_participants(db, room.id)
        audience_ids = {p.user_id for p in participants if p.role == PlayerRole.AUDIENCE}

        for uid in audience_ids:
            audience_user = db.get(User, uid)
            assert audience_user.gender != challenger_user.gender


# ---------------------------------------------------------------------------
# Transaction consistency
# ---------------------------------------------------------------------------

class TestTransactionConsistency:
    def test_failed_room_creation_leaves_users_queued(self, db):
        """
        If room creation raises an exception after state changes but before
        commit, the rollback should leave users in QUEUED state.
        """
        from unittest.mock import patch
        qm = QueueManager()
        rm = RoomManager()
        threshold = settings.GAME_ROOM_THRESHOLD

        males = [_join_queue(db, qm, f"M{i}", Gender.MALE) for i in range(threshold)]
        female = _join_queue(db, qm, "F0", Gender.FEMALE)

        # Patch db.flush to raise after state changes are written to session
        original_flush = db.flush
        call_count = {"n": 0}

        def boom():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated flush failure")
            return original_flush()

        with patch.object(db, "flush", boom):
            with pytest.raises(RuntimeError):
                rm.create_room_with_participants(db, female, males)

        # All users should still be QUEUED (rollback happened)
        for u in males + [female]:
            db.refresh(u)
            assert u.state == UserState.QUEUED
