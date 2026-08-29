# Services Reference

**Directory:** [`app/services/`](../app/services/)

The service layer contains all business logic. Route handlers call services; services call the database. Services are instantiated as **module-level singletons** — there is exactly one `queue_manager`, one `room_manager`, and one `ws_manager` per process.

---

## `QueueManager`

**File:** [`app/services/queue_manager.py`](../app/services/queue_manager.py)

**Singleton:** `queue_manager = QueueManager()`

### Concept: the queue is a database query

There is no separate queue table. The queue is defined as:

```sql
SELECT * FROM users
WHERE gender = ?
  AND state   = 'QUEUED'
ORDER BY queued_at ASC, id ASC
```

This means:

- Adding a user to the queue = setting `user.state = QUEUED` and `user.queued_at = now()`.
- Removing a user from the queue = setting `user.state = WAITING` and `user.queued_at = NULL`.
- Queue size = `COUNT(*) WHERE gender = ? AND state = 'QUEUED'`.

The database is always the authoritative source. There is no in-memory queue list that could get out of sync.

### FIFO ordering

Queue order is determined by `queued_at ASC, id ASC`:

- `queued_at` is the primary sort key. Users who joined earlier appear first.
- `id` is a tiebreaker for users who joined at exactly the same microsecond (unlikely in practice, but makes ordering deterministic).

### Methods

---

#### `add(db, user) → None`

```python
user.state    = UserState.QUEUED
user.queued_at = datetime.now(timezone.utc)
db.commit()
db.refresh(user)
```

Transitions `WAITING → QUEUED`. Sets `queued_at` so the user gets a position in the FIFO queue.

---

#### `remove(db, user) → None`

```python
user.state    = UserState.WAITING
user.queued_at = None
db.commit()
db.refresh(user)
```

Removes the user from the queue and returns them to WAITING. Clears `queued_at` so it is not accidentally used as a stale position if the user re-queues later.

---

#### `get_size(db, gender) → int`

```python
SELECT COUNT(id) FROM users
WHERE gender = ? AND state = 'QUEUED'
```

Returns the number of users currently waiting in the given gender queue. Used by `try_create_rooms()` to evaluate whether a room can be formed.

---

#### `get_users(db, gender) → list[User]`

Returns all queued users for a gender in FIFO order. Used for inspection and testing. Not used in the hot path of room creation (see `_select_for_room`).

---

#### `pop_many(db, gender, count) → list[User]`

Removes up to `count` users from the queue (FIFO) and marks them `IN_GAME`. Commits. Returns the affected users.

**Used by:** tests and utilities. The production room-creation path uses `_select_for_room` + `room_manager.create_room_with_participants` for atomicity.

---

#### `try_create_rooms(db) → list[Room]`

The core room-generation algorithm. **This is the most important method in the service layer.**

```python
with _room_creation_lock:
    while True:
        male_count   = get_size(db, MALE)
        female_count = get_size(db, FEMALE)

        if male_count >= THRESHOLD and female_count >= 1:
            audience   = _select_for_room(db, MALE,   THRESHOLD)
            challenger = _select_for_room(db, FEMALE, 1)[0]
            room       = room_manager.create_room_with_participants(db, challenger, audience)
            created.append(room)
            continue   # re-evaluate with updated queue sizes

        if female_count >= THRESHOLD and male_count >= 1:
            audience   = _select_for_room(db, FEMALE, THRESHOLD)
            challenger = _select_for_room(db, MALE,   1)[0]
            room       = room_manager.create_room_with_participants(db, challenger, audience)
            created.append(room)
            continue

        break  # neither condition met; no more rooms possible

return created
```

**Challenger selection logic:**

The queue with fewer users supplies the challenger. The logic is evaluated in priority order:

1. If males ≥ threshold and females ≥ 1 → female is challenger (females are the minority).
2. Else if females ≥ threshold and males ≥ 1 → male is challenger.

