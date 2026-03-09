"""Persistent memory tools — remembers facts and recalls them across restarts.

Backed by SQLite via openreachyclaw.memory.MemoryStore.
"""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

from openreachyclaw.memory import get_memory_store

logger = logging.getLogger(__name__)


class Remember(Tool):
    """Remember a fact, preference, or piece of information about someone or something."""

    name = "remember"
    description = (
        "Store a piece of information to remember later. Use this when someone tells "
        "you their name, preferences, important facts, or anything worth remembering. "
        "Example: 'Remember that Jason likes oat milk lattes.' "
        "This information persists across restarts."
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
            "category": {
                "type": "string",
                "description": "Optional category: 'preference', 'fact', 'relationship', 'general'.",
                "default": "general",
            },
        },
        "required": ["subject", "fact"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        subject = kwargs.get("subject", "").strip()
        fact = kwargs.get("fact", "").strip()
        category = kwargs.get("category", "general").strip()

        if not subject or not fact:
            return {"error": "Need a subject and a fact to remember."}

        store = get_memory_store()
        return await store.remember(subject, fact, category)


class Recall(Tool):
    """Recall stored information about a subject."""

    name = "recall"
    description = (
        "Recall what you know about a person, topic, or thing. Use this when someone "
        "asks 'what do you know about me?' or when you need context about a subject. "
        "Memories persist across restarts. Use '*' to recall everything."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Who or what to recall information about. Use '*' to recall everything.",
            },
        },
        "required": ["subject"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        subject = kwargs.get("subject", "").strip()

        if not subject:
            return {"error": "Need a subject to recall."}

        store = get_memory_store()

        if subject == "*":
            matches = await store.recall_all()
        else:
            matches = await store.recall(subject)

        logger.info("Recall %r: found %d memories", subject, len(matches))

        if not matches:
            return {"memories": [], "message": f"I don't have any memories about '{subject}' yet."}

        return {
            "memories": [
                {"subject": m["subject"], "fact": m["fact"], "category": m.get("category", "general")}
                for m in matches
            ],
            "message": f"Found {len(matches)} memory(ies) about '{subject}'.",
        }
