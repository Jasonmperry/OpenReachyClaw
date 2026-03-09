"""Structured logging setup for OpenReachyClaw.

Configures logging with:
- Console output (human-readable)
- File output to ~/.rosie/rosie.log (rotated, for debugging)
- Request ID context for tracing async operations
"""

from __future__ import annotations

import logging
import logging.handlers
import uuid
from contextvars import ContextVar
from pathlib import Path

# Context variable for request tracing across async calls
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """Generate a short request ID for tracing."""
    return uuid.uuid4().hex[:8]


class RequestIdFilter(logging.Filter):
    """Inject request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")  # type: ignore[attr-defined]
        return True


LOG_DIR = Path.home() / ".rosie"
LOG_FILE = LOG_DIR / "rosie.log"

CONSOLE_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] [%(request_id)s] %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the entire application."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Clear any existing handlers
    root.handlers.clear()

    # Request ID filter
    rid_filter = RequestIdFilter()

    # Console handler — human-readable
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    console.addFilter(rid_filter)
    root.addHandler(console)

    # File handler — rotated, more detail
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    file_handler.addFilter(rid_filter)
    root.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — console + file (%s)", LOG_FILE
    )
