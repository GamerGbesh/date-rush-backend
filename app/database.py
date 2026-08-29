from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Apply all pending Alembic migrations and ensure default questions exist.

    Called once at application startup via the FastAPI lifespan handler.
    This ensures the database schema is always up to date and default questions
    are seeded for matchmaking rooms.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    # Seed default questions if table is empty
    from app.enums import QuestionTarget
    from app.models.question import Question

    db = SessionLocal()
    try:
        if db.query(Question).count() == 0:
            default_questions = [
                # ANY target
                Question(text="What is your idea of a perfect weekend date?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What is the most important quality you look for in a partner?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What is your biggest pet peeve in a relationship?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you handle disagreements with someone you care about?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What is something you are deeply passionate about?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What is your favorite travel destination and why?", target_gender=QuestionTarget.ANY, active=True),
                # MALE target
                Question(text="How do you express your feelings when you really like someone?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What is one thing you wish women understood better about men?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What does commitment mean to you?", target_gender=QuestionTarget.MALE, active=True),
                # FEMALE target
                Question(text="What makes you feel truly appreciated in a relationship?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What is one quality that immediately catches your attention?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you maintain balance between work and personal life?", target_gender=QuestionTarget.FEMALE, active=True),
            ]
            db.add_all(default_questions)
            db.commit()
    finally:
        db.close()
