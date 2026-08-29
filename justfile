dev:
    uv run uvicorn app.main:app --reload

test:
    uv run pytest

test-v:
    uv run pytest -v

migrate:
    uv run alembic upgrade head

seed:
    uv run python scripts/seed_questions.py

manual-test:
    uv run python scripts/manual_test_e2e.py

manual-test-ws:
    uv run python scripts/manual_test_websockets.py

manual-test-all:
    uv run python scripts/manual_test_e2e.py
    uv run python scripts/manual_test_websockets.py
