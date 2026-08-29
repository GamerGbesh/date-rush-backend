import pytest

from app.enums import Gender, ParticipantStatus, PlayerRole, RoomState, UserState, VoteChoice
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.voting_service import voting_service


def _setup_voting_scenario(db) -> tuple[Room, User, list[User]]:
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


class TestVotingFlow:
    @pytest.mark.asyncio
    async def test_multiple_survivors_transition_to_one_on_one(self, client, db):
        room, challenger, audience = _setup_voting_scenario(db)

        # 3 YES, 2 NO
        choices = [VoteChoice.YES, VoteChoice.NO, VoteChoice.YES, VoteChoice.NO, VoteChoice.YES]
        for user, choice in zip(audience, choices):
            resp = client.post(
                f"/rooms/{room.id}/vote",
                json={"user_id": user.id, "vote": choice.value},
            )
            assert resp.status_code == 201

        db.refresh(room)
        assert room.state == RoomState.ONE_ON_ONE

        # Check participants
        p0 = db.get(RoomParticipant, (room.id, audience[0].id))
        p1 = db.get(RoomParticipant, (room.id, audience[1].id))
        assert p0.status == ParticipantStatus.ACTIVE
        assert p0.left_at is None

        assert p1.status == ParticipantStatus.ELIMINATED
        assert p1.left_at is not None

        # Check user states
        u0 = db.get(User, audience[0].id)
        u1 = db.get(User, audience[1].id)
        assert u0.state == UserState.IN_GAME
        assert u1.state == UserState.QUEUED
        assert u1.queued_at is not None

    @pytest.mark.asyncio
    async def test_single_survivor_transitions_to_final(self, client, db):
        room, challenger, audience = _setup_voting_scenario(db)

        # 1 YES, 4 NO
        choices = [VoteChoice.YES, VoteChoice.NO, VoteChoice.NO, VoteChoice.NO, VoteChoice.NO]
        for user, choice in zip(audience, choices):
            client.post(
                f"/rooms/{room.id}/vote",
                json={"user_id": user.id, "vote": choice.value},
            )

        db.refresh(room)
        assert room.state == RoomState.ONE_ON_ONE

    @pytest.mark.asyncio
    async def test_zero_survivors_transitions_to_completed(self, client, db):
        room, challenger, audience = _setup_voting_scenario(db)

        # 5 NO
        for user in audience:
            client.post(
                f"/rooms/{room.id}/vote",
                json={"user_id": user.id, "vote": "no"},
            )

        db.refresh(room)
        assert room.state == RoomState.COMPLETED

    @pytest.mark.asyncio
    async def test_mandatory_voting_waits_for_last_vote(self, client, db):
        room, challenger, audience = _setup_voting_scenario(db)

        # Submit 4/5 votes
        for user in audience[:4]:
            client.post(
                f"/rooms/{room.id}/vote",
                json={"user_id": user.id, "vote": "yes"},
            )

        db.refresh(room)
        assert room.state == RoomState.VOTING

        # Check voting status API
        status_resp = client.get(f"/rooms/{room.id}/voting?user_id={audience[4].id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["total_voters"] == 5
        assert data["votes_submitted"] == 4
        assert data["votes_remaining"] == 1
        assert data["has_voted"] is False

        # Submit final 5th vote
        client.post(
            f"/rooms/{room.id}/vote",
            json={"user_id": audience[4].id, "vote": "yes"},
        )

        db.refresh(room)
        assert room.state == RoomState.ONE_ON_ONE
