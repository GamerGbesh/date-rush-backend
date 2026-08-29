"""
Unit tests for logging configuration and HTTP request/response logging middleware.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.logging_config import setup_logging
from app.main import app


def test_setup_logging_configures_root_logger():
    """Verify setup_logging sets root logger level and adds stream handler."""
    setup_logging(log_level="DEBUG")
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) >= 1
    assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    # Reconfigure back to INFO
    setup_logging(log_level="INFO")
    assert root_logger.level == logging.INFO


def test_request_logging_middleware_logs_request_and_response(client, caplog):
    """Verify HTTP requests produce log output via log_requests_middleware."""
    with caplog.at_level(logging.INFO, logger="app.main"):
        response = client.get("/health")
        assert response.status_code == 200

    # Check that both incoming and completed logs were emitted
    logs = [rec.message for rec in caplog.records if rec.name == "app.main"]
    assert any("--> GET /health" in msg for msg in logs)
    assert any("<-- GET /health [200]" in msg for msg in logs)


def test_request_logging_middleware_logs_exception(client, caplog):
    """Verify unhandled route exceptions are logged with traceback."""
    with patch("app.api.admin.question_service.list_questions", side_effect=RuntimeError("Simulated server crash")):
        with caplog.at_level(logging.ERROR, logger="app.main"):
            with pytest.raises(RuntimeError, match="Simulated server crash"):
                client.get("/admin/questions")

    logs = [rec.message for rec in caplog.records if rec.name == "app.main"]
    assert any("unhandled exception" in msg for msg in logs)


def test_settings_log_level():
    """Verify default Settings contains LOG_LEVEL."""
    s = Settings()
    assert hasattr(s, "LOG_LEVEL")
    assert s.LOG_LEVEL == "INFO"
