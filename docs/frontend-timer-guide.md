# Date Rush — Frontend Timer Integration Guide

This guide provides frontend engineers with the exact specifications, data models, state management patterns, and production-ready code examples for implementing countdown timers across all phases of Date Rush.

---

## 1. Core Principles for Frontend Timers

1. **Backend is Authoritative**: The backend owns timer lifecycle, duration, and expiration actions (e.g., auto-submitting votes, auto-filling `[No Response]`, or eliminating inactive participants).
2. **Single-Fetch Initialization (No Polling)**:
   - On page load, component mount, or browser refresh, the frontend queries `GET /rooms/{room_id}/timer` **once**.
   - The frontend calculates the remaining seconds from the returned `expires_at` timestamp and runs the countdown clock locally.
   - **Do NOT poll the timer endpoint repeatedly.**
3. **Timestamp-Based (Drift-Free) Countdown**:
   - Do **not** rely solely on decrementing an integer with `setInterval(..., 1000)` because browser background tab throttling will cause time drift.
   - Always calculate:
     $$\text{remainingSeconds} = \max\left(0, \frac{\text{Date.parse}(\text{expires\_at}) - \text{Date.now}()}{1000}\right)$$
4. **WebSocket State Transitions as Triggers**:
   - When the backend finishes a timer countdown and transitions the room to the next stage, it broadcasts a WebSocket event (`room_state_changed`, `voting_started`, `one_on_one_started`, `one_on_one_completed`, etc.).
   - When the frontend receives these WebSocket events, it updates its UI state and re-fetches `GET /rooms/{room_id}/timer` to sync the timer for the new phase.
5. **Zero Seconds Handling**:
   - When the frontend countdown hits `00:00`, freeze the clock and display a status message (e.g. *"Time's up! Processing..."*) until the backend WebSocket transition arrives.

---

## 2. Timer Backend API Specification

### `GET /rooms/{room_id}/timer`

Retrieves the current countdown status and remaining duration for a room.

#### Request
```http
GET /rooms/12/timer HTTP/1.1
Host: api.daterush.example.com
```

#### Response: Active Timer (`200 OK`)
```json
{
  "room_id": 12,
  "active": true,
  "timer_type": "questioning",
  "duration_seconds": 480.0,
  "started_at": "2026-08-29T19:30:00.000000Z",
  "expires_at": "2026-08-29T19:38:00.000000Z",
  "remaining_seconds": 412.35,
  "session_id": null,
  "round": 1
}
```

#### Response: No Active Timer (`200 OK`)
```json
{
  "room_id": 12,
  "active": false,
  "timer_type": null,
  "duration_seconds": null,
  "started_at": null,
  "expires_at": null,
  "remaining_seconds": null,
  "session_id": null,
  "round": null
}
```

### Data Field Reference

| Field | Type | Description |
| :--- | :--- | :--- |
| `room_id` | `integer` | ID of the current room. |
| `active` | `boolean` | `true` if a phase timer is currently running, `false` otherwise. |
| `timer_type` | `string \| null` | Phase type: `"questioning"`, `"voting"`, `"one_on_one_question"`, `"one_on_one_answer"`, `"one_on_one_vote"`, `"final_selection"`. |
| `duration_seconds` | `number \| null` | Total duration allotted for this phase (in seconds). |
| `started_at` | `string \| null` | ISO 8601 UTC timestamp when timer began. |
| `expires_at` | `string \| null` | ISO 8601 UTC timestamp when timer will expire. |
| `remaining_seconds`| `number \| null` | Floating-point remaining seconds calculated by server at response time. |
| `session_id` | `integer \| null` | Specific 1-on-1 session ID (if in `"one_on_one_*"` phase). |
| `round` | `integer \| null` | Question or voting round number (if applicable). |

---

## 3. Game Phases & Timer Reference Table

