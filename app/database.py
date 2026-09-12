import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.config import settings

logger = logging.getLogger(__name__)

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 15

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    poolclass=NullPool if settings.DATABASE_URL.startswith("sqlite") else QueuePool,
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
            logger.debug("Configured SQLite connection pragmas: WAL mode, busy_timeout=5000, synchronous=NORMAL")
        except Exception:
            logger.exception("Failed to configure SQLite pragmas")

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
    logger.info("Initializing database: Running Alembic upgrade to head...")
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes["skip_logging"] = True
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic schema migrations applied successfully.")

    # Seed default questions if table is empty
    from app.enums import QuestionTarget
    from app.models.question import Question

    db = SessionLocal()
    try:
        question_count = db.query(Question).count()
        logger.info("Checking question pool: %d questions currently present.", question_count)
        if question_count == 0:
            logger.info("Seeding default question pool...")
            default_questions = [
                # ANY target
                Question(text="What's a memory that always makes you smile?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="If you could master any skill overnight, what would it be?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you've changed your mind about in the last few years?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you recharge after a long week?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a book, show, or song that changed how you see things?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What does \"home\" mean to you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's the best compliment you've ever received?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you handle being told you're wrong?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you're proud of that most people don't know about?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's your love language, and how did you figure it out?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a tradition you'd want to build with a future partner?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you show someone you're thinking of them?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a fear you've worked hard to overcome?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What does loyalty look like to you in practice?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's the most spontaneous thing you've ever done?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you like to celebrate someone else's wins?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a habit you're currently trying to build?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What would your friends say is your best quality?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something that instantly puts you in a good mood?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you define success for yourself?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a lesson a past relationship taught you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's your idea of quality time?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you handle stress in the moment?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you'll never compromise on?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a goal you're working toward right now?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you like to be supported when you're struggling?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a place that feels most like \"you\"?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something small that makes a big difference to you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you know you've found someone worth investing in?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's your take on giving second chances?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a skill you wish more people had?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you show appreciation for the people close to you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you're curious to learn more about?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's your ideal way to spend a rainy day?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you handle jealousy, in yourself or a partner?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a value your family instilled in you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something that always makes you laugh, no matter what?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you approach making big decisions?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a compliment you wish you gave more often?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What does being present with someone actually look like for you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's the most meaningful gift you've ever given or received?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you like to resolve things after an argument?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you've never told anyone on a first meeting?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a quality you admire in your closest friend?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you handle it when plans fall apart?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you look forward to about getting older?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's your honest take on long-distance relationships?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="How do you like to be pursued?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's a question you wish more people asked you?", target_gender=QuestionTarget.ANY, active=True),
                Question(text="What's something you're still figuring out about love?", target_gender=QuestionTarget.ANY, active=True),

                # MALE target
                Question(text="What's a moment you felt truly proud of yourself?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you balance ambition with making time for someone?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's a lesson your dad (or a father figure) taught you about relationships?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you show vulnerability with someone you're just getting to know?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's something you wish you'd learned earlier about dating?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you handle competition between your friendships and a relationship?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's a habit you think makes you a good partner?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you deal with rejection?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's something you find attractive that isn't physical?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you support a partner's goals without losing sight of your own?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's a stereotype about men you actively try to disprove?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you know when it's time to be serious about someone?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's the most romantic thing you've ever planned?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you handle disagreements without shutting down?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's something you look for that tells you someone's genuine?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you make space for emotional conversations?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's a way you like to be appreciated that people overlook?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you define respect in a relationship?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's something you've had to unlearn about masculinity?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How patient are you, honestly, when getting to know someone?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's a small thing that makes you feel like a good partner?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you handle it when a partner needs space?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's something you're working on to become a better partner?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="How do you show up for someone during their hard days?", target_gender=QuestionTarget.MALE, active=True),
                Question(text="What's one thing you wish you understood sooner about commitment?", target_gender=QuestionTarget.MALE, active=True),

                # FEMALE target
                Question(text="What's something you wish men asked you more often?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you handle a partner who struggles to open up?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's a quality you look for that took you time to value?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you know the difference between comfort and settling?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's something that makes you feel truly seen?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you handle giving advice a partner didn't ask for?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's a boundary you've learned to set and keep?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you support a partner's ambitions without losing your own?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's something that instantly earns your respect?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you like conflict to be handled — in the moment or after cooling off?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's a misconception about what women want that you'd correct?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you know when someone's genuinely interested versus just charming?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's the most thoughtful thing a partner has ever done for you?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you balance independence with wanting closeness?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's something you need to feel secure in a relationship?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you handle a partner who's competitive with your success?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's a quality in a partner that makes you feel proud to be with them?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you like reassurance to be shown, not just said?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's something you wish you worried about less in relationships?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you tell the difference between chemistry and compatibility?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's a deal-breaker you didn't used to have, but do now?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you handle it when a partner forgets something important to you?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's something small a partner does that makes you feel prioritized?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="How do you know when you're ready to introduce someone to your people?", target_gender=QuestionTarget.FEMALE, active=True),
                Question(text="What's one thing you wish you'd known about love earlier?", target_gender=QuestionTarget.FEMALE, active=True),
            ]
            db.add_all(default_questions)
            db.commit()
            logger.info("Seeded %d default questions successfully.", len(default_questions))
        else:
            logger.info("Question pool already seeded with %d questions.", question_count)
    except Exception:
        logger.exception("Error during question seeding in init_db")
        raise
    finally:
        db.close()
