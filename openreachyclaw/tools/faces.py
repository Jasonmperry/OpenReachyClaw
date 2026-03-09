"""Face learning and recognition tools for Reachy Mini.

Uses the camera to capture face photos and associates them with people.
On the Jetson Nano (8GB), we avoid heavy local models and instead:
  - Store face photos locally with person associations
  - Use OpenAI Vision API for identification when available
  - Fall back to simple photo-based lookup

Face embeddings can be computed later if a face_recognition library
is installed, but the core flow works without it.
"""

import base64
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import cv2

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

from openreachyclaw.memory import get_memory_store

logger = logging.getLogger(__name__)

FACES_DIR = Path.home() / ".rosie" / "faces"


class LearnFace(Tool):
    """Learn what someone looks like by taking their photo."""

    name = "learn_face"
    description = (
        "Take a photo of someone and remember what they look like. "
        "Use this when someone introduces themselves or says 'remember my face', "
        "'learn what I look like', or 'this is [name]'. "
        "You must be able to see them through your camera. "
        "This helps you recognise people later."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name to associate with their face.",
            },
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        name = kwargs.get("name", "").strip()
        if not name:
            return {"error": "I need a name to associate with the face."}

        if deps.camera_worker is None:
            return {"error": "Camera not available — I can't see right now."}

        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            return {"error": "No frame available from camera."}

        # Save face photo
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
        filename = f"face_{safe_name}_{timestamp}.jpg"
        filepath = FACES_DIR / filename

        success = cv2.imwrite(str(filepath), frame)
        if not success:
            return {"error": "Failed to save face photo."}

        # Register in memory store
        store = get_memory_store()
        person_id = await store.add_person(name)
        await store.add_face_sighting(person_id, str(filepath))

        # Also remember this as a fact
        await store.remember(
            name, f"Face photo saved on {timestamp}. Photo: {filename}", "face"
        )

        face_count = len(await store.get_face_sightings(person_id))
        logger.info("Learned face for %s (person_id=%d, total=%d photos)", name, person_id, face_count)

        return {
            "status": "success",
            "person": name,
            "filename": filename,
            "total_photos": face_count,
            "message": (
                f"Got it! I've saved a photo of {name}. "
                f"I now have {face_count} photo(s) of them. "
                f"I'll try to recognise them next time!"
            ),
        }


class WhoIsThis(Tool):
    """Try to identify who the camera is looking at."""

    name = "who_is_this"
    description = (
        "Look at the person in front of the camera and try to identify them "
        "based on previously learned faces. Use this when someone asks "
        "'do you know who I am?', 'who am I?', 'recognise me', or "
        "'who is in front of you?'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        if deps.camera_worker is None:
            return {"error": "Camera not available — I can't see right now."}

        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            return {"error": "No frame available from camera."}

        store = get_memory_store()
        people = await store.get_all_people()

        if not people:
            return {
                "known_people": [],
                "message": (
                    "I don't know anyone yet! Tell me your name and I'll "
                    "learn your face with the learn_face tool."
                ),
            }

        # Collect reference photos for each person
        people_with_faces = []
        for person in people:
            sightings = await store.get_face_sightings(person["id"], limit=1)
            if sightings:
                people_with_faces.append({
                    "name": person["name"],
                    "reference_photo": sightings[0]["image_path"],
                })

        if not people_with_faces:
            return {
                "known_people": [p["name"] for p in people],
                "message": "I know some people by name but don't have face photos for them.",
            }

        # Try OpenAI Vision API for identification
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

        # Only use vision API with actual OpenAI (not Ollama)
        if api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
            result = await self._identify_with_vision(
                frame, people_with_faces, api_key, base_url
            )
            if result:
                return result

        # Fallback: return list of known people and let the LLM ask
        return {
            "known_people": [p["name"] for p in people_with_faces],
            "message": (
                f"I can see someone but I'm not sure who it is. "
                f"I know {len(people_with_faces)} people: "
                f"{', '.join(p['name'] for p in people_with_faces)}. "
                f"Could you tell me your name?"
            ),
        }

    async def _identify_with_vision(
        self,
        current_frame: Any,
        known_people: list[dict],
        api_key: str,
        base_url: str,
    ) -> dict | None:
        """Use OpenAI Vision to compare current camera frame against known faces."""
        import httpx

        # Encode current frame
        success, buffer = cv2.imencode(".jpg", current_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
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

        for person in known_people[:5]:  # Limit to 5 reference photos
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

            answer = data["choices"][0]["message"]["content"].strip().lower()
            logger.info("Vision identification result: %s", answer)

            # Check if the answer matches any known person
            for person in known_people:
                if person["name"].lower() in answer:
                    # Load their memories
                    store = get_memory_store()
                    memories = await store.recall(person["name"])
                    memory_facts = [
                        m["fact"] for m in memories
                        if m.get("category") != "face"
                    ]

                    return {
                        "identified": True,
                        "name": person["name"],
                        "memories": memory_facts[:10],
                        "message": (
                            f"I recognise {person['name']}! "
                            + (f"Here's what I remember about them: {'; '.join(memory_facts[:5])}"
                               if memory_facts else "")
                        ),
                    }

            return {
                "identified": False,
                "known_people": [p["name"] for p in known_people],
                "message": (
                    "I can see someone but they don't match anyone I know. "
                    "Want to tell me your name so I can learn your face?"
                ),
            }

        except Exception as exc:
            logger.warning("Vision identification failed: %s", exc)
            return None


class ListPeople(Tool):
    """List all people Rosie knows."""

    name = "list_people"
    description = (
        "List all the people you know — their names, how many face photos you have, "
        "and how many things you remember about them. Use when someone asks "
        "'who do you know?' or 'how many people have you met?'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        store = get_memory_store()
        people = await store.get_all_people()

        if not people:
            return {
                "people": [],
                "message": "I don't know anyone yet! Introduce yourself and I'll remember you.",
            }

        return {
            "people": [
                {
                    "name": p["name"],
                    "face_photos": p["face_count"],
                    "memories": p["memory_count"],
                }
                for p in people
            ],
            "total": len(people),
            "message": f"I know {len(people)} people!",
        }
