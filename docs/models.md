# Database Models Reference

**File:** [`app/models/`](../app/models/)

All models use **SQLAlchemy 2.x declarative mapping** with Python type annotations. The `Mapped[T]` annotation is both a type hint and the ORM column declaration — there is no separate `Column()` call needed.

```python
# SQLAlchemy 2.x style
id: Mapped[int] = mapped_column(primary_key=True, index=True)
name: Mapped[str] = mapped_column(String(100), nullable=False)
```

---

## Design Decisions

### Integer primary keys

All primary models use integer auto-increment PKs rather than UUIDs. Rationale:

- IDs are never generated externally (no mobile clients, no external systems).
- Integer PKs are simpler to type in URLs (`/rooms/3`) and faster for SQLite B-tree indexes.
- UUIDs would add noise without benefit in a single-process, single-database system.

### `Base.metadata` population

`app/models/__init__.py` imports every model so that `Base.metadata` is fully populated when Alembic or `init_db()` needs to create/inspect tables. Without this, models defined in modules that haven't been imported yet would be invisible to the migration system.

### SQLite Enum storage

SQLAlchemy's `Enum` type on SQLite stores the **enum name** (e.g. `"MALE"`) by default, not the value (`"male"`). In this codebase the enum *names* and *values* differ in case (`MALE` vs `"male"`), so this is important to be aware of: the database stores `"MALE"`, but Python code compares with `Gender.MALE == "male"` (which works because `StrEnum` makes the member equal to its *value*). The Alembic-generated migration captures the actual stored strings.

---

## `User`

**File:** [`app/models/user.py`](../app/models/user.py)

```
users
├── id          INTEGER PRIMARY KEY AUTOINCREMENT
├── name        VARCHAR(100)  NOT NULL
├── gender      ENUM('MALE','FEMALE')  NOT NULL
├── state       ENUM('WAITING','QUEUED','IN_GAME','MATCHED')  NOT NULL  DEFAULT 'WAITING'
├── created_at  DATETIME WITH TIMEZONE  NOT NULL
└── queued_at   DATETIME WITH TIMEZONE  NULL
```

### Field explanations

| Field | Type | Purpose |
|---|---|---|
| `id` | `int` | Auto-increment primary key |
| `name` | `str(100)` | Display name entered on registration |
| `gender` | `Gender` | Determines queue placement and room role eligibility |
| `state` | `UserState` | Lifecycle position; the authoritative source for queue membership |
| `created_at` | `datetime` | UTC timestamp of registration |
| `queued_at` | `datetime \| None` | UTC timestamp when user entered the queue; drives FIFO ordering; `None` when not queued |

### Why `queued_at` is separate from `created_at`

A user registers (`created_at` set), then later explicitly joins the queue (`queued_at` set). In future stages, eliminated users re-enter the queue — their `queued_at` is reset to `now()` at that point, giving them a later position in the queue than users who have been waiting longer. Using `created_at` for ordering would incorrectly favour users who registered early but joined the queue late.

### No uniqueness constraint on `name`

Two people called "James" should both be able to register. Name is a display label, not an identifier. Future authentication stages would introduce a unique identifier (phone number, email, etc.).

---

## `Room`

**File:** [`app/models/room.py`](../app/models/room.py)

```
rooms
├── id                  INTEGER PRIMARY KEY AUTOINCREMENT
├── state               ENUM(RoomState values)  NOT NULL  DEFAULT 'WAITING'
├── challenger_id       INTEGER  NULL  → users.id
├── challenger_gender   ENUM('MALE','FEMALE')  NULL
├── current_question_id INTEGER  NULL  → questions.id
├── current_round       INTEGER  NOT NULL  DEFAULT 0
└── created_at          DATETIME WITH TIMEZONE  NOT NULL
```

### Field explanations

