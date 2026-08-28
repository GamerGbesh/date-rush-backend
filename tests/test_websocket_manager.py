from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.websocket_manager import WebSocketManager


@pytest.fixture()
def wm():
    return WebSocketManager()


def _mock_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


class TestConnect:
    def test_connect_stores_websocket(self, wm):
        ws = _mock_ws()
        wm.connect(room_id=1, user_id=10, websocket=ws)
        assert wm._connections[1][10] is ws

    def test_multiple_users_same_room(self, wm):
        ws1, ws2 = _mock_ws(), _mock_ws()
        wm.connect(1, 10, ws1)
        wm.connect(1, 20, ws2)
        assert len(wm._connections[1]) == 2


class TestDisconnect:
    def test_disconnect_removes_websocket(self, wm):
        ws = _mock_ws()
        wm.connect(1, 10, ws)
        wm.disconnect(1, 10)
        assert 10 not in wm._connections.get(1, {})

    def test_disconnect_cleans_empty_room(self, wm):
        ws = _mock_ws()
        wm.connect(1, 10, ws)
        wm.disconnect(1, 10)
        assert 1 not in wm._connections

    def test_disconnect_nonexistent_is_safe(self, wm):
        # Should not raise
        wm.disconnect(999, 999)


class TestSendToUser:
    @pytest.mark.asyncio
    async def test_sends_message_to_correct_user(self, wm):
        ws = _mock_ws()
        wm.connect(1, 10, ws)
        await wm.send_to_user(1, 10, {"event": "test"})
        ws.send_json.assert_awaited_once_with({"event": "test"})

    @pytest.mark.asyncio
    async def test_no_error_if_user_not_connected(self, wm):
        # Should log a warning but not raise
        await wm.send_to_user(1, 99, {"event": "test"})


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcasts_to_all_users_in_room(self, wm):
        ws1, ws2 = _mock_ws(), _mock_ws()
        wm.connect(1, 10, ws1)
        wm.connect(1, 20, ws2)
        await wm.broadcast(1, {"event": "start"})
        ws1.send_json.assert_awaited_once_with({"event": "start"})
        ws2.send_json.assert_awaited_once_with({"event": "start"})

    @pytest.mark.asyncio
    async def test_broadcast_empty_room_is_safe(self, wm):
        await wm.broadcast(999, {"event": "noop"})
