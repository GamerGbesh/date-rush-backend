"""
Shared fixtures for the test suite.

Each test function receives its own in-memory SQLite database so tests are
fully isolated from each other.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.database import Base, get_db
from app.enums import QuestionTarget
from app.main import app
from app.models.question import Question

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    # Import all models so their tables are registered on Base.metadata.
    import app.models  # noqa: F401

    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db(db_engine):
    """Yield a database session for a single test."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )
    session = TestingSessionLocal()
    try:
        # Seed default pool of active questions for room creation
        default_questions = [
            Question(text=f"Any Question {i}", target_gender=QuestionTarget.ANY, active=True)
            for i in range(1, 6)
        ] + [
            Question(text=f"Male Question {i}", target_gender=QuestionTarget.MALE, active=True)
            for i in range(1, 6)
        ] + [
            Question(text=f"Female Question {i}", target_gender=QuestionTarget.FEMALE, active=True)
            for i in range(1, 6)
        ]
        session.add_all(default_questions)
        session.commit()

        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    """
    Yield a TestClient whose get_db dependency is overridden to use the
    test's isolated in-memory database.

    init_db is patched to a no-op so the lifespan handler does not touch
    the real SQLite file; the test engine already has all tables from the
    db_engine fixture.
    """

    def override_get_db():
        try:
            yield db
        finally:
            pass  # session lifecycle managed by the `db` fixture

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.main.init_db"):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()
