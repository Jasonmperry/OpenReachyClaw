"""Configuration for OpenReachyClaw extensions."""

from __future__ import annotations

import os


def get_openclaw_url() -> str:
    return os.environ.get("OPENCLAW_URL", "http://localhost:3000")


def get_webhook_port() -> int:
    return int(os.environ.get("OPENCLAW_CALLBACK_PORT", "8100"))


def get_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required")
    return key


def get_text_model() -> str:
    return os.environ.get("OPENREACHYCLAW_TEXT_MODEL", "gpt-4o")


def get_history_max_messages() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_MAX", "40"))


def get_history_ttl_seconds() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_TTL", "7200"))
