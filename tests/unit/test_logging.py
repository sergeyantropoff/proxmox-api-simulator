from __future__ import annotations

import json
import logging

from app.logging import JsonFormatter


def test_json_formatter_emits_structured_fields() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.request_id = "request-1"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello world"
    assert payload["request_id"] == "request-1"
    assert payload["level"] == "INFO"
