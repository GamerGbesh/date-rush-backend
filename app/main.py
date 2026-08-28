from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.queue import router as queue_router
from app.api.rooms import router as rooms_router
from app.api.users import router as users_router
from app.api.ws import router as ws_router
from app.database import init_db
from app.exceptions import InvalidRoomTransitionError, RoomNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    init_db()
    yield


app = FastAPI(
    title="Date Rush",
    description="Live matchmaking event system — backend API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(users_router)
app.include_router(queue_router)
app.include_router(rooms_router)
app.include_router(admin_router)
app.include_router(ws_router)


@app.exception_handler(InvalidRoomTransitionError)
async def invalid_room_transition_handler(request: Request, exc: InvalidRoomTransitionError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": exc.message},
    )


@app.exception_handler(RoomNotFoundError)
async def room_not_found_handler(request: Request, exc: RoomNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
