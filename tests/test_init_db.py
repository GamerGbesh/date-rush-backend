from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from app.database import Base, init_db
from app.models.question import Question


def test_init_db_seeds_default_questions():
    # Test engine with fresh in-memory db
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    with patch("app.database.SessionLocal", TestingSession):
        with patch("alembic.command.upgrade"):
            init_db()

            session = TestingSession()
            try:
                count = session.query(Question).count()
                assert count == 12
            finally:
                session.close()

            # Calling init_db again should not duplicate questions
            init_db()
            session = TestingSession()
            try:
                count = session.query(Question).count()
                assert count == 12
            finally:
                session.close()
