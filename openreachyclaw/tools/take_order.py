"""Tool for taking and managing orders (food, drinks, tasks)."""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

# In-memory order store (persists while app is running)
_orders: list[dict] = []


class TakeOrder(Tool):
    """Take an order from someone — food, drink, task, or anything else."""

    name = "take_order"
    description = (
        "Take an order from someone. Use this when a person asks you to remember "
        "an order, place a request, or add something to a list. You can take food "
        "orders, drink orders, supply requests, or any kind of task."
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

        order = {
            "id": len(_orders) + 1,
            "person": person,
            "item": item,
            "notes": notes,
            "time": datetime.now().strftime("%I:%M %p"),
            "status": "pending",
        }
        _orders.append(order)

        logger.info("Order #%d: %s ordered '%s'", order["id"], person, item)
        return {
            "status": "confirmed",
            "order_id": order["id"],
            "person": person,
            "item": item,
            "notes": notes,
            "message": f"Order #{order['id']} confirmed for {person}: {item}",
        }


class ListOrders(Tool):
    """List all current orders."""

    name = "list_orders"
    description = (
        "List all orders that have been taken. Use this when someone asks "
        "what orders are pending, what people have ordered, or to review the order list."
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
        person_filter = kwargs.get("person", "").strip().lower()

        if not _orders:
            return {"orders": [], "message": "No orders yet."}

        filtered = _orders
        if person_filter:
            filtered = [o for o in _orders if person_filter in o["person"].lower()]

        logger.info("Listing %d orders (filter=%r)", len(filtered), person_filter or "none")
        return {
            "orders": filtered,
            "total": len(filtered),
            "message": f"{len(filtered)} order(s) found.",
        }
