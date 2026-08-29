import pytest

from app.enums import Gender, PlayerRole, RoomState, UserState, VoteChoice
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.services.queue_manager import queue_manager
from app.services.voting_service import voting_service


class TestQueueReentryAndRoomTriggering:
    @pytest.mark.asyncio
    async def test_eliminated_users_remain_waiting_until_rejoining_queue(self, db):
        challenger = User(name="Ama", gender=Gender.FEMALE, state=UserState.IN_GAME)
        aud = User(name="Kwame", gender=Gender.MALE, state=UserState.IN_GAME)
        db.add_all([challenger, aud])
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
        db.add(RoomParticipant(room_id=room.id, user_id=aud.id, role=PlayerRole.AUDIENCE))
        db.commit()

        # Submit NO vote -> eliminated into WAITING
        await voting_service.submit_vote(db, room.id, aud.id, VoteChoice.NO)

        db.refresh(aud)
        assert aud.state == UserState.WAITING

        # User explicitly clicks return to queue
        queue_manager.add(db, aud)
        db.refresh(aud)
        assert aud.state == UserState.QUEUED
        assert aud.queued_at is not None

    @pytest.mark.asyncio
    async def test_eliminated_user_rejoining_queue_triggers_new_room_when_threshold_reached(self, db):
        # 1. Existing queue: 4 males and 1 female waiting in QUEUED
        for i in range(4):
            m = User(name=f"Queued_M{i}", gender=Gender.MALE)
            db.add(m)
            db.commit()
            queue_manager.add(db, m)

        f = User(name="Queued_F0", gender=Gender.FEMALE)
        db.add(f)
        db.commit()
        queue_manager.add(db, f)

        assert queue_manager.get_size(db, Gender.MALE) == 4
        assert queue_manager.get_size(db, Gender.FEMALE) == 1

        # 2. Active room currently in VOTING with 1 challenger and 1 audience member
        challenger = User(name="Active_Challenger", gender=Gender.FEMALE, state=UserState.IN_GAME)
        active_aud = User(name="Active_Audience", gender=Gender.MALE, state=UserState.IN_GAME)
        db.add_all([challenger, active_aud])
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
        db.add(RoomParticipant(room_id=room.id, user_id=active_aud.id, role=PlayerRole.AUDIENCE))
        db.commit()

        # 3. Active audience member votes NO -> eliminated into WAITING
        await voting_service.submit_vote(db, room.id, active_aud.id, VoteChoice.NO)
        db.refresh(active_aud)
        assert active_aud.state == UserState.WAITING

        # 4. User explicitly rejoins queue -> triggers room creation!
        queue_manager.add(db, active_aud)
        queue_manager.try_create_rooms(db)

        # 5. Verify a new room was created
        new_rooms = db.query(Room).where(Room.id != room.id).all()
        assert len(new_rooms) == 1
        new_room = new_rooms[0]
        assert new_room.state == RoomState.READY
        assert new_room.challenger_id == f.id
        assert len(new_room.participants) == 6  # 1 challenger + 5 audience
