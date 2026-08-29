"""
WebSocketManager — in-memory WebSocket connection registry for public room channels
and private 1-on-1 session channels.

Active connections are stored in memory only. The database remains the
source of truth for all persistent state. On server restart, connections
are lost (expected for a single-process event application).
"""

from collections.abc import Iterable
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Type aliases for clarity
_RoomId = int
_UserId = int


class WebSocketManager:
    """Manages in-memory WebSocket connections grouped by game room, match room, and queue."""

    def __init__(self) -> None:
        # { room_id: { user_id: set[WebSocket] } }
        self._connections: dict[_RoomId, dict[_UserId, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )
        # { match_room_id: { user_id: WebSocket } }
        self._match_room_connections: dict[int, dict[_UserId, WebSocket]] = defaultdict(dict)
        # { user_id: WebSocket }
        self._queue_connections: dict[_UserId, WebSocket] = {}

    # -------------------------------------------------------------------------
    # Game Room channels (Multiplexed Transport)
    # -------------------------------------------------------------------------

    def connect(self, room_id: _RoomId, user_id: _UserId, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user in a room."""
        self._connections[room_id][user_id].add(websocket)
        logger.info("WS connected  room=%s user=%s", room_id, user_id)

    def disconnect(
        self, room_id: _RoomId, user_id: _UserId, websocket: WebSocket | None = None
    ) -> None:
        """Remove a WebSocket connection. Safe to call even if not connected."""
        room_conns = self._connections.get(room_id)
        if room_conns and user_id in room_conns:
            if websocket is not None:
                room_conns[user_id].discard(websocket)
            if websocket is None or not room_conns[user_id]:
                room_conns.pop(user_id, None)
            logger.info("WS disconnected  room=%s user=%s", room_id, user_id)
        # Clean up empty room entries to avoid unbounded memory growth.
        if room_conns is not None and not room_conns:
            self._connections.pop(room_id, None)

    async def send_to_user(
        self, room_id: _RoomId, user_id: _UserId, message: dict
    ) -> None:
        """Send a JSON message to a single user in a room across all their active connections."""
        room_conns = self._connections.get(room_id, {})
        user_sockets = list(room_conns.get(user_id, set()))
        msg_type = message.get("type", "unknown")
        if user_sockets:
            logger.debug(
                "WS send_to_user  room=%s user=%s type=%s socket_count=%d",
                room_id,
                user_id,
                msg_type,
                len(user_sockets),
            )
            for ws in user_sockets:
                try:
                    await ws.send_json(message)
                except Exception:
                    logger.exception(
                        "send_to_user failed  room=%s user=%s type=%s",
                        room_id,
                        user_id,
                        msg_type,
                    )
        else:
            logger.debug(
                "send_to_user: no active connection  room=%s user=%s type=%s",
                room_id,
                user_id,
                msg_type,
            )

    async def send_to_users(
        self, room_id: _RoomId, user_ids: Iterable[_UserId], message: dict
    ) -> None:
        """Send a JSON message only to the specified set/iterable of users in a room."""
        user_ids_list = list(user_ids)
        logger.debug(
            "WS send_to_users  room=%s targets=%s type=%s",
            room_id,
            user_ids_list,
            message.get("type", "unknown"),
        )
        for user_id in user_ids_list:
            await self.send_to_user(room_id, user_id, message)

    async def broadcast(self, room_id: _RoomId, message: dict) -> None:
        """Send a JSON message to every connected user in a room."""
        room_conns = self._connections.get(room_id, {})
        msg_type = message.get("type", "unknown")
        logger.debug(
            "WS broadcast  room=%s total_users=%d type=%s",
            room_id,
            len(room_conns),
            msg_type,
        )
        for user_id, user_sockets in list(room_conns.items()):
            for ws in list(user_sockets):
                try:
                    await ws.send_json(message)
                except Exception:
                    logger.exception(
                        "broadcast failed  room=%s user=%s type=%s",
                        room_id,
                        user_id,
                        msg_type,
                    )

    # -------------------------------------------------------------------------
    # Private match room channels
    # -------------------------------------------------------------------------

    def connect_match_room(
        self, match_room_id: int, user_id: _UserId, websocket: WebSocket
    ) -> None:
        """Register a new WebSocket connection for a user in a private match room."""
        self._match_room_connections[match_room_id][user_id] = websocket
        logger.info("Match room WS connected  match_room=%s user=%s", match_room_id, user_id)

    def disconnect_match_room(self, match_room_id: int, user_id: _UserId) -> None:
        """Remove a private match room WebSocket connection."""
        mr_conns = self._match_room_connections.get(match_room_id)
        if mr_conns and user_id in mr_conns:
            del mr_conns[user_id]
            logger.info("Match room WS disconnected  match_room=%s user=%s", match_room_id, user_id)
        if mr_conns is not None and not mr_conns:
            del self._match_room_connections[match_room_id]

    async def send_to_match_room_user(
        self, match_room_id: int, user_id: _UserId, message: dict
    ) -> None:
        """Send a JSON message to a single user in a private match room."""
        mr_conns = self._match_room_connections.get(match_room_id, {})
        ws = mr_conns.get(user_id)
        if ws is not None:
            await ws.send_json(message)
        else:
            logger.warning(
                "send_to_match_room_user: no connection  match_room=%s user=%s",
                match_room_id,
                user_id,
            )

    async def broadcast_match_room(self, match_room_id: int, message: dict) -> None:
        """Send a JSON message to both participants in a private match room."""
        mr_conns = self._match_room_connections.get(match_room_id, {})
        for user_id, ws in list(mr_conns.items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception(
                    "match room broadcast failed  match_room=%s user=%s",
                    match_room_id,
                    user_id,
                )

    # -------------------------------------------------------------------------
    # Queue waiting room channel
    # -------------------------------------------------------------------------

    def connect_queue(self, user_id: _UserId, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user in the waiting queue."""
        self._queue_connections[user_id] = websocket
        logger.info("Queue WS connected  user=%s total_queued_sockets=%d", user_id, len(self._queue_connections))

    def disconnect_queue(self, user_id: _UserId) -> None:
        """Remove a user from the active queue WebSocket registry."""
        if user_id in self._queue_connections:
            del self._queue_connections[user_id]
            logger.info("Queue WS disconnected  user=%s remaining_queued_sockets=%d", user_id, len(self._queue_connections))

    def is_user_in_queue(self, user_id: _UserId) -> bool:
        """Check if user has an active queue WebSocket connection."""
        return user_id in self._queue_connections

    def get_connected_queue_user_ids(self) -> set[_UserId]:
        """Return set of user IDs with active queue WebSocket connections."""
        return set(self._queue_connections.keys())

    async def send_to_queue_user(self, user_id: _UserId, message: dict) -> None:
        """Send a JSON message to a single user in the waiting queue."""
        ws = self._queue_connections.get(user_id)
        if ws is not None:
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("send_to_queue_user failed user=%s", user_id)
        else:
            logger.warning("send_to_queue_user: no connection user=%s", user_id)

    async def broadcast_queue(self, message: dict) -> None:
        """Send a JSON message to all connected users in the waiting queue."""
        for user_id, ws in list(self._queue_connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("queue broadcast failed user=%s", user_id)


# Single shared instance — import this in route handlers.
ws_manager = WebSocketManager()