| Field | Type | Purpose |
|---|---|---|
| `id` | `int` | Auto-increment primary key |
| `state` | `RoomState` | Current phase of the room's lifecycle |
| `challenger_id` | `int \| None` | FK to the challenger `User`; nullable until the room is assembled |
| `challenger_gender` | `Gender \| None` | Cached for efficient question filtering without joining `users` |
| `current_question_id` | `int \| None` | The active question in the current round; `None` between rounds |
| `current_round` | `int` | Monotonically increasing round counter; starts at 0 |
| `created_at` | `datetime` | UTC creation timestamp |

### Why `challenger_gender` is denormalised

The challenger's gender is stored on `Room` even though it can be derived from `users.gender` via `challenger_id`. This avoids a join every time the game logic needs to know which questions are eligible. It is set once at room creation and never changes.

### Why `challenger_id` is nullable

Rooms can technically be created in a `WAITING` state before participants are assigned (the `RoomManager.create_room()` scaffold method does this). In the production flow (`create_room_with_participants()`), the challenger is set immediately.

---

## `RoomParticipant`

**File:** [`app/models/room.py`](../app/models/room.py) (same file as `Room`)

```
room_participants
├── room_id    INTEGER  NOT NULL  → rooms.id     ┐
├── user_id    INTEGER  NOT NULL  → users.id     ├─ Composite PRIMARY KEY
├── role       ENUM('CHALLENGER','AUDIENCE')  NOT NULL
├── joined_at  DATETIME WITH TIMEZONE  NOT NULL
└── left_at    DATETIME WITH TIMEZONE  NULL
```

### Design: composite primary key instead of surrogate key

Using `(room_id, user_id)` as the PK ensures a user can only appear once in a given room at the database level — no application-layer check needed. A surrogate `id` column would allow accidental duplicates.

### Why `left_at` instead of DELETE

When a user is eliminated (voted out), their `RoomParticipant` record is **not deleted**. Instead, `left_at` is set to the current UTC timestamp. This preserves a complete audit trail:

- Who was in each room.
- In what order they left.
- Whether any eliminations happened.

Active participants are those with `left_at IS NULL`.

### Relationship to `Room`

```python
# On Room:
participants: Mapped[list["RoomParticipant"]] = relationship(
    "RoomParticipant", back_populates="room", lazy="select"
)
```

`lazy="select"` means participants are loaded in a separate query when accessed, not joined automatically. For most API calls this is fine; for bulk operations, consider `selectinload` in the query.

---

## `Question`

**File:** [`app/models/question.py`](../app/models/question.py)

```
questions
├── id             INTEGER PRIMARY KEY AUTOINCREMENT
├── text           VARCHAR(500)  NOT NULL
├── target_gender  ENUM('ANY','MALE','FEMALE')  NOT NULL  DEFAULT 'ANY'
├── active         BOOLEAN  NOT NULL  DEFAULT TRUE
└── created_at     DATETIME WITH TIMEZONE  NOT NULL
```

### Field explanations

| Field | Purpose |
|---|---|
| `text` | The question text displayed to the challenger |
| `target_gender` | Filters which questions are eligible for a given room's challenger gender |
| `active` | Soft-delete flag — deactivated questions are excluded from selection without being lost |
| `created_at` | Allows ordering by recency; useful when a question pool grows over time |

### Why questions are in the database

Questions are dynamically manageable — an admin can add, edit, or deactivate them without a code deployment. This is why they are a first-class model rather than a hardcoded list.

---

## `Answer`

**File:** [`app/models/answer.py`](../app/models/answer.py)

```
answers
├── id           INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id      INTEGER  NOT NULL  → rooms.id
├── question_id  INTEGER  NOT NULL  → questions.id
├── user_id      INTEGER  NOT NULL  → users.id
├── answer       VARCHAR(1000)  NOT NULL
└── created_at   DATETIME WITH TIMEZONE  NOT NULL
```

### Purpose

Records what the challenger said in response to each question. This enables:

- Real-time display to the audience via WebSocket broadcast.
- Post-event review of what happened in each room.
- Future features like answer replay or highlight reels.

### Why `user_id` is stored alongside `room_id`

Denormalization for clarity — you can query "all answers by user 3" without joining through `room_participants`. The challenger for a given room is also `room.challenger_id`, but storing `user_id` on `Answer` avoids that join.

---

## `Vote`

**File:** [`app/models/vote.py`](../app/models/vote.py)

```
votes
├── id          INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id     INTEGER  NOT NULL  → rooms.id
├── round       INTEGER  NOT NULL
├── voter_id    INTEGER  NOT NULL  → users.id
├── target_id   INTEGER  NOT NULL  → users.id
├── vote        ENUM('YES', 'NO')  NOT NULL
└── created_at  DATETIME WITH TIMEZONE  NOT NULL

UNIQUE (room_id, round, voter_id)   ← uq_vote_per_round
```

### The unique constraint

`UNIQUE (room_id, round, voter_id)` is enforced at the **database level**. This prevents:

- A voter submitting two votes in the same round (accidentally or maliciously).
- Application bugs that call the vote-submission endpoint twice.

The constraint name `uq_vote_per_round` is explicit so Alembic can manage it correctly across migrations.

### `vote` as VoteChoice enum

`YES` = keep the challenger, `NO` = eliminate the voter from the current room and return them to the queue.


### `round` field

Votes belong to a specific round, not just a room. This allows the system to tally votes per-round correctly even if the data grows across many rounds.

---

## `Match`

**File:** [`app/models/match.py`](../app/models/match.py)

```
matches
├── id            INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id       INTEGER  NOT NULL  → rooms.id (UNIQUE)
├── challenger_id INTEGER  NOT NULL  → users.id
├── audience_id   INTEGER  NOT NULL  → users.id
├── status        ENUM('CREATED', 'COMPLETED', 'CANCELLED')  NOT NULL  DEFAULT 'CREATED'
└── created_at    DATETIME WITH TIMEZONE  NOT NULL

UNIQUE (room_id)   ← uq_match_room_id
```

### Purpose

Records the final pairing produced by a room. When the challenger selects a finalist (or when a single survivor remains after 1-on-1), a `Match` record is created linking the challenger and the matched audience member.

### Contact sharing not yet implemented

The mechanism for matched users to exchange contact information (phone number reveal, QR code, etc.) will be added in a later stage. The `Match` table is the foundation that exchange will build on.

### Why both FKs point to `users`

SQLAlchemy allows multiple foreign keys from one table to the same target table. Both `challenger_id` and `audience_id` are `→ users.id`. There is no ambiguity at the database level — they are simply two different user references.

---

## `RoomStateHistory`

**File:** [`app/models/room_state_history.py`](../app/models/room_state_history.py)

```
room_state_history
├── id          INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id     INTEGER  NOT NULL  → rooms.id
├── from_state  ENUM(RoomState values)  NOT NULL
├── to_state    ENUM(RoomState values)  NOT NULL
└── created_at  DATETIME WITH TIMEZONE  NOT NULL
```

### Purpose

Provides an audit log of state transitions for each game room during live events. Recorded on every successful state change.

---

## `RoomQuestion`

**File:** [`app/models/room_question.py`](../app/models/room_question.py)

```
room_questions
├── id          INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id     INTEGER  NOT NULL  → rooms.id
├── question_id INTEGER  NOT NULL  → questions.id
├── position    INTEGER  NOT NULL
├── phase       ENUM('PUBLIC', 'PRIVATE')  NOT NULL  DEFAULT 'PUBLIC'
└── created_at  DATETIME WITH TIMEZONE  NOT NULL

UNIQUE (room_id, position)
UNIQUE (room_id, question_id)
```

### Purpose

Persists the randomized, gender-filtered question sequence determined at room creation time.