| Phase (`timer_type`) | Default Time | Who is Acting | UI Component Context | Behavior on Expiry |
| :--- | :--- | :--- | :--- | :--- |
| `questioning` | 8 min (480s) | Challenger | Public Room: Challenger answering 3 questions | 0 answers: Re-queues all with error.<br>1-2 answers: Fills `[No Response]` & advances to Voting. |
| `voting` | 30s | Audience | Public Room: Audience voting YES/NO | Auto-finalizes votes; non-voters eliminated. |
| `one_on_one_question` | 1 min (60s) | Audience Member | 1-on-1 Screen: Audience submitting private question | Audience member eliminated & next session starts. |
| `one_on_one_answer` | 1 min (60s) | Challenger | 1-on-1 Screen: Challenger answering private question | Auto-fills `[No Response]` and advances to vote. |
| `one_on_one_vote` | 30s | Audience Member | 1-on-1 Screen: Audience submitting private YES/NO vote | Auto-submits `NO` vote; audience member eliminated. |
| `final_selection` | 1 min (60s) | Challenger | Finalist Selection Screen | Auto-selects first finalist candidate. |

---

## 4. Frontend State & Component Implementation

### React / TypeScript Implementation

#### 1. Custom Hook: `useRoomTimer.ts`

```typescript
import { useEffect, useState, useRef, useCallback } from 'react';

export interface TimerStatus {
  room_id: number;
  active: boolean;
  timer_type: string | null;
  duration_seconds: number | null;
  started_at: string | null;
  expires_at: string | null;
  remaining_seconds: number | null;
  session_id?: number | null;
  round?: number | null;
}

export function useRoomTimer(roomId: number, apiBaseUrl: string) {
  const [timerData, setTimerData] = useState<TimerStatus | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);
  const [isExpired, setIsExpired] = useState<boolean>(false);
  const animationFrameRef = useRef<number | null>(null);

  // Fetch initial timer data from backend (called on mount, refresh, or stage change)
  const syncTimer = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/rooms/${roomId}/timer`);
      if (!res.ok) throw new Error('Failed to fetch timer');
      const data: TimerStatus = await res.json();
      setTimerData(data);

      if (data.active && data.expires_at) {
        const targetTime = new Date(data.expires_at).getTime();
        const now = Date.now();
        const diff = Math.max(0, (targetTime - now) / 1000);
        setRemainingSeconds(diff);
        setIsExpired(diff <= 0);
      } else {
        setRemainingSeconds(0);
        setIsExpired(false);
      }
    } catch (err) {
      console.error('Error syncing timer:', err);
    }
  }, [roomId, apiBaseUrl]);

  // Sync on mount or when roomId changes
  useEffect(() => {
    syncTimer();
  }, [syncTimer]);

  // Run drift-free countdown clock locally based on target expires_at timestamp
  useEffect(() => {
    if (!timerData?.active || !timerData.expires_at) {
      return;
    }

    const targetTime = new Date(timerData.expires_at).getTime();

    const tick = () => {
      const now = Date.now();
      const diff = (targetTime - now) / 1000;

      if (diff <= 0) {
        setRemainingSeconds(0);
        setIsExpired(true);
      } else {
        setRemainingSeconds(diff);
        setIsExpired(false);
        animationFrameRef.current = requestAnimationFrame(tick);
      }
    };

    animationFrameRef.current = requestAnimationFrame(tick);

    return () => {
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [timerData?.active, timerData?.expires_at]);

  // Format MM:SS helper
  const formattedTime = (() => {
    const totalSecs = Math.ceil(remainingSeconds);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  })();

  const progressPercentage = (() => {
    if (!timerData?.duration_seconds || timerData.duration_seconds <= 0) return 0;
    return Math.min(100, Math.max(0, (remainingSeconds / timerData.duration_seconds) * 100));
  })();

  return {
    timerData,
    remainingSeconds,
    formattedTime,
    progressPercentage,
    isExpired,
    syncTimer, // Call when WebSocket pushes stage transition
  };
}
```

---

#### 2. React UI Component: `CountdownTimer.tsx`

```tsx
import React from 'react';
import { useRoomTimer } from './useRoomTimer';

interface CountdownTimerProps {
  roomId: number;
  apiBaseUrl: string;
  onTimeout?: () => void;
}

export const CountdownTimer: React.FC<CountdownTimerProps> = ({
  roomId,
  apiBaseUrl,
  onTimeout,
}) => {
  const { timerData, formattedTime, progressPercentage, isExpired } = useRoomTimer(
    roomId,
    apiBaseUrl
  );

  if (!timerData?.active) {
    return null; // No active countdown in current room state
  }

  const isUrgent = (timerData.remaining_seconds ?? 0) <= 10;

  return (
    <div className="flex flex-col items-center gap-1 p-3 bg-gray-900/80 rounded-xl border border-gray-800 shadow-md">
      <div className="flex items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">
          {timerData.timer_type?.replace(/_/g, ' ')}
        </span>
      </div>

      <div className={`text-3xl font-mono font-bold tracking-tight ${isUrgent ? 'text-red-500 animate-pulse' : 'text-white'}`}>
        {formattedTime}
      </div>

      {/* Visual Progress Bar */}
      <div className="w-full bg-gray-700 h-1.5 rounded-full overflow-hidden mt-1">
        <div
          className={`h-full transition-all duration-200 ${isUrgent ? 'bg-red-500' : 'bg-pink-500'}`}
          style={{ width: `${progressPercentage}%` }}
        />
      </div>

      {isExpired && (
        <span className="text-xs text-yellow-400 italic">Processing timeout...</span>
      )}
    </div>
  );
};
```

---

### Vue 3 / Pinia Implementation

#### 1. Composable: `useRoomTimer.ts`

```typescript
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';

export function useRoomTimer(roomId: number, apiBaseUrl: string) {
  const timerData = ref<any>(null);
  const remainingSeconds = ref(0);
  const isExpired = ref(false);
  let timerInterval: number | null = null;

  async function syncTimer() {
    try {
      const res = await fetch(`${apiBaseUrl}/rooms/${roomId}/timer`);
      if (res.ok) {
        timerData.value = await res.json();
      }
    } catch (e) {
      console.error('Failed to sync timer:', e);
    }
  }

  function startLocalCountdown() {
    if (timerInterval) clearInterval(timerInterval);

    if (!timerData.value?.active || !timerData.value?.expires_at) {
      remainingSeconds.value = 0;
      isExpired.value = false;
      return;
    }

    const targetTime = new Date(timerData.value.expires_at).getTime();

    const update = () => {
      const now = Date.now();
      const diff = (targetTime - now) / 1000;
      if (diff <= 0) {
        remainingSeconds.value = 0;
        isExpired.value = true;
        if (timerInterval) clearInterval(timerInterval);
      } else {
        remainingSeconds.value = diff;
        isExpired.value = false;
      }
    };

    update();
    timerInterval = window.setInterval(update, 100);
  }

  watch(() => timerData.value, startLocalCountdown, { deep: true });

  onMounted(() => {
    syncTimer();
  });

  onUnmounted(() => {
    if (timerInterval) clearInterval(timerInterval);
  });

  const formattedTime = computed(() => {
    const total = Math.ceil(remainingSeconds.value);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  });

  return {
    timerData,
    remainingSeconds,
    formattedTime,
    isExpired,
    syncTimer,
  };
}
```

---

## 5. Integrating with WebSockets

When WebSocket messages arrive, update the UI and trigger `syncTimer()`:

```typescript
// Inside your WebSocket event handler
websocket.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'room_state_changed':
    case 'question_started':
    case 'voting_started':
    case 'one_on_one_started':
    case 'one_on_one_completed':
    case 'final_selection_started':
      // Room entered a new phase: Re-sync timer to get new duration & expiry
      syncTimer();
      break;

    case 'questioning_timeout':
      // Show questioning timeout error modal/banner
      showNotification('Challenger timed out. Returning to queue...', 'error');
      break;

    case 'eliminated':
      // User was eliminated due to timeout or vote
      showNotification('You have been eliminated and returned to the queue.', 'warning');
      break;
  }
};
```

---

## 6. Summary Checklist for Frontend Developers

- [ ] Query `GET /rooms/{room_id}/timer` on component load and browser refresh.
- [ ] Calculate remaining seconds from `Date.parse(expires_at) - Date.now()` (avoids background tab lag).
- [ ] When countdown reaches `00:00`, display *"Waiting for server..."* rather than assuming an outcome.
- [ ] Call `syncTimer()` whenever WebSocket pushes stage changes (`question_started`, `voting_started`, `one_on_one_started`, `final_selection_started`).
- [ ] Do **not** poll the timer endpoint.
