# Date Rush — Frontend Integration Guide

This guide is written for frontend engineers integrating with the Date Rush backend platform. It walks through the end-to-end user lifecycle, provides the recommended UI state machine, details state-recovery mechanisms, and explains error-handling strategies.

---

## 1. Core Principles for Frontend Integration

1. **The Backend is Authoritative**: The backend controls all queues, game room state transitions, eliminations, session activations, and matchmaking. The frontend renders the state and sends user actions.
2. **REST for Actions & Recovery; WebSockets for Real-Time Progression**:
   - Call REST endpoints (`POST /...`) when users perform an explicit action (submit vote, answer question, submit contacts).
   - Listen to WebSockets for real-time live events.
   - Call REST endpoints (`GET /...`) when the app launches, reconnects, or reloads to recover the current UI state.
3. **No Polling Required**: WebSockets automatically push all progression events. Do not poll REST endpoints in a loop.
4. **Opaque Identifiers**: Treat `user_id`, `room_id`, `session_id`, `match_id`, and `match_room_id` as opaque integers.

---

## 2. Recommended Frontend UI State Machine

```text
                  ┌─────────────────┐
                  │  AUTHENTICATE   │
                  │ (Register/Load) │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │     QUEUED      │
                  │ (Waiting Room)  │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │     IN_GAME     │
                  │  (Public Room)  │
                  └────────┬────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
     ┌───────────────┐           ┌───────────────┐
     │  QUESTIONING  │           │    VOTING     │
     └───────┬───────┘           └───────┬───────┘
             │                           │
             └─────────────┬─────────────┘
                           ▼
                  ┌─────────────────┐
                  │   ONE_ON_ONE    │
                  │(Private Session)│
                  └────────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│0 Survivors    │  │1 Survivor     │  │>1 Survivors   │
│COMPLETED      │  │Auto-Match     │  │FINAL_SELECTION│
└───────────────┘  └───────┬───────┘  └───────┬───────┘
                           │                  │
                           └────────┬─────────┘
                                    ▼
                           ┌─────────────────┐
                           │    MATCHED      │
                           │(Match Details)  │
                           └────────┬────────┘
                                    ▼
                           ┌─────────────────┐
                           │CONTACT_EXCHANGE │
                           │ (Match Room)    │
                           └────────┬────────┘
                                    ▼
                           ┌─────────────────┐
                           │    COMPLETED    │
                           │(Terminal State) │
                           └─────────────────┘
```

---

## 3. End-to-End Lifecycle Walkthrough

### Step 1: App Launch & State Recovery
When the app opens or the browser refreshes:
```http
GET /users/me?user_id={user_id}
```
**Response handling:**
- `state: "waiting"` $\rightarrow$ Show join queue screen.
- `state: "queued"` $\rightarrow$ Show queue waiting screen.
- `state: "in_game"` $\rightarrow$ Connect to Public Room WS (`/ws/rooms/{room_id}/users/{user_id}`).
- `state: "matched"` $\rightarrow$ Show match summary / navigate to Match Room.
- `state: "completed"` $\rightarrow$ Show completed event screen with partner contacts if available.

---

### Step 2: Joining the Queue
User registers/joins:
```http
POST /queue/join
Body: {"name": "Ama", "gender": "female"}
```
The backend puts the user in the correct queue based on gender. When enough participants exist (1 challenger + 5 audience members of opposite gender), a room is formed automatically.

---

### Step 3: Public Game Room Experience
1. Connect to Room WebSocket:
   ```text
   WS /ws/rooms/{room_id}/users/{user_id}
   ```
2. **Questioning Phase:**
   - Challenger sees question and input box $\rightarrow$ submits `POST /rooms/{room_id}/answers`.
   - Audience sees question and waits for answer.
   - When challenger answers $\rightarrow$ WS receives `answer_revealed`.
   - Automatically advances across 3 question rounds.
3. **Voting Phase:**
   - WS receives `voting_started`.
   - Audience sees YES / NO buttons $\rightarrow$ submits `POST /rooms/{room_id}/vote`.
   - Room receives `vote_progress` updates.
   - When all vote $\rightarrow$ surviving audience members enter 1-on-1; eliminated audience members receive `eliminated` event and return to queue.

