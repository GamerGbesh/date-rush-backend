import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.match_rooms import router as match_rooms_router
from app.api.matches import router as matches_router
from app.api.queue import router as queue_router
from app.api.rooms import router as rooms_router
from app.api.users import router as users_router
from app.api.ws import router as ws_router
from app.config import settings
from app.database import init_db
from app.exceptions import InvalidRoomTransitionError, MatchRoomNotFoundError, RoomNotFoundError
from app.logging_config import setup_logging

# Configure logging immediately on module load
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup and log lifecycle."""
    logger.info("Starting Date Rush API: Initializing database and services...")
    import asyncio
    from app.services.websocket_manager import ws_manager
    ws_manager.set_loop(asyncio.get_running_loop())
    init_db()
    logger.info("Date Rush API initialized and ready to serve requests.")
    yield
    logger.info("Date Rush API shutting down.")


app = FastAPI(
    title="Date Rush",
    description="Live matchmaking event system — backend API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """Log incoming HTTP requests and their responses with duration and status code."""
    start_time = time.perf_counter()
    client_host = request.client.host if request.client else "unknown"
    path = request.url.path
    query_string = request.url.query
    full_path = f"{path}?{query_string}" if query_string else path

    logger.info("--> %s %s [client=%s]", request.method, full_path, client_host)
    try:
        response = await call_next(request)
        process_time = (time.perf_counter() - start_time) * 1000
        logger.info(
            "<-- %s %s [%s] completed in %.2fms",
            request.method,
            full_path,
            response.status_code,
            process_time,
        )
        return response
    except Exception as exc:
        process_time = (time.perf_counter() - start_time) * 1000
        logger.exception(
            "<-- %s %s [500] unhandled exception in %.2fms: %s",
            request.method,
            full_path,
            process_time,
            str(exc),
        )
        raise


app.include_router(users_router)
app.include_router(queue_router)
app.include_router(rooms_router)
app.include_router(matches_router)
app.include_router(match_rooms_router)
app.include_router(admin_router)
app.include_router(ws_router)


@app.exception_handler(InvalidRoomTransitionError)
async def invalid_room_transition_handler(request: Request, exc: InvalidRoomTransitionError):
    logger.warning("Invalid room transition on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": exc.message},
    )


@app.exception_handler(RoomNotFoundError)
async def room_not_found_handler(request: Request, exc: RoomNotFoundError):
    logger.warning("Room not found on %s: %s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(MatchRoomNotFoundError)
async def match_room_not_found_handler(request: Request, exc: MatchRoomNotFoundError):
    logger.warning("Match room not found on %s: %s", request.url.path, str(exc))
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}

