import pytest

from app.enums import Gender, ParticipantStatus, PlayerRole, RoomState, UserState, VoteChoice
from app.exceptions import DuplicateVoteError, InvalidVoterError, InvalidVotingStateError, RoomNotFoundError
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.models.vote import Vote
from app.services.voting_service import voting_service


def _create_voting_room(db) -> tuple[Room, User, list[User]]:
    challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
    audience = [
        User(name=f"Audience_{i}", gender=Gender.MALE, state=UserState.IN_GAME)
        for i in range(5)
    ]
    db.add_all([challenger] + audience)
    db.commit()

    room = Room(
        state=RoomState.VOTING,
        challenger_id=challenger.id,
        challenger_gender=challenger.gender,
        current_round=1,
    )
    db.add(room)
    db.flush()

    db.add(RoomParticipant(room_id=room.id, user_id=challenger.id, role=PlayerRole.CHALLENGER))
    for a in audience:
        db.add(RoomParticipant(room_id=room.id, user_id=a.id, role=PlayerRole.AUDIENCE))

    db.commit()
    db.refresh(room)
    return room, challenger, audience


class TestVoteSubmissionValidations:
    @pytest.mark.asyncio
    async def test_active_audience_can_vote_yes(self, db):
        room, _, audience = _create_voting_room(db)
        vote = await voting_service.submit_vote(
            db=db,
            room_id=room.id,
            voter_id=audience[0].id,
            vote_choice=VoteChoice.YES,
        )
        assert vote.id is not None
        assert vote.vote == VoteChoice.YES
        assert vote.voter_id == audience[0].id
        assert vote.target_id == room.challenger_id

    @pytest.mark.asyncio
    async def test_active_audience_can_vote_no(self, db):
        room, _, audience = _create_voting_room(db)
        vote = await voting_service.submit_vote(
            db=db,
            room_id=room.id,
            voter_id=audience[1].id,
            vote_choice=VoteChoice.NO,
        )
        assert vote.id is not None
        assert vote.vote == VoteChoice.NO

    @pytest.mark.asyncio
    async def test_challenger_cannot_vote(self, db):
        room, challenger, _ = _create_voting_room(db)
        with pytest.raises(InvalidVoterError) as exc_info:
            await voting_service.submit_vote(
                db=db,
                room_id=room.id,
                voter_id=challenger.id,
                vote_choice=VoteChoice.YES,
            )
        assert "Challenger cannot submit an audience vote" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_outsider_cannot_vote(self, db):
        room, _, _ = _create_voting_room(db)
        outsider = User(name="Outsider", gender=Gender.MALE, state=UserState.WAITING)
        db.add(outsider)
        db.commit()

        with pytest.raises(InvalidVoterError):
            await voting_service.submit_vote(
                db=db,
                room_id=room.id,
                voter_id=outsider.id,
                vote_choice=VoteChoice.YES,
            )

    @pytest.mark.asyncio
    async def test_eliminated_participant_cannot_vote(self, db):
        room, _, audience = _create_voting_room(db)
        p = db.get(RoomParticipant, (room.id, audience[0].id))
        p.left_at = db.get(User, audience[0].id).created_at
        p.status = ParticipantStatus.ELIMINATED
        db.commit()

        with pytest.raises(InvalidVoterError):
            await voting_service.submit_vote(
                db=db,
                room_id=room.id,
                voter_id=audience[0].id,
                vote_choice=VoteChoice.YES,
            )

    @pytest.mark.asyncio
    async def test_voting_outside_voting_state_rejected(self, db):
        room, _, audience = _create_voting_room(db)
        room.state = RoomState.QUESTIONING
        db.commit()

        with pytest.raises(InvalidVotingStateError):
            await voting_service.submit_vote(
                db=db,
                room_id=room.id,
                voter_id=audience[0].id,
                vote_choice=VoteChoice.YES,
            )

    @pytest.mark.asyncio
    async def test_duplicate_vote_rejected(self, db):
        room, _, audience = _create_voting_room(db)
        await voting_service.submit_vote(
            db=db,
            room_id=room.id,
            voter_id=audience[0].id,
            vote_choice=VoteChoice.YES,
        )

        with pytest.raises(DuplicateVoteError):
            await voting_service.submit_vote(
                db=db,
                room_id=room.id,
                voter_id=audience[0].id,
                vote_choice=VoteChoice.NO,
            )


class TestVotingStatus:
    @pytest.mark.asyncio
    async def test_get_voting_status_reflects_progress(self, db):
        room, _, audience = _create_voting_room(db)
        status_before = voting_service.get_voting_status(db, room.id, user_id=audience[0].id)
        assert status_before.total_voters == 5
        assert status_before.votes_submitted == 0
        assert status_before.votes_remaining == 5
        assert status_before.has_voted is False

        await voting_service.submit_vote(db, room.id, audience[0].id, VoteChoice.YES)

        status_after = voting_service.get_voting_status(db, room.id, user_id=audience[0].id)
        assert status_after.total_voters == 5
        assert status_after.votes_submitted == 1
        assert status_after.votes_remaining == 4
        assert status_after.has_voted is True