---

### Step 4: One-on-One Private Sessions
Surviving audience members interact with the challenger sequentially:
1. Check session details via `GET /rooms/{room_id}/one-on-one`.
2. Connect to private session channel:
   ```text
   WS /ws/rooms/{room_id}/one-on-one/{session_id}/users/{user_id}
   ```
3. Audience submits question:
   ```http
   POST /rooms/{room_id}/one-on-one/{session_id}/question
   Body: {"user_id": {id}, "text": "..."}
   ```
4. Challenger submits answer:
   ```http
   POST /rooms/{room_id}/one-on-one/{session_id}/answer
   Body: {"user_id": {id}, "text": "..."}
   ```
5. Audience submits private YES / NO vote:
   ```http
   POST /rooms/{room_id}/one-on-one/{session_id}/vote
   Body: {"user_id": {id}, "vote": "yes"}
   ```
6. The backend automatically proceeds to the next session.

---

### Step 5: Final Selection (If Multiple Survivors)
If >1 audience member survived the 1-on-1 phase:
1. WS emits `final_selection_started`.
2. Challenger queries candidate list:
   ```http
   GET /rooms/{room_id}/final-selection?user_id={challenger_id}
   ```
3. Challenger selects one candidate:
   ```http
   POST /rooms/{room_id}/final-selection
   Body: {"user_id": {challenger_id}, "candidate_id": {candidate_id}}
   ```
4. Match and MatchRoom are created. Non-selected finalists automatically return to the queue.

*(Note: If exactly 1 audience member survives 1-on-1, this step is skipped and the match is formed automatically).*

---

### Step 6: Private Match Room & Contact Exchange
1. Fetch match info: `GET /matches/{match_id}?user_id={user_id}`.
2. Connect to Match Room WebSocket:
   ```text
   WS /ws/match-rooms/{match_room_id}/users/{user_id}
   ```
3. User enters WhatsApp, Snapchat, or both:
   ```http
   POST /match-rooms/{match_room_id}/contacts
   Body: {"user_id": {id}, "whatsapp": "+233201234567", "snapchat": null}
   ```
4. While waiting for partner, UI shows "Waiting for partner...".
5. Once partner submits, WS emits `contacts_exchanged` containing partner name and handle(s).
6. WS emits `match_completed`.
7. Users are marked as `COMPLETED` and the experience finishes.

---

## 4. State Recovery Matrix

If the user loses internet connection or refreshes the page at any phase:

| Phase | State Recovery Endpoint |
| :--- | :--- |
| **Global State** | `GET /users/me?user_id={user_id}` |
| **Public Room** | `GET /rooms/{room_id}` |
| **Public Voting** | `GET /rooms/{room_id}/voting?user_id={user_id}` |
| **1-on-1 Sessions** | `GET /rooms/{room_id}/one-on-one` |
| **Final Selection** | `GET /rooms/{room_id}/final-selection?user_id={user_id}` |
| **Match Details** | `GET /matches/{match_id}?user_id={user_id}` |
| **Match Room** | `GET /match-rooms/{match_room_id}?user_id={user_id}` |
| **Contact Status** | `GET /match-rooms/{match_room_id}/contacts?user_id={user_id}` |

---

## 5. Machine-Readable Error Handling

All REST endpoints return standard HTTP error status codes with structured detail messages. Handle common cases:

```typescript
async function submitVote(roomId: number, userId: number, choice: "yes" | "no") {
  try {
    const response = await fetch(`/rooms/${roomId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, vote: choice }),
    });

    if (response.status === 409) {
      // Already voted or voting is no longer active
      const err = await response.json();
      console.warn("Vote rejected:", err.detail);
      // Sync state with server
      await syncVotingState(roomId, userId);
    } else if (response.status === 403) {
      console.error("Unauthorized to vote");
    }
  } catch (error) {
    console.error("Network error submitting vote", error);
  }
}
```
