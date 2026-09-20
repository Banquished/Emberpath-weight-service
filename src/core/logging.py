import json
import logging
import traceback
from contextvars import ContextVar
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
APPLICATION_LOGGER_NAME = "src"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            exception_type, _, exception_traceback = record.exc_info
            payload["exception"] = {
                "type": exception_type.__name__,
                "frames": [
                    {
                        "file": frame.filename,
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(exception_traceback)
                ],
            }
        return json.dumps(payload, default=str)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_context.get()
        return True


def configure_logging(log_level: str) -> None:
    application_logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    application_logger.setLevel(log_level)
    application_logger.propagate = False
    if application_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(JsonFormatter())
    application_logger.addHandler(handler)
