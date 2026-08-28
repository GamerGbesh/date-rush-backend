# Architecture Overview

## What is Date Rush?

Date Rush is a **live, admin-controlled matchmaking event system**. It is designed to be run as a single event: users register on the night, are placed into gender queues, and the system automatically assembles them into game rooms. Each room runs a question-and-answer game that progressively eliminates audience members until one person remains — creating a 1:1 match.

This document describes the technical architecture of the backend.

---

## Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Web framework | **FastAPI** | Async-capable, built-in Pydantic validation, automatic OpenAPI docs, WebSocket support |
| ORM | **SQLAlchemy 2.x** | Mature, type-safe mapped columns, composable queries |
| Database | **SQLite** | Zero-infrastructure, single-process, perfectly adequate for a live event with O(100s) of concurrent users |
| Migrations | **Alembic** | Industry-standard SQLAlchemy migration tool; autogenerates diffs from model changes |
| Validation | **Pydantic v2** | Fast, native Python types, used for both request/response schemas and application settings |
| Settings | **pydantic-settings** | Reads `DATABASE_URL`, thresholds from `.env` or environment variables |
| Enums | **`StrEnum`** | Values are human-readable strings (stored as-is in SQLite), safe to compare with `==`, serialise cleanly to JSON |
| Package manager | **uv** | Fast, modern Python packaging; lockfile included |

### Intentionally excluded

| Technology | Reason for exclusion |
|---|---|
| Redis | No need for a separate in-memory store; SQLite is the source of truth |
| Celery | No background task queue needed; room creation is synchronous |
| PostgreSQL | Overcomplicated for a single-process event app |
| Kafka / RabbitMQ | No message broker needed; single process handles all state |
| Docker orchestration | Single process; simple `uvicorn` startup is sufficient |
| Microservices | One deployable unit is simpler to reason about and debug during a live event |

---

## Layered Architecture

```
┌──────────────────────────────────────────────────────┐
│                    HTTP Clients                       │
│              (browser, admin tool, etc.)              │
└─────────────────────────┬────────────────────────────┘
                          │ HTTP / WebSocket
┌─────────────────────────▼────────────────────────────┐
│                     API Layer                         │
│          app/api/{users, queue, rooms, admin}         │
│                                                       │
│  • Parse & validate requests (Pydantic schemas)       │
│  • Call service methods                               │
│  • Return serialised responses                        │
│  • NO business/game logic                             │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│                   Service Layer                       │
│    app/services/{queue_manager, room_manager,         │
│                  websocket_manager}                   │
│                                                       │
│  • All business logic lives here                      │
│  • QueueManager   — queue operations, room creation   │
│  • RoomManager    — room lifecycle, participants      │
│  • WebSocketManager — in-memory connection registry  │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│                  Persistence Layer                    │
│          app/models/{user, room, question,            │
│                      answer, vote, match}             │
│                                                       │
│  • SQLAlchemy ORM models                              │
│  • Alembic migrations in alembic/versions/            │
│  • SQLite database file (date_rush.db)                │
└──────────────────────────────────────────────────────┘
```

### The rule: logic flows downward only

API routes call services. Services call models/database. Models know nothing about services or the API. This keeps each layer independently testable and prevents business logic from leaking into HTTP handlers.

---

## Directory Structure

