"""Face learning and recognition tools for Reachy Mini.

Uses the camera to capture face photos and associates them with people.
On the Jetson Nano (8GB), we avoid heavy local models and instead:
  - Store face photos locally with person associations
  - Use OpenAI Vision API for identification (via vision.py)
  - Fall back to simple photo-based lookup
"""

import logging
from datetime import datetime
from typing import Any, Dict

import cv2

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

from openreachyclaw.config import get_data_dir
from openreachyclaw.memory import get_memory_store
from openreachyclaw.vision import identify_person_in_frame

logger = logging.getLogger(__name__)


def _faces_dir():
    d = get_data_dir() / "faces"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
        faces_dir = _faces_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
        filename = f"face_{safe_name}_{timestamp}.jpg"
        filepath = faces_dir / filename

        success = cv2.imwrite(str(filepath), frame)
        if not success:
            return {"error": "Failed to save face photo."}

        # Register in memory store
        store = get_memory_store()
        person_id = await store.add_person(name)
        await store.add_face_sighting(person_id, str(filepath))
        await store.remember(name, f"Face photo saved on {timestamp}. Photo: {filename}", "face")

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

        # Use shared vision module for identification
        result = await identify_person_in_frame(frame, people_with_faces)

        if result and result["identified"]:
            name = result["name"]
            memories = await store.recall(name)
            memory_facts = [m["fact"] for m in memories if m.get("category") != "face"]

            return {
                "identified": True,
                "name": name,
                "memories": memory_facts[:10],
                "message": (
                    f"I recognise {name}! "
                    + (f"Here's what I remember about them: {'; '.join(memory_facts[:5])}"
                       if memory_facts else "")
                ),
            }

        if result and not result["identified"]:
            return {
                "identified": False,
                "known_people": [p["name"] for p in people_with_faces],
                "message": (
                    "I can see someone but they don't match anyone I know. "
                    "Want to tell me your name so I can learn your face?"
                ),
            }

        # Fallback: vision API unavailable
        return {
            "known_people": [p["name"] for p in people_with_faces],
            "message": (
                f"I can see someone but I can't identify them right now. "
                f"I know {len(people_with_faces)} people: "
                f"{', '.join(p['name'] for p in people_with_faces)}. "
                f"Could you tell me your name?"
            ),
        }


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
