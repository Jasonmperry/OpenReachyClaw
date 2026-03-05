"""Nano Banana — AI image style transfer via Gemini API for Reachy Mini."""

import os
import base64
import logging
from typing import Any, Dict
from pathlib import Path
from datetime import datetime

import cv2
import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent"
IMAGES_DIR = Path.home() / "rosie_images"


class NanoBanana(Tool):
    """Take a photo and apply an AI style transformation using Gemini."""

    name = "nano_banana"
    description = (
        "Take a photo with the camera and transform it with an AI style. "
        "Use when someone asks to take a picture and apply a style, filter, or transformation. "
        "Examples: 'make me look like a cartoon', 'turn me into a superhero', "
        "'make this look like a painting', 'take a fun photo of me'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "The style or transformation to apply to the photo. "
                    "E.g. 'make this person look like a cartoon character' "
                    "or 'turn this into a watercolor painting'."
                ),
            },
        },
        "required": ["prompt"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return {"error": "prompt must be a non-empty string"}

        if not GEMINI_API_KEY:
            return {"error": "GEMINI_API_KEY environment variable not set"}

        logger.info("Tool call: nano_banana prompt=%s", prompt[:120])

        # Get frame from camera
        if deps.camera_worker is None:
            return {"error": "Camera not available"}

        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            return {"error": "No frame available from camera"}

        # Encode frame to JPEG base64
        success, buffer = cv2.imencode(".jpg", frame)
        if not success:
            return {"error": "Failed to encode camera frame"}

        b64_image = base64.b64encode(buffer.tobytes()).decode("utf-8")

        # Call Gemini API
        url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_image,
                            }
                        },
                        {"text": f"Transform this photo: {prompt}"},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Gemini HTTP error: %s", exc)
            return {"error": f"Gemini API error: {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.error("Gemini request error: %s", exc)
            return {"error": f"Gemini request failed: {exc}"}

        # Extract generated image from response
        generated_b64 = None
        response_text = ""
        candidates = data.get("candidates", [])
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if "inline_data" in part:
                    generated_b64 = part["inline_data"]["data"]
                if "text" in part:
                    response_text = part["text"]

        if not generated_b64:
            return {
                "error": "Gemini did not return an image",
                "text": response_text or "No response text",
            }

        # Save to ~/rosie_images/
        IMAGES_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"nanobanan_{timestamp}.jpg"
        filepath = IMAGES_DIR / filename

        image_bytes = base64.b64decode(generated_b64)
        filepath.write_bytes(image_bytes)
        logger.info("Saved nano_banana image to %s", filepath)

        return {
            "status": "success",
            "filename": filename,
            "text": response_text,
            "message": f"I created a styled image! Check it out on the Live tab: {filename}",
        }