This naturally selects the minority-gender user as the challenger (the spec's intent). Edge case: if both queues are exactly at threshold, the first branch wins (male audience, female challenger).

**Iteration:** After each successful room creation, `create_room_with_participants` commits. The next `get_size` calls see the updated database state — consumed users are now `IN_GAME` and excluded from the count. This is why committing per room is correct.

**Return value:** Returns `list[Room]` so the HTTP layer can include `room_id` in the join response without an extra query.

---

#### `_select_for_room(db, gender, count) → list[User]` (private)

```python
SELECT * FROM users
WHERE gender = ? AND state = 'QUEUED'
ORDER BY queued_at, id
LIMIT ?
```

**Read-only.** Does not change any state. Used by `try_create_rooms` to identify which users will be consumed by the next room. State changes happen inside `create_room_with_participants`.

---

### Concurrency and the `threading.Lock`

FastAPI runs synchronous route handlers in a thread pool. Without locking, two simultaneous `POST /queue/join` requests could both call `try_create_rooms`, both read the same queue sizes, and both attempt to consume the same users — creating two rooms that share participants.

```python
# Module-level lock
_room_creation_lock = threading.Lock()

def try_create_rooms(self, db):
    with _room_creation_lock:
        ...
```

The lock is held for the entire `while` loop. This means room creation is serialised across threads — at most one room-creation loop runs at a time. This is correct and appropriate for a single-process application.

**Why not use database-level locking?**

SQLite supports `BEGIN IMMEDIATE` to acquire a write lock upfront. However, that would require low-level DBAPI control. A Python `threading.Lock` achieves the same goal more cleanly within a single process.

---

## `RoomManager`

**File:** [`app/services/room_manager.py`](../app/services/room_manager.py)

**Singleton:** `room_manager = RoomManager()`

Manages room lifecycle: creation, participant management, and state transitions.

### Methods

---

#### `create_room(db, challenger_gender) → Room`

Creates a minimal room in `WAITING` state. Used as a scaffold in tests and in future admin-initiated room setup flows. Does not assign participants.

---

#### `create_room_with_participants(db, challenger, audience) → Room`

**The atomic room-creation method.** All of the following happen inside a single database transaction:

```
1. challenger.state    = IN_GAME,  challenger.queued_at = None
2. user.state          = IN_GAME,  user.queued_at        = None  (for each audience user)
3. INSERT INTO rooms (state=READY, challenger_id=..., challenger_gender=..., current_round=0)
4. db.flush()    ← materialises room.id without committing
5. INSERT INTO room_participants (room_id, user_id=challenger.id, role=CHALLENGER)
6. INSERT INTO room_participants (room_id, user_id=user.id,       role=AUDIENCE)   × N
7. db.commit()   ← all-or-nothing
8. db.refresh(room)
```

If **any** step raises an exception, `db.rollback()` is called in the `except` block. Users are left in QUEUED state (their state changes are uncommitted). No partial room is created.

**Why `db.flush()` before `db.commit()`?**

`db.flush()` sends pending SQL to the database connection's buffer without committing the transaction. This is necessary to obtain `room.id` (assigned by the autoincrement sequence) before creating the `RoomParticipant` records that need it. The entire buffer is then committed atomically.

---

#### `get_room(db, room_id) → Room`

```python
room = db.get(Room, room_id)
if room is None:
    raise HTTPException(404, f"Room {room_id} not found.")
return room
```

Fetches a room by PK, raising `HTTP 404` if absent. Route handlers use this to avoid boilerplate existence checks.

---

#### `add_participant(db, room, user, role) → RoomParticipant`

Adds a single participant to an existing room. Used in tests and for future admin-controlled participant assignment. Sets `user.state = IN_GAME`.

---

#### `remove_participant(db, room, user) → RoomParticipant`

Sets `participant.left_at = now()` and returns the user to `QUEUED` state. The participant record is **not deleted** — see [docs/models.md](./models.md) for why.

---

#### `set_state(db, room, new_state) → Room`

Transitions a room to a new `RoomState`. No validation of the transition is currently enforced — the admin is trusted to call this correctly. A state machine guard could be added later.

---

#### `get_active_participants(db, room) → list[RoomParticipant]`

Returns `[p for p in room.participants if p.left_at is None]`. Active participants are those who have not yet been eliminated.

---

## `RoomStateService`

**File:** [`app/services/room_state_service.py`](../app/services/room_state_service.py)

**Singleton:** `room_state_service = RoomStateService()`

Manages the explicit room state machine, transition validations, history audit logging, and WebSocket broadcast events.

### Valid transitions

```
READY → INTRO
INTRO → QUESTIONING
QUESTIONING → VOTING
VOTING → ELIMINATION
ELIMINATION → QUESTIONING (when > 1 audience member remains)
ELIMINATION → FINAL (when 1 audience member remains)
FINAL → MATCHED
MATCHED → COMPLETED
```

### Methods

- `transition(db, room_id, target_state) -> Room` (async): validates transition, updates state, increments `current_round` on entering `QUESTIONING`, logs `RoomStateHistory`, commits, and broadcasts `room_state_changed` event over WebSocket.
- `get_history(db, room_id) -> list[RoomStateHistory]`: returns audit log of transitions.
- `determine_next_elimination_state(db, room) -> RoomState`: routes to `FINAL` or `QUESTIONING`.


---

## `WebSocketManager`

**File:** [`app/services/websocket_manager.py`](../app/services/websocket_manager.py)

**Singleton:** `ws_manager = WebSocketManager()`

Manages the in-memory registry of active WebSocket connections.

### Data structure

```python
_connections: dict[int, dict[int, WebSocket]]
#              room_id → { user_id → WebSocket }
```

A nested dictionary keyed by `room_id` then `user_id`. This allows:

- Broadcasting to all users in a room in O(N) time.
- Sending a message to a specific user in O(1) time.
- Disconnecting a user in O(1) time.

### Why in-memory?

WebSocket connections are ephemeral — they live only as long as the TCP connection. There is no meaningful way to persist an active socket connection to a database. If the server restarts, all connections are lost (clients must reconnect).

The in-memory store is rebuilt from zero on each server start. This is correct behaviour.

### Methods

---

#### `connect(room_id, user_id, websocket) → None`

Registers a WebSocket connection. If this is the first connection for a room, the inner dict is created.

---

#### `disconnect(room_id, user_id) → None`

Removes the connection. If the room becomes empty after disconnect, the room's dict is cleaned up to prevent memory leaks.

---

#### `send_to_user(room_id, user_id, message) → None` (async)

Sends a JSON-serialisable message to a specific user in a room across their active socket connections. No-op if the user is not connected.

---

#### `send_to_users(room_id, user_ids, message) → None` (async)

Sends a JSON-serialisable message strictly to a specified set/iterable of users in a room. Used for private one-on-one message routing inside the GameRoom channel.

---

#### `broadcast(room_id, message) → None` (async)

Sends a JSON-serialisable message to every connected user in a room. No-op if the room has no connections.

### Future: event types

When the game flow is implemented, `broadcast` and `send_to_user` will carry structured event payloads:

```json
{"event": "question", "data": {"id": 3, "text": "..."}}
{"event": "vote_result", "data": {"yes": 3, "no": 2}}
{"event": "room_assigned", "data": {"room_id": 1, "role": "audience"}}
```

The `WebSocketManager` is already structured to support this — it sends arbitrary JSON without knowing the event structure.

---

## Service Singletons and Dependency Injection

Each service is instantiated once at module import time:

```python
# At the bottom of each service file
queue_manager = QueueManager()
room_manager  = RoomManager()
ws_manager    = WebSocketManager()
```

Route handlers import these singletons directly:

```python
from app.services.queue_manager import queue_manager

@router.post("/queue/join")
def join_queue(payload, db = Depends(get_db)):
    queue_manager.add(db, user)
    queue_manager.try_create_rooms(db)
```

The `db` session is injected per-request via FastAPI's `Depends(get_db)` mechanism. Services are stateless with respect to the database — all state lives in the `db` session and the underlying SQLite file.

### Why singletons instead of FastAPI `Depends`?

Services hold no per-request state (unlike the `db` session, which is per-request). There is no need for a new instance per request. A singleton is simpler and uses less memory.

The exception is `WebSocketManager`, which holds mutable in-memory state (the connection dict). This works correctly as a singleton because:

1. The entire application runs in one process.
2. `asyncio` is single-threaded for async operations.
3. WebSocket operations (`connect`, `disconnect`) happen in the async event loop, not the thread pool.
