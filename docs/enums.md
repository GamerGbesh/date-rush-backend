# Enums Reference

**File:** [`app/enums.py`](../app/enums.py)

All enumerations in Date Rush use Python's `StrEnum`. This means each member *is* a `str` — its value is the string stored in SQLite and serialised into JSON. You can compare enum members directly with strings:

```python
user.gender == "male"    # True if gender is Gender.MALE
user.state == "queued"   # True if state is UserState.QUEUED
```

Using `StrEnum` instead of plain `Enum` avoids a common class of bugs where database values (`"male"`) and Python objects (`Gender.MALE`) get out of sync.

---

## `Gender`

```python
class Gender(StrEnum):
    MALE   = "male"
    FEMALE = "female"
```

### Why only two values?

The room-generation algorithm is fundamentally binary: it divides users into exactly two pools and assigns one pool as the challenger and the other as the audience. Adding a third gender would require rethinking the entire matchmaking model (which pools oppose each other? how are rooms formed?). The two-value constraint is intentional and not a social statement.

### Where it is used

| Location | Purpose |
|---|---|
| `User.gender` | Determines which queue the user enters |
| `Room.challenger_gender` | Denotes the challenger's gender for question targeting |
| `RoomParticipant` (indirectly) | Audience gender is always opposite to `challenger_gender` |
| `QuestionTarget` | Questions can target `MALE` or `FEMALE` challengers |
| `QueueManager.get_size(db, gender)` | Queries queue size per gender |

---

## `UserState`

```python
class UserState(StrEnum):
    WAITING  = "waiting"
    QUEUED   = "queued"
    IN_GAME  = "in_game"
    MATCHED  = "matched"
```

### State machine

```
              ┌────────────────┐
  Register    │                │   join queue
  ──────────► │    WAITING     │ ──────────────► QUEUED
              │                │                   │
              └────────────────┘                   │
                                                   │ room created
                                                   ▼
              ┌────────────────┐               IN_GAME
              │                │◄──────────────────┘
              │    WAITING     │   voted NO
              │  (re-queued)   │   (returns to queue,
              └────────────────┘    not yet implemented)
                                                   │
                                               MATCHED
                                          (final 1:1 reached,
                                           not yet implemented)
```

### Why `queued_at` is separate from state

`user.state = QUEUED` tells you *that* a user is in the queue. `user.queued_at` tells you *when* they joined. The timestamp drives FIFO ordering — without it, queue order would depend on insertion row ID, which is less transparent and breaks if users are ever removed and re-added.

### `IN_GAME → QUEUED` (not yet implemented)

When an audience member votes NO, they leave the room and re-enter their gender queue. This transition is explicit rather than automatic so the admin can control pacing.

---

## `PlayerRole`

```python
class PlayerRole(StrEnum):
    CHALLENGER = "challenger"
    AUDIENCE   = "audience"
```

### Why role is separate from user state

A user's *state* (`IN_GAME`) describes their lifecycle position. Their *role* (`CHALLENGER` or `AUDIENCE`) describes their function within a specific room. These are orthogonal:

- The same user could theoretically be CHALLENGER in room A then AUDIENCE in room B (after the full elimination flow is implemented).
- `state` is global; `role` is scoped to a `RoomParticipant` record.

### Where it is stored

`RoomParticipant.role` — not on the `User` model. This is correct: role is a room-scoped property, not a user-level property.

---

## `RoomState`

```python
class RoomState(StrEnum):
    WAITING     = "waiting"
    READY       = "ready"
    INTRO       = "intro"
    QUESTIONING = "questioning"
    VOTING      = "voting"
    ELIMINATION = "elimination"
    FINAL       = "final"
    MATCHED     = "matched"
    COMPLETED   = "completed"
```

### State machine (planned)

```
WAITING ──► READY ──► INTRO ──► QUESTIONING ──► VOTING ──► ELIMINATION
                                     ▲                           │
                                     │    (repeat per round)     │
                                     └───────────────────────────┘
                                              until 1 remains
                                                   │
                                                   ▼
                                               FINAL ──► MATCHED ──► COMPLETED
```

| State | Meaning |
|---|---|
| `WAITING` | Room object created but not yet fully assembled (scaffold state) |
| `READY` | Room has exactly 1 challenger + N audience. Ready to begin |
| `INTRO` | Challenger is being introduced to the audience |
| `QUESTIONING` | Challenger is answering the current question |
| `VOTING` | Audience members are casting YES/NO votes |
| `ELIMINATION` | Votes tallied; NO voters are being removed |
| `FINAL` | Only 1 audience member remains; 1:1 pairing state |
| `MATCHED` | A match has been recorded |
| `COMPLETED` | Room is closed; no further actions possible |

### Why admin-controlled, not timer-driven?

The event is run live with a host. Automatic timers cannot account for audience reactions, technical delays, or the host's pacing. The admin triggers transitions manually, giving full control over the event flow. Timers may be added later as an optional layer on top of admin control.

### Current implementation (Stage 2)

Rooms are created with `state=READY`. All other transitions are scaffolded but not yet implemented.

---

## `QuestionTarget`

```python
class QuestionTarget(StrEnum):
    ANY    = "any"
    MALE   = "male"
    FEMALE = "female"
```

### Purpose

Questions can be written with a specific challenger gender in mind. For example, questions referencing romantic scenarios from a male perspective would be tagged `MALE` and only shown when the challenger is male.

| Value | Meaning |
|---|---|
| `ANY` | General question; shown regardless of challenger gender |
| `MALE` | Only shown when `Room.challenger_gender == MALE` |
| `FEMALE` | Only shown when `Room.challenger_gender == FEMALE` |

### Where filtering happens

Question selection (and gender filtering) is not yet implemented. The `target_gender` field exists on the `Question` model to support it without a future migration.
