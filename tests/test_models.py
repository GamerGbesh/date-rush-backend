import pytest
from sqlalchemy.exc import IntegrityError

from app.enums import Gender, PlayerRole, QuestionTarget, RoomState, UserState
from app.models.match import Match
from app.models.question import Question
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.models.vote import Vote


class TestQuestionModel:
    def test_create_question_defaults(self, db):
        q = Question(text="What is your favourite colour?")
        db.add(q)
        db.commit()
        db.refresh(q)
        assert q.id is not None
        assert q.target_gender == QuestionTarget.ANY
        assert q.active is True
        assert q.created_at is not None

    def test_create_question_with_gender_target(self, db):
        q = Question(text="Male-specific question", target_gender=QuestionTarget.MALE)
        db.add(q)
        db.commit()
        db.refresh(q)
        assert q.target_gender == QuestionTarget.MALE


class TestRoomModel:
    def test_create_room_defaults(self, db):
        room = Room(challenger_gender=Gender.FEMALE)
        db.add(room)
        db.commit()
        db.refresh(room)
        assert room.id is not None
        assert room.state == RoomState.WAITING
        assert room.current_round == 0
        assert room.challenger_id is None
        assert room.current_question_id is None

    def test_room_state_transitions(self, db):
        room = Room()
        db.add(room)
        db.commit()
        room.state = RoomState.READY
        db.commit()
        db.refresh(room)
        assert room.state == RoomState.READY


class TestRoomParticipantModel:
    def _make_user(self, db, name="TestUser", gender=Gender.MALE):
        user = User(name=name, gender=gender)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def _make_room(self, db):
        room = Room()
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    def test_add_participant(self, db):
        user = self._make_user(db)
        room = self._make_room(db)
        p = RoomParticipant(room_id=room.id, user_id=user.id, role=PlayerRole.AUDIENCE)
        db.add(p)
        db.commit()
        db.refresh(p)
        assert p.left_at is None
        assert p.joined_at is not None

    def test_duplicate_participant_raises(self, db):
        user = self._make_user(db)
        room = self._make_room(db)
        room_id, user_id = room.id, user.id
        p1 = RoomParticipant(room_id=room_id, user_id=user_id, role=PlayerRole.AUDIENCE)
        db.add(p1)
        db.commit()
        db.expunge_all()  # clear identity map to avoid SAWarning on duplicate
        p2 = RoomParticipant(room_id=room_id, user_id=user_id, role=PlayerRole.CHALLENGER)
        db.add(p2)
        with pytest.raises(IntegrityError):
            db.commit()



class TestVoteUniqueConstraint:
    def test_duplicate_vote_per_round_raises(self, db):
        from app.enums import VoteChoice
        voter = User(name="Voter", gender=Gender.MALE)
        target = User(name="Target", gender=Gender.FEMALE)
        room = Room()
        db.add_all([voter, target, room])
        db.commit()
        db.refresh(voter)
        db.refresh(target)
        db.refresh(room)

        v1 = Vote(room_id=room.id, round=1, voter_id=voter.id, target_id=target.id, vote=VoteChoice.YES)
        db.add(v1)
        db.commit()

        v2 = Vote(room_id=room.id, round=1, voter_id=voter.id, target_id=target.id, vote=VoteChoice.NO)
        db.add(v2)
        with pytest.raises(IntegrityError):
            db.commit()

    def test_same_voter_different_rounds_allowed(self, db):
        from app.enums import VoteChoice
        voter = User(name="Voter2", gender=Gender.FEMALE)
        target = User(name="Target2", gender=Gender.MALE)
        room = Room()
        db.add_all([voter, target, room])
        db.commit()
        db.refresh(voter)
        db.refresh(target)
        db.refresh(room)

        for round_num in (1, 2, 3):
            v = Vote(room_id=room.id, round=round_num, voter_id=voter.id, target_id=target.id, vote=VoteChoice.YES)
            db.add(v)
        db.commit()  # should not raise


class TestMatchModel:
    def test_create_match(self, db):
        challenger = User(name="Challenger", gender=Gender.MALE)
        audience = User(name="Audience", gender=Gender.FEMALE)
        room = Room()
        db.add_all([challenger, audience, room])
        db.commit()
        db.refresh(challenger)
        db.refresh(audience)
        db.refresh(room)

        match = Match(
            room_id=room.id,
            challenger_id=challenger.id,
            audience_id=audience.id,
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        assert match.id is not None
        assert match.created_at is not None
