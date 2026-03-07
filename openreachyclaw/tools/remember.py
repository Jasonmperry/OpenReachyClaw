"""Simple memory tool — remembers facts and recalls them later."""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

# Simple in-memory store (persists while app is running)
_memories: list[dict] = []


class Remember(Tool):
    """Remember a fact, preference, or piece of information about someone or something."""

    name = "remember"
    description = (
        "Store a piece of information to remember later. Use this when someone tells "
        "you their name, preferences, important facts, or anything worth remembering. "
        "Example: 'Remember that Jason likes oat milk lattes.'"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Who or what this is about (e.g. 'Jason', 'the project', 'office').",
            },
            "fact": {
                "type": "string",
                "description": "The information to remember.",
            },
        },
        "required": ["subject", "fact"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        subject = kwargs.get("subject", "").strip()
        fact = kwargs.get("fact", "").strip()

        if not subject or not fact:
            return {"error": "Need a subject and a fact to remember."}

        memory = {
            "subject": subject,
            "fact": fact,
            "time": datetime.now().isoformat(),
        }
        _memories.append(memory)
        logger.info("Remembered about %s: %s", subject, fact[:80])
        return {"status": "remembered", "subject": subject, "fact": fact}


class Recall(Tool):
    """Recall stored information about a subject."""

    name = "recall"
    description = (
        "Recall what you know about a person, topic, or thing. Use this when someone "
        "asks 'what do you know about me?' or when you need context about a subject."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Who or what to recall information about.",
            },
        },
        "required": ["subject"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        subject = kwargs.get("subject", "").strip().lower()

        if not subject:
            return {"error": "Need a subject to recall."}

        matches = [m for m in _memories if subject in m["subject"].lower()]
        logger.info("Recall %r: found %d memories", subject, len(matches))

        if not matches:
            return {"memories": [], "message": f"I don't have any memories about '{subject}' yet."}

        return {
            "memories": [{"subject": m["subject"], "fact": m["fact"]} for m in matches],
            "message": f"Found {len(matches)} memory(ies) about '{subject}'.",
        }
