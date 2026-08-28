"""
WebSocketManager — in-memory WebSocket connection registry.

Active connections are stored in memory only. The database remains the
source of truth for all persistent state.  On server restart, connections
are lost (expected for a single-process event application).
"""

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Type alias for clarity
_RoomId = int
_UserId = int


class WebSocketManager:
    """Manages in-memory WebSocket connections grouped by room."""

    def __init__(self) -> None:
        # { room_id: { user_id: WebSocket } }
        self._connections: dict[_RoomId, dict[_UserId, WebSocket]] = defaultdict(dict)

    def connect(self, room_id: _RoomId, user_id: _UserId, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user in a room."""
        self._connections[room_id][user_id] = websocket
        logger.info("WS connected  room=%s user=%s", room_id, user_id)

    def disconnect(self, room_id: _RoomId, user_id: _UserId) -> None:
        """Remove a WebSocket connection.  Safe to call even if not connected."""
        room_conns = self._connections.get(room_id)
        if room_conns and user_id in room_conns:
            del room_conns[user_id]
            logger.info("WS disconnected  room=%s user=%s", room_id, user_id)
        # Clean up empty room entries to avoid unbounded memory growth.
        if room_conns is not None and not room_conns:
            del self._connections[room_id]

    async def send_to_user(
        self, room_id: _RoomId, user_id: _UserId, message: dict
    ) -> None:
        """Send a JSON message to a single user in a room."""
        room_conns = self._connections.get(room_id, {})
        ws = room_conns.get(user_id)
        if ws is not None:
            await ws.send_json(message)
        else:
            logger.warning(
                "send_to_user: no connection  room=%s user=%s", room_id, user_id
            )

    async def broadcast(self, room_id: _RoomId, message: dict) -> None:
        """Send a JSON message to every connected user in a room."""
        room_conns = self._connections.get(room_id, {})
        for user_id, ws in list(room_conns.items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception(
                    "broadcast failed  room=%s user=%s", room_id, user_id
                )


# Single shared instance — import this in route handlers.
ws_manager = WebSocketManager()
