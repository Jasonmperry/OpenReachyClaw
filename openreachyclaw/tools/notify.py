"""Tools for sending messages and photos to text channels via OpenClaw."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# OpenAI function-calling schema for these tools.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "send_message_to_channel",
            "description": (
                "Send a text message to someone on a specific channel "
                "(Slack, Discord, Telegram, or email). Use this when someone "
                "asks you to message another person, or to relay information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "The channel to send on (e.g. 'slack', 'discord', 'email').",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Who to send the message to (username or email).",
                    },
                    "text": {
                        "type": "string",
                        "description": "The message text to send.",
                    },
                },
                "required": ["channel", "recipient", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_photo_to_channel",
            "description": (
                "Send a photo with an optional caption to someone on a channel. "
                "Use this after taking a photo with the camera tool when the user "
                "wants to share it on Slack, Discord, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "The channel to send on (e.g. 'slack', 'discord', 'email').",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Who to send the photo to (username or email).",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Path to the image file to send.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption for the photo.",
                        "default": "",
                    },
                },
                "required": ["channel", "recipient", "image_path"],
            },
        },
    },
]


class NotifyTools:
    """Executes notification tool calls using the OpenClaw bridge."""

    def __init__(self, openclaw_bridge: Any):
        self.bridge = openclaw_bridge

    async def execute(self, name: str, args: dict) -> str:
        if name == "send_message_to_channel":
            return await self._send_message(args)
        elif name == "send_photo_to_channel":
            return await self._send_photo(args)
        return json.dumps({"error": f"Unknown notify tool: {name}"})

    async def _send_message(self, args: dict) -> str:
        channel = args["channel"]
        recipient = args["recipient"]
        text = args["text"]

        ok = await self.bridge.send_text(channel, recipient, text)
        if ok:
            logger.info("Sent message to %s on %s", recipient, channel)
            return json.dumps({"status": "sent", "channel": channel, "recipient": recipient})
        return json.dumps({"error": f"Failed to send message to {recipient} on {channel}"})

    async def _send_photo(self, args: dict) -> str:
        channel = args["channel"]
        recipient = args["recipient"]
        image_path = args["image_path"]
        caption = args.get("caption", "")

        ok = await self.bridge.send_photo(channel, recipient, image_path, caption)
        if ok:
            logger.info("Sent photo to %s on %s", recipient, channel)
            return json.dumps({"status": "sent", "channel": channel, "recipient": recipient})
        return json.dumps({"error": f"Failed to send photo to {recipient} on {channel}"})
