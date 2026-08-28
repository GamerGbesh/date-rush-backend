"""
RoomStateService — room state machine and transition management.

Validates state transitions, records transition audit history,
updates the room round when appropriate, and broadcasts state change events
to all connected participants via WebSocketManager.
"""

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import PlayerRole, RoomState
from app.exceptions import InvalidRoomTransitionError, RoomNotFoundError
from app.models.room import Room
from app.models.room_state_history import RoomStateHistory
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Explicit valid state transitions
VALID_TRANSITIONS: dict[RoomState, set[RoomState]] = {
    RoomState.READY: {RoomState.INTRO},
    RoomState.INTRO: {RoomState.QUESTIONING},
    RoomState.QUESTIONING: {RoomState.VOTING},
    RoomState.VOTING: {RoomState.ELIMINATION},
    RoomState.ELIMINATION: {RoomState.QUESTIONING, RoomState.ONE_ON_ONE, RoomState.FINAL, RoomState.COMPLETED},
    RoomState.ONE_ON_ONE: {RoomState.FINAL},
    RoomState.FINAL: {RoomState.MATCHED},
    RoomState.MATCHED: {RoomState.COMPLETED},
    RoomState.COMPLETED: set(),
    # Retain WAITING -> READY for backwards compatibility if needed
    RoomState.WAITING: {RoomState.READY},
}


class RoomStateService:
    """Manages room state transitions and lifecycle validation."""

    def is_valid_transition(self, current_state: RoomState, target_state: RoomState) -> bool:
        """Check whether a transition between two states is valid."""
        return target_state in VALID_TRANSITIONS.get(current_state, set())

    async def transition(
        self,
        db: Session,
        room_id: int,
        target_state: RoomState,
    ) -> Room:
        """
        Transition a room to a new state.

        1. Fetch room from database.
        2. Validate the requested transition.
        3. Increment room.current_round when entering QUESTIONING.
        4. Record RoomStateHistory.
        5. Persist the state update.
        6. Broadcast room_state_changed event via WebSocket.
        7. Return the updated room.
        """
        room = db.get(Room, room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        current_state = room.state
        if not self.is_valid_transition(current_state, target_state):
            logger.warning(
                "Invalid transition attempted for room %d: %s -> %s",
                room_id,
                current_state,
                target_state,
            )
            from_str = current_state.value if hasattr(current_state, "value") else str(current_state)
            to_str = target_state.value if hasattr(target_state, "value") else str(target_state)
            raise InvalidRoomTransitionError(from_state=from_str, to_state=to_str)

        # Round management: increment round when entering QUESTIONING
        if target_state == RoomState.QUESTIONING:
            room.current_round += 1

        # Record transition history
        history_entry = RoomStateHistory(
            room_id=room.id,
            from_state=current_state,
            to_state=target_state,
        )
        db.add(history_entry)

        # Update room state
        room.state = target_state
        db.commit()
        db.refresh(room)

        logger.info(
            "Room %d transitioned: %s -> %s (round=%d)",
            room.id,
            current_state,
            target_state,
            room.current_round,
        )

        # Broadcast state change event to connected WebSocket clients
        event_payload = {
            "type": "room_state_changed",
            "room_id": room.id,
            "previous_state": current_state.value if hasattr(current_state, "value") else str(current_state),
            "state": target_state.value if hasattr(target_state, "value") else str(target_state),
        }
        await ws_manager.broadcast(room.id, event_payload)

        # When entering QUESTIONING, automatically start the question round
        if target_state == RoomState.QUESTIONING:
            from app.services.questioning_service import questioning_service
            await questioning_service.start_questioning_round(db, room)

        # When entering VOTING, broadcast voting_started event with total voters
        if target_state == RoomState.VOTING:
            active_voters_count = sum(
                1
                for p in room.participants
                if p.left_at is None and p.role == PlayerRole.AUDIENCE
            )
            await ws_manager.broadcast(
                room.id,
                {
                    "type": "voting_started",
                    "room_id": room.id,
                    "total_voters": active_voters_count,
                },
            )

        return room

    def get_history(self, db: Session, room_id: int) -> list[RoomStateHistory]:
        """Fetch audit log history for a room, ordered by creation time."""
        result = db.execute(
            select(RoomStateHistory)
            .where(RoomStateHistory.room_id == room_id)
            .order_by(RoomStateHistory.id.asc())
        )
        return list(result.scalars().all())

    def determine_next_elimination_state(self, db: Session, room: Room) -> RoomState:
        """
        Determine whether ELIMINATION leads to QUESTIONING or FINAL based on
        active audience count.
        """
        active_audience = [
            p
            for p in room.participants
            if p.left_at is None and p.role == PlayerRole.AUDIENCE
        ]
        if len(active_audience) <= 1:
            return RoomState.FINAL
        return RoomState.QUESTIONING


room_state_service = RoomStateService()
