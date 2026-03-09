"""Shared vision utilities — face identification via OpenAI Vision API.

Used by both the face tools (interactive) and the greeter (background).
Keeps the API call logic in one place.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import cv2
import httpx

from openreachyclaw.config import get_openai_api_key, get_openai_base_url, is_using_local_llm

logger = logging.getLogger(__name__)


async def identify_person_in_frame(
    frame: Any,
    known_people: list[dict],
    max_references: int = 5,
) -> dict | None:
    """Try to identify a person in a camera frame against known face photos.

    Args:
        frame: numpy array (BGR) from the camera
        known_people: list of dicts with 'name' and 'reference_photo' keys
        max_references: max number of reference photos to send to the API

    Returns:
        dict with 'identified', 'name', 'confidence_text' keys, or None on failure.
    """
    if is_using_local_llm():
        return None  # Vision API not available with Ollama

    api_key = get_openai_api_key()
    base_url = get_openai_base_url()

    if not api_key or api_key == "ollama":
        return None

    # Encode current frame
    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not success:
        return None

    current_b64 = base64.b64encode(buffer.tobytes()).decode("utf-8")

    # Build message with current photo + reference photos
    content: list[dict] = [
        {"type": "text", "text": (
            "I'm a robot trying to identify who is in front of my camera. "
            "The FIRST image is what I currently see. The remaining images are "
            "reference photos of people I know, labelled with their names. "
            "Tell me which person (if any) matches the person in the first image. "
            "If you can't tell or no one matches, say 'unknown'. "
            "Respond with ONLY the person's name or 'unknown'."
        )},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{current_b64}", "detail": "low"},
        },
    ]

    for person in known_people[:max_references]:
        ref_path = Path(person["reference_photo"])
        if not ref_path.exists():
            continue
        ref_bytes = ref_path.read_bytes()
        ref_b64 = base64.b64encode(ref_bytes).decode("utf-8")
        content.append(
            {"type": "text", "text": f"Reference photo — this is {person['name']}:"}
        )
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{ref_b64}", "detail": "low"},
        })

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        ) as client:
            resp = await client.post("/chat/completions", json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 50,
            })
            resp.raise_for_status()
            data = resp.json()

        answer = data["choices"][0]["message"]["content"].strip()
        logger.info("Vision identification result: %s", answer)

        # Check if the answer matches any known person
        answer_lower = answer.lower()
        for person in known_people:
            if person["name"].lower() in answer_lower:
                return {
                    "identified": True,
                    "name": person["name"],
                    "confidence_text": answer,
                }

        return {
            "identified": False,
            "name": None,
            "confidence_text": answer,
        }

    except Exception as exc:
        logger.warning("Vision identification failed: %s", exc)
        return None


async def describe_scene(frame: Any) -> str | None:
    """Get a brief description of what the camera sees.

    Returns a short string like "a person sitting at a desk" or None on failure.
    """
    if is_using_local_llm():
        return None

    api_key = get_openai_api_key()
    base_url = get_openai_base_url()

    if not api_key or api_key == "ollama":
        return None

    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    if not success:
        return None

    b64 = base64.b64encode(buffer.tobytes()).decode("utf-8")

    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        ) as client:
            resp = await client.post("/chat/completions", json={
                "model": "gpt-4o",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "Briefly describe what you see in this image in one sentence. "
                            "Focus on people if present. Be concise."
                        )},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
                    ],
                }],
                "max_tokens": 60,
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("Scene description failed: %s", exc)
        return None
