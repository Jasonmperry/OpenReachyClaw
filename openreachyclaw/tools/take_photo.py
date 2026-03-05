"""Simple photo capture tool for Reachy Mini — saves camera frame, no AI."""

import os
import logging
from typing import Any, Dict
from pathlib import Path
from datetime import datetime

import cv2

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

IMAGES_DIR = Path.home() / "rosie_images"


class TakePhoto(Tool):
    """Take a photo with the camera and save it."""

    name = "take_photo"
    description = (
        "Take a photo with the camera and save it. "
        "Use this when someone asks you to take a picture, snap a photo, "
        "or capture what you see. This saves a regular photo without any filters. "
        "For style transformations like 'make me look like a cartoon', use nano_banana instead."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Optional short description of what you're photographing.",
            },
        },
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        desc = (kwargs.get("description") or "").strip()

        logger.info("Tool call: take_photo description=%s", desc[:80] if desc else "none")

        if deps.camera_worker is None:
            return {"error": "Camera not available"}

        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            return {"error": "No frame available from camera"}

        # Save to ~/rosie_images/
        IMAGES_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        filepath = IMAGES_DIR / filename

        success = cv2.imwrite(str(filepath), frame)
        if not success:
            return {"error": "Failed to save photo"}

        logger.info("Saved photo to %s", filepath)

        return {
            "status": "success",
            "filename": filename,
            "message": f"Photo saved! You can see it on the Live tab: {filename}",
        }
