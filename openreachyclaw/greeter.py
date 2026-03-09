"""Presence greeting system for Rosie.

Detects motion in front of the camera using simple frame differencing
(no ML — suitable for 8 GB Jetson Nano) and greets visitors by name
when possible, using OpenAI Vision to match faces against the memory
store.  Every detection is logged to a security folder with a photo.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

import cv2
import httpx
import numpy as np

from openreachyclaw.memory import MemoryStore

logger = logging.getLogger(__name__)

# Directory for security snapshots.
SECURITY_DIR = Path.home() / ".rosie" / "faces" / "security"

# Cooldown — don't re-greet the same person within this window.
GREET_COOLDOWN_SECONDS = 5 * 60  # 5 minutes

# Frame-differencing threshold: mean absolute difference of pixel values
# above which we consider "something changed" in front of the camera.
MOTION_THRESHOLD = 25.0

# Minimum fraction of the frame that must differ to count as motion,
# to ignore sensor noise on the Jetson camera.
MOTION_PIXEL_FRACTION = 0.02

# JPEG quality for saved snapshots (keep files small on the Nano).
JPEG_QUALITY = 80


@dataclass
class GreetingResult:
    """Outcome of a single presence-check cycle."""

    person_detected: bool
    identified: bool
    name: str | None
    greeting_text: str | None
    photo_path: str | None


class PresenceGreeter:
    """Watches the camera for motion and greets visitors.

    Parameters
    ----------
    camera_frame_getter:
        Callable that returns the latest camera frame as a numpy array
        (BGR, uint8) or ``None`` if no frame is available.
    tool_dispatcher:
        Async callable ``(name, args_json, deps) -> result`` used to
        invoke robot tools (not used directly by the greeter today but
        kept for future actions like waving).
    memory_store:
        The shared :class:`MemoryStore` instance for face and fact
        look-ups.
    speech_callback:
        Optional async callable that speaks a string aloud via TTS.
    motion_threshold:
        Mean absolute pixel difference required to trigger detection.
    """

    def __init__(
        self,
        camera_frame_getter: Callable[[], np.ndarray | None],
        tool_dispatcher: Callable[..., Awaitable[Any]],
        memory_store: MemoryStore,
        speech_callback: Callable[[str], Awaitable[None]] | None = None,
        *,
        motion_threshold: float = MOTION_THRESHOLD,
    ) -> None:
        self._get_frame = camera_frame_getter
        self._dispatch = tool_dispatcher
        self._memory = memory_store
        self._speak = speech_callback
        self._motion_threshold = motion_threshold

        # Previous frame for motion detection (grayscale).
        self._prev_gray: np.ndarray | None = None

        # Per-person cooldown tracker: name -> last greeting monotonic time.
        self._last_greeted: dict[str, float] = {}

        # Ensure the security snapshot directory exists.
        SECURITY_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_and_greet(self) -> GreetingResult:
        """Run one detection + greeting cycle.

        Intended to be called periodically by the heartbeat system.

        Returns a :class:`GreetingResult` describing what happened.
        """
        frame = self._get_frame()
        if frame is None:
            return GreetingResult(
                person_detected=False,
                identified=False,
                name=None,
                greeting_text=None,
                photo_path=None,
            )

        # --- Motion detection (lightweight) ---
        if not self._detect_motion(frame):
            return GreetingResult(
                person_detected=False,
                identified=False,
                name=None,
                greeting_text=None,
                photo_path=None,
            )

        logger.info("Motion detected — capturing snapshot for identification")

        # --- Save security snapshot ---
        photo_path = self._save_security_photo(frame)

        # --- Try to identify the person ---
        name, confidence = await self._identify_person(frame)
        identified = name is not None

        # --- Log sighting in memory store ---
        await self._log_sighting(name, photo_path, confidence)

        # --- Build greeting ---
        greeting_text: str | None = None

        if identified:
            assert name is not None
            if self._is_on_cooldown(name):
                logger.debug("Skipping greeting for %s (cooldown active)", name)
                return GreetingResult(
                    person_detected=True,
                    identified=True,
                    name=name,
                    greeting_text=None,
                    photo_path=str(photo_path),
                )

            greeting_text = await self._build_personalised_greeting(name)
            self._last_greeted[name] = time.monotonic()
        else:
            # Unknown person — only greet if we haven't greeted an unknown
            # person recently (use sentinel key).
            if not self._is_on_cooldown("__unknown__"):
                greeting_text = (
                    "Hey there! I don't think we've met. What's your name?"
                )
                self._last_greeted["__unknown__"] = time.monotonic()

        # --- Speak the greeting aloud ---
        if greeting_text and self._speak is not None:
            try:
                await self._speak(greeting_text)
            except Exception:
                logger.exception("Speech callback failed")

        return GreetingResult(
            person_detected=True,
            identified=identified,
            name=name,
            greeting_text=greeting_text,
            photo_path=str(photo_path),
        )

    # ------------------------------------------------------------------
    # Motion detection
    # ------------------------------------------------------------------

    def _detect_motion(self, frame: np.ndarray) -> bool:
        """Return ``True`` if the frame differs significantly from the last.

        Uses mean absolute difference on down-scaled grayscale frames to
        keep CPU usage low on the Jetson Nano.
        """
        # Down-scale for speed (quarter resolution is plenty for motion).
        small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return False

        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray

        # Count pixels that changed more than the threshold.
        changed = (diff > self._motion_threshold).sum()
        total = diff.size
        fraction = changed / total

        if fraction >= MOTION_PIXEL_FRACTION:
            logger.debug(
                "Motion: %.2f%% pixels changed (threshold %.2f%%)",
                fraction * 100,
                MOTION_PIXEL_FRACTION * 100,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Security photo
    # ------------------------------------------------------------------

    def _save_security_photo(self, frame: np.ndarray) -> Path:
        """Save a timestamped JPEG to the security directory."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = SECURITY_DIR / f"{ts}.jpg"
        cv2.imwrite(
            str(path),
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
        )
        logger.info("Security photo saved: %s", path)
        return path

    # ------------------------------------------------------------------
    # Face identification via OpenAI Vision
    # ------------------------------------------------------------------

    async def _identify_person(
        self, frame: np.ndarray
    ) -> tuple[str | None, float]:
        """Use OpenAI Vision to match *frame* against known faces.

        Returns ``(name, confidence)`` or ``(None, 0.0)`` if no match.
        """
        people = await self._memory.get_all_people()
        if not people:
            logger.debug("No people in memory store — skipping identification")
            return None, 0.0

        # Gather one reference photo per person.
        reference_images: list[dict[str, Any]] = []
        for person in people:
            sightings = await self._memory.get_face_sightings(
                person["id"], limit=1
            )
            if not sightings:
                continue
            ref_path = sightings[0]["image_path"]
            ref_b64 = _encode_image_file(ref_path)
            if ref_b64 is None:
                continue
            reference_images.append(
                {"name": person["name"], "image_b64": ref_b64}
            )

        if not reference_images:
            logger.debug("No reference photos available for matching")
            return None, 0.0

        # Encode the current frame.
        current_b64 = _encode_frame(frame)

        # Build the Vision API request.
        names_list = ", ".join(r["name"] for r in reference_images)

        # System message.
        system_text = (
            "You are a face-matching assistant. You will be shown a set of "
            "labelled reference photos followed by a new photo. Determine "
            "which person (if any) appears in the new photo. Respond with "
            "ONLY a JSON object: {\"name\": \"<name>\", \"confidence\": <0-1>} "
            "or {\"name\": null, \"confidence\": 0} if no match."
        )

        # Build content blocks: reference images first, then the query image.
        content: list[dict[str, Any]] = []
        for ref in reference_images:
            content.append({"type": "text", "text": f"Reference — {ref['name']}:"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{ref['image_b64']}",
                        "detail": "low",
                    },
                }
            )

        content.append({"type": "text", "text": "New photo — who is this?"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{current_b64}",
                    "detail": "low",
                },
            }
        )

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": content},
        ]

        try:
            result = await _call_openai_vision(messages)
        except Exception:
            logger.exception("Vision API call failed during identification")
            return None, 0.0

        # Parse the response.
        name = result.get("name")
        confidence = float(result.get("confidence", 0))

        if name and confidence >= 0.5:
            logger.info("Identified %s (confidence %.2f)", name, confidence)
            return name, confidence

        logger.info("No confident match (best: %s @ %.2f)", name, confidence)
        return None, 0.0

    # ------------------------------------------------------------------
    # Memory logging
    # ------------------------------------------------------------------

    async def _log_sighting(
        self,
        name: str | None,
        photo_path: Path,
        confidence: float,
    ) -> None:
        """Record the sighting in the memory store."""
        now_iso = datetime.now().isoformat()

        if name:
            person_id = await self._memory.add_person(name)
            await self._memory.add_face_sighting(
                person_id, str(photo_path), confidence=confidence
            )
            await self._memory.remember(
                subject=name,
                fact=f"Seen at {now_iso}",
                category="sighting",
            )
        else:
            # Unrecognised person — flag for review.
            await self._memory.remember(
                subject="security",
                fact=(
                    f"Unrecognised person detected at {now_iso}. "
                    f"Photo: {photo_path}. Flagged for review."
                ),
                category="security_alert",
            )

    # ------------------------------------------------------------------
    # Personalised greeting
    # ------------------------------------------------------------------

    async def _build_personalised_greeting(self, name: str) -> str:
        """Create a warm greeting using stored memories about *name*."""
        memories = await self._memory.recall(name)

        # Filter out bare sighting records to find interesting facts.
        facts = [
            m["fact"]
            for m in memories
            if m.get("category") != "sighting" and "Seen at" not in m["fact"]
        ]

        if facts:
            # Pick the most recent non-sighting fact for a personal touch.
            latest_fact = facts[0]
            return f"Hey {name}! Good to see you again. {latest_fact}"

        return f"Hey {name}! Good to see you!"

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------

    def _is_on_cooldown(self, name: str) -> bool:
        last = self._last_greeted.get(name)
        if last is None:
            return False
        return (time.monotonic() - last) < GREET_COOLDOWN_SECONDS


# ======================================================================
# Module-level helpers
# ======================================================================


def _encode_frame(frame: np.ndarray) -> str:
    """Encode a BGR numpy frame to a base64 JPEG string."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("Failed to encode frame to JPEG")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _encode_image_file(path: str) -> str | None:
    """Read an image file and return its base64 JPEG encoding, or None."""
    p = Path(path)
    if not p.exists():
        logger.warning("Reference image not found: %s", path)
        return None
    frame = cv2.imread(str(p))
    if frame is None:
        logger.warning("Could not decode reference image: %s", path)
        return None
    return _encode_frame(frame)


async def _call_openai_vision(messages: list[dict]) -> dict:
    """Send a Vision request to the OpenAI-compatible endpoint.

    Returns the parsed JSON object from the assistant's reply.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    ) as client:
        resp = await client.post(
            "/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": messages,
                "max_tokens": 100,
            },
        )
        resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()

    # The model should return bare JSON, but strip markdown fences if present.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    import json

    return json.loads(text)
