import pytest

from app.enums import Gender, PlayerRole, RoomState, UserState
from app.models.room import Room
from app.models.user import User
from app.services.room_manager import RoomManager


@pytest.fixture()
def rm():
    return RoomManager()


def _make_user(db, name="TestUser", gender=Gender.MALE):
    user = User(name=name, gender=gender)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestCreateRoom:
    def test_returns_room_in_waiting_state(self, db, rm):
        room = rm.create_room(db, Gender.FEMALE)
        assert room.id is not None
        assert room.state == RoomState.WAITING

    def test_sets_challenger_gender(self, db, rm):
        room = rm.create_room(db, Gender.MALE)
        assert room.challenger_gender == Gender.MALE

    def test_challenger_id_is_null(self, db, rm):
        room = rm.create_room(db, Gender.FEMALE)
        assert room.challenger_id is None


class TestGetRoom:
    def test_returns_existing_room(self, db, rm):
        room = rm.create_room(db, Gender.MALE)
        fetched = rm.get_room(db, room.id)
        assert fetched.id == room.id

    def test_raises_404_for_missing_room(self, db, rm):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            rm.get_room(db, 99999)
        assert exc_info.value.status_code == 404


class TestAddParticipant:
    def test_creates_participant(self, db, rm):
        user = _make_user(db)
        room = rm.create_room(db, Gender.FEMALE)
        p = rm.add_participant(db, room, user, PlayerRole.AUDIENCE)
        assert p.room_id == room.id
        assert p.user_id == user.id
        assert p.role == PlayerRole.AUDIENCE
        assert p.left_at is None

    def test_sets_user_state_to_in_game(self, db, rm):
        user = _make_user(db)
        room = rm.create_room(db, Gender.FEMALE)
        rm.add_participant(db, room, user, PlayerRole.AUDIENCE)
        assert user.state == UserState.IN_GAME


class TestRemoveParticipant:
    def test_sets_left_at(self, db, rm):
        user = _make_user(db)
        room = rm.create_room(db, Gender.FEMALE)
        rm.add_participant(db, room, user, PlayerRole.AUDIENCE)
        p = rm.remove_participant(db, room, user)
        assert p.left_at is not None

    def test_returns_user_to_queued(self, db, rm):
        user = _make_user(db)
        room = rm.create_room(db, Gender.FEMALE)
        rm.add_participant(db, room, user, PlayerRole.AUDIENCE)
        rm.remove_participant(db, room, user)
        assert user.state == UserState.QUEUED

    def test_raises_404_if_not_participant(self, db, rm):
        from fastapi import HTTPException
        user = _make_user(db)
        room = rm.create_room(db, Gender.FEMALE)
        with pytest.raises(HTTPException) as exc_info:
            rm.remove_participant(db, room, user)
        assert exc_info.value.status_code == 404


class TestSetState:
    def test_updates_room_state(self, db, rm):
        room = rm.create_room(db, Gender.MALE)
        rm.set_state(db, room, RoomState.READY)
        assert room.state == RoomState.READY

    def test_can_progress_through_states(self, db, rm):
        room = rm.create_room(db, Gender.MALE)
        for state in [RoomState.READY, RoomState.INTRO, RoomState.QUESTIONING]:
            rm.set_state(db, room, state)
            assert room.state == state


class TestGetActiveParticipants:
    def test_excludes_participants_who_left(self, db, rm):
        room = rm.create_room(db, Gender.FEMALE)
        user1 = _make_user(db, "User1")
        user2 = _make_user(db, "User2")

        rm.add_participant(db, room, user1, PlayerRole.AUDIENCE)
        rm.add_participant(db, room, user2, PlayerRole.AUDIENCE)
        rm.remove_participant(db, room, user1)

        db.refresh(room)
        active = rm.get_active_participants(db, room)
        active_ids = {p.user_id for p in active}
        assert user1.id not in active_ids
        assert user2.id in active_ids
