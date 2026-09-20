import json
import logging
import sys

import pytest
from sqlalchemy.exc import StatementError

from src.core.logging import JsonFormatter


@pytest.mark.parametrize("kind", ["value", "database", "chained", "group"])
def test_exception_logs_keep_locations_without_private_values(kind):
    secret = "private-measurement-101.25"
    try:
        if kind == "database":
            raise StatementError(
                "Failing row contains " + secret,
                "INSERT INTO logs VALUES (:weight)",
                {"weight": secret},
                ValueError(secret),
            )
        if kind == "chained":
            try:
                raise ValueError(secret)
            except ValueError as error:
                raise RuntimeError(secret) from error
        if kind == "group":
            raise ExceptionGroup(secret, [ValueError(secret)])
        raise ValueError(secret)
    except Exception:
        record = logging.LogRecord(
            "src.test",
            logging.ERROR,
            __file__,
            1,
            "unhandled_exception",
            (),
            sys.exc_info(),
        )
    output = JsonFormatter().format(record)
    payload = json.loads(output)
    assert secret not in output
    assert "INSERT" not in output
    assert payload["message"] == "unhandled_exception"
    assert payload["exception"]["type"]
    assert (
        payload["exception"]["frames"][-1]["function"]
        == "test_exception_logs_keep_locations_without_private_values"
    )
    assert payload["exception"]["frames"][-1]["line"] > 0
