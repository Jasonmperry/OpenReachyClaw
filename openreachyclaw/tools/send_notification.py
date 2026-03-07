"""Tool for sending messages to Slack, Discord, or email via OpenClaw gateway."""

import logging
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

# OpenClaw gateway URL (Docker sidecar)
import os
OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://localhost:3000")


class SendMessage(Tool):
    """Send a text message to someone on Slack, Discord, or email."""

    name = "send_message"
    description = (
        "Send a text message to someone on a specific channel like Slack, Discord, "
        "or email. Use this when someone asks you to message another person, relay "
        "information, or send a notification."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "The channel to send on: 'slack', 'discord', or 'email'.",
            },
            "recipient": {
                "type": "string",
                "description": "Who to send the message to (username, handle, or email address).",
            },
            "text": {
                "type": "string",
                "description": "The message text to send.",
            },
        },
        "required": ["channel", "recipient", "text"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        channel = kwargs.get("channel", "").strip()
        recipient = kwargs.get("recipient", "").strip()
        text = kwargs.get("text", "").strip()

        if not all([channel, recipient, text]):
            return {"error": "Need channel, recipient, and text."}

        logger.info("Sending message to %s on %s: %s", recipient, channel, text[:80])

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{OPENCLAW_URL}/api/send",
                    json={"channel": channel, "recipient": recipient, "text": text},
                )
                if resp.status_code == 200:
                    return {"status": "sent", "channel": channel, "recipient": recipient}
                else:
                    return {"error": f"OpenClaw returned {resp.status_code}: {resp.text[:200]}"}
        except httpx.ConnectError:
            return {"error": "OpenClaw gateway is not running. Start it with: docker compose up -d"}
        except Exception as e:
            return {"error": f"Failed to send: {e}"}
