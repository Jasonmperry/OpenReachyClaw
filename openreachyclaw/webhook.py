"""FastAPI webhook server — receives inbound messages from OpenClaw."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from openreachyclaw.config import get_webhook_port

if TYPE_CHECKING:
    from openreachyclaw.text_brain import TextBrain

logger = logging.getLogger(__name__)

app = FastAPI(title="OpenReachyClaw Webhook")


class IncomingMessage(BaseModel):
    channel: str
    sender: str
    text: str
    display_name: str = ""
    thread_id: str = ""


class OutgoingReply(BaseModel):
    reply: str


# The text brain is injected at startup via set_text_brain().
_text_brain: TextBrain | None = None


def set_text_brain(brain: TextBrain) -> None:
    global _text_brain
    _text_brain = brain


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/incoming", response_model=OutgoingReply)
async def incoming(msg: IncomingMessage):
    if _text_brain is None:
        logger.error("Text brain not initialised — dropping message from %s", msg.sender)
        return OutgoingReply(reply="Sorry, I'm not ready yet. Try again in a moment.")

    logger.info("[%s] %s: %s", msg.channel, msg.display_name or msg.sender, msg.text)
    reply = await _text_brain.handle_message(
        channel=msg.channel,
        sender=msg.sender,
        display_name=msg.display_name or msg.sender,
        text=msg.text,
        thread_id=msg.thread_id,
    )
    return OutgoingReply(reply=reply)


async def start_webhook_server() -> asyncio.Task:
    """Start the webhook server in the background and return its task."""
    port = get_webhook_port()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    logger.info("Webhook server starting on port %d", port)
    return task
