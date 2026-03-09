"""Configuration for OpenReachyClaw extensions.

Centralises all environment-variable lookups with validation and
sensible defaults.  Call ``validate_config()`` at startup to log
warnings about missing optional keys.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Core paths ────────────────────────────────────────────────
def get_data_dir() -> Path:
    """Root data directory for persistent state (memory, faces, logs)."""
    p = Path(os.environ.get("ROSIE_DATA_DIR", str(Path.home() / ".rosie")))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── OpenClaw ──────────────────────────────────────────────────
def get_openclaw_url() -> str:
    return os.environ.get("OPENCLAW_URL", "http://localhost:3000")


def get_webhook_port() -> int:
    return int(os.environ.get("OPENCLAW_CALLBACK_PORT", "8100"))


# ── OpenAI / LLM ─────────────────────────────────────────────
def get_openai_base_url() -> str:
    """Base URL for Chat Completions API. Defaults to OpenAI; set to Ollama for local LLM."""
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


def get_openai_api_key() -> str:
    """API key. Required for OpenAI, optional for Ollama (use any non-empty string)."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        base = get_openai_base_url()
        if "localhost" in base or "127.0.0.1" in base:
            return "ollama"
        raise RuntimeError("OPENAI_API_KEY environment variable is required")
    return key


def get_text_model() -> str:
    return os.environ.get("OPENREACHYCLAW_TEXT_MODEL", "gpt-4o")


def is_using_local_llm() -> bool:
    """True if the text brain is pointed at a local endpoint (Ollama, etc.)."""
    base = get_openai_base_url()
    return "localhost" in base or "127.0.0.1" in base


# ── Conversation history ──────────────────────────────────────
def get_history_max_messages() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_MAX", "40"))


def get_history_ttl_seconds() -> int:
    return int(os.environ.get("OPENREACHYCLAW_HISTORY_TTL", "7200"))


# ── Idle / heartbeat ─────────────────────────────────────────
def get_idle_timeout() -> int:
    """Seconds of inactivity before idle behaviors start."""
    return int(os.environ.get("ROSIE_IDLE_TIMEOUT", "30"))


def get_greeting_cooldown() -> int:
    """Minimum seconds between re-greeting the same person."""
    return int(os.environ.get("ROSIE_GREETING_COOLDOWN", "300"))


# ── Optional API keys ────────────────────────────────────────
def get_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


def get_serpapi_key() -> str:
    return os.environ.get("SERPAPI_KEY", "")


def get_openweather_api_key() -> str:
    return os.environ.get("OPENWEATHER_API_KEY", "")


# ── Startup validation ───────────────────────────────────────
def validate_config() -> dict[str, bool]:
    """Check all integrations and return status dict.  Logs warnings for missing keys."""
    status: dict[str, bool] = {}

    # Required
    try:
        get_openai_api_key()
        status["openai"] = True
    except RuntimeError:
        logger.error("OPENAI_API_KEY is required but not set")
        status["openai"] = False

    # Optional integrations
    optional = {
        "gemini": get_gemini_api_key,
        "serpapi": get_serpapi_key,
        "openweather": get_openweather_api_key,
    }
    for name, getter in optional.items():
        val = getter()
        status[name] = bool(val)
        if not val:
            logger.info("Optional: %s not configured (set %s)", name, name.upper() + "_API_KEY" if name != "openweather" else "OPENWEATHER_API_KEY")

    # Check Twilio
    twilio_vars = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"]
    status["twilio"] = all(os.environ.get(v) for v in twilio_vars)
    if not status["twilio"]:
        logger.info("Optional: Twilio SMS not configured")

    # Check data directory
    data_dir = get_data_dir()
    status["data_dir"] = data_dir.exists()

    # Local vs cloud LLM
    status["local_llm"] = is_using_local_llm()
    logger.info("LLM: %s (model=%s)", "local" if status["local_llm"] else "cloud", get_text_model())

    return status
