"""
WebSocketManager — in-memory WebSocket connection registry for public room channels
and private 1-on-1 session channels.

Active connections are stored in memory only. The database remains the
source of truth for all persistent state. On server restart, connections
are lost (expected for a single-process event application).
"""

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Type aliases for clarity
_RoomId = int
_SessionId = int
_UserId = int


class WebSocketManager:
    """Manages in-memory WebSocket connections grouped by room and private session."""

    def __init__(self) -> None:
        # { room_id: { user_id: WebSocket } }
        self._connections: dict[_RoomId, dict[_UserId, WebSocket]] = defaultdict(dict)
        # { session_id: { user_id: WebSocket } }
        self._session_connections: dict[_SessionId, dict[_UserId, WebSocket]] = defaultdict(dict)
        # { match_room_id: { user_id: WebSocket } }
        self._match_room_connections: dict[int, dict[_UserId, WebSocket]] = defaultdict(dict)

    # -------------------------------------------------------------------------
    # Public room channels
    # -------------------------------------------------------------------------

    def connect(self, room_id: _RoomId, user_id: _UserId, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user in a room."""
        self._connections[room_id][user_id] = websocket
        logger.info("WS connected  room=%s user=%s", room_id, user_id)

    def disconnect(self, room_id: _RoomId, user_id: _UserId) -> None:
        """Remove a WebSocket connection. Safe to call even if not connected."""
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

    # -------------------------------------------------------------------------
    # Private 1-on-1 session channels
    # -------------------------------------------------------------------------

    def connect_session(
        self, session_id: _SessionId, user_id: _UserId, websocket: WebSocket
    ) -> None:
        """Register a new WebSocket connection for a user in a private 1-on-1 session."""
        self._session_connections[session_id][user_id] = websocket
        logger.info("Private WS connected  session=%s user=%s", session_id, user_id)

    def disconnect_session(self, session_id: _SessionId, user_id: _UserId) -> None:
        """Remove a private session WebSocket connection."""
        session_conns = self._session_connections.get(session_id)
        if session_conns and user_id in session_conns:
            del session_conns[user_id]
            logger.info("Private WS disconnected  session=%s user=%s", session_id, user_id)
        if session_conns is not None and not session_conns:
            del self._session_connections[session_id]

    async def send_to_session_user(
        self, session_id: _SessionId, user_id: _UserId, message: dict
    ) -> None:
        """Send a JSON message to a single user in a private session."""
        session_conns = self._session_connections.get(session_id, {})
        ws = session_conns.get(user_id)
        if ws is not None:
            await ws.send_json(message)
        else:
            logger.warning(
                "send_to_session_user: no connection  session=%s user=%s",
                session_id,
                user_id,
            )

    async def broadcast_session(self, session_id: _SessionId, message: dict) -> None:
        """Send a JSON message to both participants in a private 1-on-1 session."""
        session_conns = self._session_connections.get(session_id, {})
        for user_id, ws in list(session_conns.items()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception(
                    "session broadcast failed  session=%s user=%s",
                    session_id,
                    user_id,
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


# Single shared instance — import this in route handlers.
ws_manager = WebSocketManager()

