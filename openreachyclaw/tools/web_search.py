"""SerpAPI web search tool for Reachy Mini."""

import logging
import os
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
SERPAPI_URL = "https://serpapi.com/search.json"


class WebSearch(Tool):
    """Search the web and return top results."""

    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns the top 5 results with titles, links, and snippets."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
        },
        "required": ["query"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return {"error": "query must be a non-empty string"}

        if not SERPAPI_KEY:
            return {"error": "SERPAPI_KEY environment variable not set"}

        logger.info("Tool call: web_search query=%s", query[:120])

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    SERPAPI_URL,
                    params={
                        "q": query,
                        "api_key": SERPAPI_KEY,
                        "num": 5,
                    },
                )

            resp.raise_for_status()
            data = resp.json()

            organic = data.get("organic_results", [])[:5]
            results = [
                {
                    "title": r.get("title", ""),
                    "link": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                }
                for r in organic
            ]

            return {"query": query, "results": results}

        except httpx.HTTPStatusError as exc:
            logger.error("SerpAPI HTTP error: %s", exc)
            return {"error": f"Search API error: {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.error("SerpAPI request error: %s", exc)
            return {"error": f"Search API request failed: {exc}"}
