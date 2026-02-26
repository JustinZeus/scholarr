from __future__ import annotations

import json
import logging
import re
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.logging_config import ConsoleLogFormatter, JsonLogFormatter, parse_redact_fields
from app.logging_utils import structured_log
from app.main import app
from app.http.middleware import REQUEST_ID_HEADER, parse_skip_paths


def test_json_log_formatter_redacts_sensitive_fields() -> None:
    formatter = JsonLogFormatter(redact_fields=parse_redact_fields("api_key"))
    record = logging.makeLogRecord(
        {
            "name": "tests.logging",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "test.event",
            "args": (),
            "password": "very-secret",
            "payload": {
                "csrf_token": "token-value",
                "safe": "ok",
            },
            "color_message": "ANSI-noise",
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "test.event"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z", payload["timestamp"])
    assert payload["password"] == "[REDACTED]"
    assert payload["payload"]["csrf_token"] == "[REDACTED]"
    assert payload["payload"]["safe"] == "ok"
    assert "color_message" not in payload


def test_request_logging_middleware_sets_request_id_header(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database", AsyncMock(return_value=True))
    client = TestClient(app)
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "request-123"})
    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "request-123"


def test_parse_skip_paths_trims_and_discards_empty_segments() -> None:
    assert parse_skip_paths(" /healthz , , /api/v1/metrics ") == (
        "/healthz",
        "/api/v1/metrics",
    )


# --- structured_log tests ---


def _capture_structured_log(caplog, level, event, **fields):
    """Helper: call structured_log and return the captured LogRecord."""
    logger = logging.getLogger("tests.structured")
    with caplog.at_level(logging.DEBUG, logger="tests.structured"):
        structured_log(logger, level, event, **fields)
    return caplog.records[-1]


def test_structured_log_json_formatter_uses_event_as_message(caplog) -> None:
    record = _capture_structured_log(caplog, "info", "ingestion.run_started", user_id=42)
    formatter = JsonLogFormatter(redact_fields=set())
    payload = json.loads(formatter.format(record))

    assert payload["event"] == "ingestion.run_started"
    assert payload["user_id"] == 42


def test_structured_log_console_formatter(caplog) -> None:
    record = _capture_structured_log(caplog, "warning", "export.failed", scholar_id=7)
    formatter = ConsoleLogFormatter(redact_fields=set())
    output = formatter.format(record)

    assert "export.failed" in output
    assert "scholar_id=7" in output


def test_structured_log_strips_metric_fields(caplog) -> None:
    record = _capture_structured_log(
        caplog,
        "info",
        "scrape.complete",
        metric_name="articles_scraped",
        metric_value=15,
        scholar_id=3,
    )
    formatter = JsonLogFormatter(redact_fields=set())
    payload = json.loads(formatter.format(record))

    assert "metric_name" not in payload
    assert "metric_value" not in payload
    assert payload["scholar_id"] == 3


def test_structured_log_extra_fields_in_output(caplog) -> None:
    record = _capture_structured_log(
        caplog,
        "info",
        "scholar.created",
        user_id=1,
        scholar_id=99,
        scholar_name="Ada Lovelace",
    )
    formatter = JsonLogFormatter(redact_fields=set())
    payload = json.loads(formatter.format(record))

    assert payload["event"] == "scholar.created"
    assert payload["user_id"] == 1
    assert payload["scholar_id"] == 99
    assert payload["scholar_name"] == "Ada Lovelace"
