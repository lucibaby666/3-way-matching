"""
Structured JSON logging for Azure Container Apps.

Every application event is emitted as a single-line JSON
object on stdout, which Azure Container Apps ships to
Log Analytics as ContainerAppConsoleLogs_CL. The stable
"event" field makes it possible to build KQL queries and
log alerts (for example on "run_failed").

Example line:

    {"timestamp": "2026-08-25T10:00:00.000000+00:00",
     "level": "ERROR",
     "logger": "app.api.pipeline",
     "message": "run_failed",
     "event": "run_failed",
     "run_id": "...",
     "upload_id": "...",
     "error_type": "OSError",
     "error_message": "..."}

Existing human-readable logs and prints elsewhere are
intentionally left untouched.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """
    Format one log record as one single-line JSON object.
    Fields passed via extra={"props": {...}} are merged at
    the top level so they are directly queryable.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        )

        payload: dict[str, Any] = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        props = getattr(record, "props", None)

        if isinstance(props, dict):
            payload.update(props)

        if record.exc_info:
            payload["exc_info"] = self.formatException(
                record.exc_info
            )

        return json.dumps(payload, default=str)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """
    Emit one structured event. The event name is stable and
    meant for alerting; arbitrary fields ride along.
    """

    logger.log(
        level,
        event,
        extra={"props": {"event": event, **fields}},
    )


def configure_structured_logging(
    level: int = logging.INFO,
) -> None:
    """
    Attach the JSON handler to the root logger exactly once.
    Safe to call multiple times (idempotent).
    """

    root = logging.getLogger()

    for handler in root.handlers:
        if isinstance(handler.formatter, JsonFormatter):
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    if root.level > level or root.level == 0:
        root.setLevel(level)