```
date_rush/
│
├── app/                        ← Application source
│   ├── main.py                 ← FastAPI app, lifespan, router registration
│   ├── config.py               ← Settings (DATABASE_URL, GAME_ROOM_THRESHOLD, …)
│   ├── database.py             ← Engine, SessionLocal, Base, get_db(), init_db()
│   ├── enums.py                ← All StrEnum definitions
│   │
│   ├── models/                 ← SQLAlchemy ORM models (persistent state)
│   │   ├── __init__.py         ← Re-imports all models (populates Base.metadata)
│   │   ├── user.py
│   │   ├── room.py             ← Room + RoomParticipant
│   │   ├── question.py
│   │   ├── answer.py
│   │   ├── vote.py
│   │   └── match.py
│   │
│   ├── schemas/                ← Pydantic request/response schemas (API contracts)
│   │   ├── user.py
│   │   ├── room.py
│   │   ├── queue.py
│   │   └── question.py
│   │
│   ├── services/               ← Business logic
│   │   ├── queue_manager.py    ← Queue operations + room-creation algorithm
│   │   ├── room_manager.py     ← Room lifecycle + participant management
│   │   └── websocket_manager.py← In-memory WebSocket registry
│   │
│   └── api/                    ← FastAPI route handlers (thin wrappers)
│       ├── users.py            ← POST /users
│       ├── queue.py            ← POST /queue/join, GET /queue/status
│       ├── rooms.py            ← GET /rooms/{id}
│       └── admin.py            ← GET /admin/rooms (+ future admin endpoints)
│
├── alembic/                    ← Database migration scripts
│   ├── env.py                  ← Migration environment (reads app settings)
│   └── versions/               ← One .py file per schema change
│
├── tests/                      ← Test suite
│   ├── conftest.py             ← Fixtures: isolated in-memory DB per test
│   ├── test_enums.py
│   ├── test_models.py
│   ├── test_queue.py
│   ├── test_room_manager.py
│   ├── test_room_creation.py   ← Room-generation algorithm tests
│   ├── test_queue_api.py       ← HTTP integration tests for queue endpoints
│   ├── test_rooms_api.py
│   ├── test_users.py
│   └── test_websocket_manager.py
│
├── docs/                       ← This documentation
├── alembic.ini                 ← Alembic configuration
├── pyproject.toml              ← Project metadata + dependencies (uv)
├── pytest.ini                  ← Test configuration
└── README.md                   ← Quick-start guide
```

---

## Application Startup

```
uvicorn app.main:app
    │
    ├── FastAPI app created
    ├── Routers registered (users, queue, rooms, admin)
    └── Lifespan handler fires:
            init_db()
                └── alembic upgrade head
                        └── Applies any pending migrations to date_rush.db
```

After startup, the application is ready to accept HTTP and WebSocket connections.

---

## Data Flow: User Joins Queue

```
POST /queue/join {"name": "Alice", "gender": "female"}
    │
    ▼
api/queue.py :: join_queue()
    │
    ├── Create User record           (state=WAITING)
    ├── queue_manager.add(user)      (state=QUEUED, queued_at=now())
    ├── queue_manager.try_create_rooms()
    │       │
    │       ├── [threading.Lock acquired]
    │       ├── SELECT count WHERE state=QUEUED AND gender=male   → N
    │       ├── SELECT count WHERE state=QUEUED AND gender=female → M
    │       │
    │       ├── if N >= THRESHOLD and M >= 1:
    │       │       _select_for_room(FEMALE, 1)  → challenger
    │       │       _select_for_room(MALE, N)    → audience
    │       │       room_manager.create_room_with_participants()
    │       │           ├── Set states IN_GAME, clear queued_at
    │       │           ├── INSERT Room (state=READY)
    │       │           ├── flush() → get room.id
    │       │           ├── INSERT RoomParticipant × (1 + N)
    │       │           └── commit()
    │       │
    │       └── [Lock released]
    │
    └── Return {user_id, state, room_id}
```

---

## Concurrency Model

The application is designed for a **single `uvicorn` process** (no workers). FastAPI runs synchronous route handlers in a thread pool via `anyio.to_thread.run_sync`.

The only concurrency risk is in `try_create_rooms()`: two simultaneous join requests could both read the same queue state and attempt to consume the same users. This is prevented by a `threading.Lock` in `QueueManager`. The lock is coarse (one room-creation loop at a time) but correct and appropriate for this scale.

```
Thread A: POST /queue/join (Male 5)
Thread B: POST /queue/join (Male 6)
                │
                ▼
    Both arrive at try_create_rooms()
                │
    Only one acquires the lock.
    The other waits.
                │
    Lock holder: reads queue, creates room, commits.
                │
    Other thread: acquires lock, reads updated queue,
                  finds no room possible, returns.
```

---

## Source of Truth

| State | Where stored |
|---|---|
| User state (WAITING/QUEUED/IN_GAME/MATCHED) | `users.state` in SQLite |
| Queue membership | `users.state = 'QUEUED'` — derived, not a separate table |
| Queue order | `users.queued_at ASC, users.id ASC` |
| Room state | `rooms.state` in SQLite |
| Room participants | `room_participants` table |
| Active WebSocket connections | In-memory `WebSocketManager._connections` dict |

The database is always the authoritative source of truth. The in-memory WebSocket registry is ephemeral — it is rebuilt from zero on each server start.
