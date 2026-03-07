"""Configuration for OpenReachyClaw extensions."""

from __future__ import annotations

import os


def get_openclaw_url() -> str:
    return os.environ.get("OPENCLAW_URL", "http://localhost:3000")


def get_webhook_port() -> int:
    return int(os.environ.get("OPENCLAW_CALLBACK_PORT", "8100"))


def get_openai_base_url() -> str:
    """Base URL for Chat Completions API. Defaults to OpenAI; set to Ollama for local LLM."""
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


def get_openai_api_key() -> str:
    """API key. Required for OpenAI, optional for Ollama (use any non-empty string)."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        # If using Ollama or another local endpoint, a dummy key is fine.
        base = get_openai_base_url()
        if "localhost" in base or "127.0.0.1" in base:
            return "ollama"
        raise RuntimeError("OPENAI_API_KEY environment variable is required")
    return key


def get_text_model() -> str:
    return os.environ.get("OPENREACHYCLAW_TEXT_MODEL", "gpt-4o")


def get_history_max_messages() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_MAX", "40"))


def get_history_ttl_seconds() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_TTL", "7200"))
