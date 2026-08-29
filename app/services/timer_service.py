"""
TimerService — standalone countdown timer engine for all game phases.

Manages background asyncio countdown tasks for:
- Public Questioning (challenger answers 3 questions)
- Public Voting (audience YES/NO voting)
- One-on-One Questions (audience asks private question)
- One-on-One Answers (challenger answers private question)
- One-on-One Voting (audience private YES/NO vote)
- Final Selection (challenger chooses winning finalist)

Provides timer inspection for frontend countdown synchronization on page load / refresh.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


@dataclass
class ActiveTimer:
    room_id: int
    timer_type: str
    duration_seconds: float
    started_at: datetime
    expires_at: datetime
    session_id: int | None
    round: int | None
    task: asyncio.Task


class TimerService:
    """Standalone timer service managing game phase countdowns."""

    def __init__(self) -> None:
        self._timers: dict[int, ActiveTimer] = {}

    def start_timer(
        self,
        room_id: int,
        timer_type: str,
        duration_seconds: float,
        on_timeout: Callable[[], Coroutine[Any, Any, None] | None],
        session_id: int | None = None,
        round: int | None = None,
    ) -> ActiveTimer:
        """
        Start a new countdown timer for a room phase.
        Cancels any existing timer for this room before starting.
        """
        self.cancel_timer(room_id)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=duration_seconds)

        task = asyncio.create_task(
            self._run_timer(
                room_id=room_id,
                timer_type=timer_type,
                duration_seconds=duration_seconds,
                on_timeout=on_timeout,
            )
        )

        active_timer = ActiveTimer(
            room_id=room_id,
            timer_type=timer_type,
            duration_seconds=float(duration_seconds),
            started_at=now,
            expires_at=expires_at,
            session_id=session_id,
            round=round,
            task=task,
        )
        self._timers[room_id] = active_timer

        logger.info(
            "Timer started: room=%d, type=%s, duration=%.1fs, expires_at=%s",
            room_id,
            timer_type,
            duration_seconds,
            expires_at.isoformat(),
        )

        return active_timer

    def cancel_timer(self, room_id: int, timer_type: str | None = None) -> bool:
        """
        Cancel any active timer for this room.
        If timer_type is specified, only cancel if the timer matches that type.
        """
        timer = self._timers.get(room_id)
        if timer:
            if timer_type is not None and timer.timer_type != timer_type:
                return False
            self._timers.pop(room_id, None)
            if not timer.task.done():
                timer.task.cancel()
                logger.info("Timer cancelled: room=%d, type=%s", room_id, timer.timer_type)
            return True
        return False

    def get_timer_info(self, room_id: int) -> dict:
        """
        Get current countdown status for a room.
        Used by API endpoints and WebSocket reconnection handlers to initialize frontend clock.
        """
        timer = self._timers.get(room_id)
        if timer and not timer.task.done():
            now = datetime.now(timezone.utc)
            remaining = max(0.0, (timer.expires_at - now).total_seconds())
            return {
                "room_id": room_id,
                "active": True,
                "timer_type": timer.timer_type,
                "duration_seconds": timer.duration_seconds,
                "started_at": timer.started_at,
                "expires_at": timer.expires_at,
                "remaining_seconds": remaining,
                "session_id": timer.session_id,
                "round": timer.round,
            }

        return {
            "room_id": room_id,
            "active": False,
            "timer_type": None,
            "duration_seconds": None,
            "started_at": None,
            "expires_at": None,
            "remaining_seconds": None,
            "session_id": None,
            "round": None,
        }

    async def _run_timer(
        self,
        room_id: int,
        timer_type: str,
        duration_seconds: float,
        on_timeout: Callable[[], Coroutine[Any, Any, None] | None],
    ) -> None:
        """Wait for duration and trigger timeout callback if not cancelled."""
        try:
            await asyncio.sleep(duration_seconds)
            logger.info("Timer expired: room=%d, type=%s", room_id, timer_type)
            # Remove timer record
            self._timers.pop(room_id, None)

            # Invoke callback
            res = on_timeout()
            if asyncio.iscoroutine(res):
                await res
        except asyncio.CancelledError:
            logger.debug("Timer task cancelled: room=%d, type=%s", room_id, timer_type)
        except Exception:
            logger.exception("Exception occurred during timer timeout: room=%d, type=%s", room_id, timer_type)
        finally:
            timer = self._timers.get(room_id)
            if timer and timer.task == asyncio.current_task():
                self._timers.pop(room_id, None)

    async def _broadcast_timer_started(
        self,
        room_id: int,
        timer_type: str,
        duration_seconds: float,
        started_at: datetime,
        expires_at: datetime,
        session_id: int | None,
        round: int | None,
    ) -> None:
        """Broadcast timer sync payload to room participants."""
        payload = {
            "type": "timer_started",
            "room_id": room_id,
            "timer_type": timer_type,
            "duration_seconds": duration_seconds,
            "started_at": started_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "remaining_seconds": duration_seconds,
            "session_id": session_id,
            "round": round,
        }
        await ws_manager.broadcast(room_id, payload)


timer_service = TimerService()