---

## `OneOnOneSession`

**File:** [`app/models/one_on_one_session.py`](../app/models/one_on_one_session.py)

```
one_on_one_sessions
├── id            INTEGER PRIMARY KEY AUTOINCREMENT
├── room_id       INTEGER  NOT NULL  → rooms.id
├── audience_id   INTEGER  NOT NULL  → users.id
├── challenger_id INTEGER  NOT NULL  → users.id
├── sequence      INTEGER  NOT NULL
├── state         ENUM('PENDING', 'ACTIVE', 'ANSWERED', 'VOTING', 'ACCEPTED', 'REJECTED', 'COMPLETED')
├── question      VARCHAR(500)  NULL
├── answer        VARCHAR(1000)  NULL
├── vote          ENUM('YES', 'NO')  NULL
├── started_at    DATETIME WITH TIMEZONE  NULL
├── answered_at   DATETIME WITH TIMEZONE  NULL
├── voted_at      DATETIME WITH TIMEZONE  NULL
├── completed_at  DATETIME WITH TIMEZONE  NULL
└── created_at    DATETIME WITH TIMEZONE  NOT NULL

UNIQUE (room_id, sequence)
UNIQUE (room_id, audience_id)
```

### Purpose

Tracks the sequential 1-on-1 private sessions between the challenger and each surviving audience member, along with their private question, answer, and mandatory private vote.

---

## `MatchRoom`

**File:** [`app/models/match_room.py`](../app/models/match_room.py)

```
match_rooms
├── id           INTEGER PRIMARY KEY AUTOINCREMENT
├── match_id     INTEGER  NOT NULL  → matches.id (UNIQUE)
├── state        ENUM('WAITING_FOR_CONTACTS', 'CONTACTS_EXCHANGED', 'COMPLETED')  NOT NULL  DEFAULT 'WAITING_FOR_CONTACTS'
├── created_at   DATETIME WITH TIMEZONE  NOT NULL
└── completed_at DATETIME WITH TIMEZONE  NULL

UNIQUE (match_id)   ← uq_match_room_match_id
```

### Purpose

Dedicated private post-match room for collecting and exchanging contact details between the two matched participants.

---

## `MatchContact`

**File:** [`app/models/match_contact.py`](../app/models/match_contact.py)

```
match_contacts
├── id            INTEGER PRIMARY KEY AUTOINCREMENT
├── match_room_id INTEGER  NOT NULL  → match_rooms.id
├── user_id       INTEGER  NOT NULL  → users.id
├── whatsapp      VARCHAR(100)  NULL
├── snapchat      VARCHAR(100)  NULL
└── submitted_at  DATETIME WITH TIMEZONE  NOT NULL

UNIQUE (match_room_id, user_id)   ← uq_match_room_user_contact
```

### Purpose

Stores the WhatsApp and/or Snapchat handle submitted by a matched participant for that specific match. It is not part of the user's permanent profile.





---

## Entity Relationship Diagram

```
users ──────────────────────────────────────────────────────┐
  │ id                                                       │
  │ name                                                     │
  │ gender                                                   │
  │ state                                                    │
  │ queued_at                                                │
  │                                                          │
  └──< room_participants                                     │
         room_id ──►──────── rooms ──────► questions        │
         user_id ──►──────── id              id             │
         role               state            text           │
         joined_at          challenger_id ►──┘  (current)  │
         left_at            challenger_gender               │
                            current_question_id             │
                            current_round                   │
                                 │                          │
                                 └──< answers               │
                                        room_id             │
                                        question_id         │
                                        user_id ──────────►─┘
                                        answer              │
                                                            │
                                      votes                 │
                                        room_id             │
                                        round               │
                                        voter_id ─────────►─┘
                                        vote                │
                                                            │
                                      matches               │
                                        room_id             │
                                        challenger_id ────►─┤
                                        audience_id ──────►─┘
```
