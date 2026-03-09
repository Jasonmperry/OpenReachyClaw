"""Persistent order management tool — backed by SQLite."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

from openreachyclaw.memory import get_memory_store

logger = logging.getLogger(__name__)


class TakeOrder(Tool):
    """Take an order from someone — food, drink, task, or anything else."""

    name = "take_order"
    description = (
        "Take an order from someone. Use this when a person asks you to remember "
        "an order, place a request, or add something to a list. You can take food "
        "orders, drink orders, supply requests, or any kind of task. "
        "Orders persist across restarts."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": "Name of the person placing the order.",
            },
            "item": {
                "type": "string",
                "description": "What they are ordering (e.g. 'large oat milk latte', '2 boxes of pens').",
            },
            "notes": {
                "type": "string",
                "description": "Any special instructions or notes.",
                "default": "",
            },
        },
        "required": ["person", "item"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        person = kwargs.get("person", "").strip()
        item = kwargs.get("item", "").strip()
        notes = kwargs.get("notes", "").strip()

        if not person or not item:
            return {"error": "Need both a person name and an item to place an order."}

        store = get_memory_store()
        result = await store.take_order(person, item, notes)
        result["message"] = f"Order #{result['order_id']} confirmed for {person}: {item}"
        return result


class ListOrders(Tool):
    """List all current orders."""

    name = "list_orders"
    description = (
        "List all orders that have been taken. Use this when someone asks "
        "what orders are pending, what people have ordered, or to review the order list. "
        "Orders persist across restarts."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": "Optional: filter orders by person name.",
                "default": "",
            },
        },
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        person_filter = kwargs.get("person", "").strip()

        store = get_memory_store()
        orders = await store.list_orders(person_filter)

        logger.info("Listing %d orders (filter=%r)", len(orders), person_filter or "none")

        if not orders:
            return {"orders": [], "message": "No orders yet."}

        return {
            "orders": orders,
            "total": len(orders),
            "message": f"{len(orders)} order(s) found.",
        }
