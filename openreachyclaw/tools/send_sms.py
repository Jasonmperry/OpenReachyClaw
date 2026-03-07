"""Twilio SMS sending tool for Reachy Mini."""

import logging
import os
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


class SendSMS(Tool):
    """Send an SMS text message via Twilio."""

    name = "send_sms"
    description = (
        "Send an SMS text message to someone's phone. "
        "Use this when someone asks you to text someone, send a message to a number, "
        "or send an SMS. Ask the person for the phone number if they haven't given one. "
        "The number must be in format like +14105551234."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient phone number in E.164 format, e.g. '+14105551234'.",
            },
            "message": {
                "type": "string",
                "description": "The text message to send.",
            },
        },
        "required": ["to", "message"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        to = (kwargs.get("to") or "").strip()
        message = (kwargs.get("message") or "").strip()

        if not to:
            return {"error": "to must be a non-empty phone number"}
        if not message:
            return {"error": "message must be a non-empty string"}

        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
            return {"error": "Twilio environment variables not fully configured"}

        logger.info("Tool call: send_sms to=%s message_len=%d", to, len(message))

        url = (
            f"https://api.twilio.com/2010-04-01"
            f"/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        )

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                    data={
                        "From": TWILIO_FROM_NUMBER,
                        "To": to,
                        "Body": message,
                    },
                )

            resp.raise_for_status()
            data = resp.json()

            return {
                "status": data.get("status", "sent"),
                "to": data.get("to", to),
                "message_sid": data.get("sid", ""),
            }

        except httpx.HTTPStatusError as exc:
            logger.error("Twilio HTTP error: %s", exc)
            try:
                err_body = exc.response.json()
                err_msg = err_body.get("message", str(exc.response.status_code))
            except Exception:
                err_msg = str(exc.response.status_code)
            return {"error": f"Twilio error: {err_msg}"}
        except httpx.RequestError as exc:
            logger.error("Twilio request error: %s", exc)
            return {"error": f"Twilio request failed: {exc}"}
