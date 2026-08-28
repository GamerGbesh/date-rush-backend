# Date Rush — Backend

A live matchmaking event system backend built with FastAPI, SQLAlchemy, and SQLite.

---

## Installation

Requires [uv](https://docs.astral.sh/uv/) (Python package manager).

```bash
# Install all dependencies (including dev)
uv sync --dev
```

---

## Running the server

```bash
uv run uvicorn app.main:app --reload
```

The server automatically applies any pending migrations (`alembic upgrade head`) at startup. The API will be available at `http://localhost:8000`.
Interactive API docs: `http://localhost:8000/docs`

---

## Database migrations (Alembic)

Schema changes are managed by Alembic. The `alembic/` directory contains the migration scripts and `alembic.ini` contains the configuration.

**Apply migrations** (also runs automatically on server start):
```bash
uv run alembic upgrade head
```

**Check current revision**:
```bash
uv run alembic current
```

**After changing a model**, generate a new migration:
```bash
uv run alembic revision --autogenerate -m "describe your change"
```

**Roll back one revision**:
```bash
uv run alembic downgrade -1
```

> [!NOTE]
> The `DATABASE_URL` used by Alembic is read from `app.config.settings`,
> so it respects your `.env` file and environment variables — no separate
> configuration needed.

## Running tests

```bash
uv run pytest tests/ -v
```

---

## Configuration

Copy `.env.example` to `.env` and adjust values as needed:

| Variable               | Default                     | Description                                            |
|------------------------|-----------------------------|--------------------------------------------------------|
| `DATABASE_URL`         | `sqlite:///./date_rush.db`  | SQLAlchemy database URL                                |
| `GAME_ROOM_THRESHOLD`  | `5`                         | Minimum same-gender queue size before a room can form  |
| `QUESTIONS_PER_ROOM`   | `10`                        | Number of questions per game room (reserved)           |

---

## Architecture

```
app/
├── main.py              # FastAPI app entry point, lifespan, router registration
├── config.py            # Application settings via pydantic-settings
├── database.py          # SQLAlchemy engine, session factory, Base, get_db()
├── enums.py             # All domain enums (Gender, UserState, RoomState, etc.)
├── models/              # SQLAlchemy ORM models (persistent state)
│   ├── user.py
│   ├── room.py          # Room + RoomParticipant
│   ├── question.py
│   ├── answer.py
│   ├── vote.py
│   └── match.py
├── schemas/             # Pydantic request/response schemas
│   ├── user.py
│   ├── room.py
│   └── question.py
├── services/            # Business logic layer
│   ├── queue_manager.py     # Add/remove users from gender queues
│   ├── room_manager.py      # Room lifecycle and participant management
│   └── websocket_manager.py # In-memory WebSocket connection registry
└── api/                 # FastAPI route handlers (thin — no business logic)
    ├── users.py
    ├── rooms.py
    └── admin.py         # Placeholder for future admin endpoints

alembic/                 # Alembic migration scripts
├── env.py               # Configured to read DATABASE_URL from app.config.settings
├── script.py.mako       # Template for new migration files
└── versions/            # One .py file per schema migration
alembic.ini              # Alembic configuration

tests/
```

### Layer boundaries

```
API routes (app/api/)
    ↓ calls
Service layer (app/services/)
    ↓ reads/writes
Database models (app/models/)
```

- **API routes** only handle HTTP concerns: parsing requests, calling services, returning responses.
- **Services** own all business/game logic.
- **Models** represent persisted state via SQLAlchemy.
- **Schemas** represent API data shapes via Pydantic.
- **Enums** define all valid states and domain values.

### Queue design

The male and female queues are **not separate tables**. A user is "in the queue" when their `state = QUEUED`. `QueueManager` queries the `users` table directly. This keeps SQLite as the single source of truth and eliminates synchronisation bugs.

### WebSocket connections

Active WebSocket connections are stored **in memory only** (in `WebSocketManager`). On server restart, connections are lost — this is expected for a single-process event application. Persistent state (room progress, participants, votes) always lives in the database.

---

## Current API endpoints

| Method | Path             | Description                         |
|--------|------------------|-------------------------------------|
| GET    | `/health`        | Health check                        |
| POST   | `/users`         | Create a new user                   |
| GET    | `/rooms/{id}`    | Retrieve a room and its participants |

---

## What has intentionally NOT been implemented yet

The following will be added in subsequent stages:

- **Queue entry** — endpoint to move a user from WAITING → QUEUED
- **Automatic room generation** — detecting when queues are full enough
- **Matchmaking algorithm** — challenger selection, audience selection
- **Question management** — admin endpoints to add/deactivate questions
- **Game flow** — intro → questioning → voting → elimination → final → match
- **Voting** — audience YES/NO votes per round
- **Elimination** — returning NO voters to the queue
- **Match completion** — recording the final pair
- **Contact sharing** — how matched users exchange information
- **Admin dashboard** — room state advancement, queue management
- **Authentication** — any form of user identity verification
- **Timers** — automatic state progression (admin-controlled for now)
- **Redis, Celery, message brokers** — intentionally excluded; single-process design
