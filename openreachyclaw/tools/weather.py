"""OpenWeatherMap current weather tool for Reachy Mini."""

import logging
import os
from typing import Any, Dict

import httpx

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


class GetWeather(Tool):
    """Get current weather for a location."""

    name = "get_weather"
    description = (
        "Get the current weather for a location. "
        "Provide a city name like 'Baltimore, MD' or 'Tokyo'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name, e.g. 'Baltimore, MD' or 'Tokyo'.",
            },
        },
        "required": ["location"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        location = (kwargs.get("location") or "").strip()
        if not location:
            return {"error": "location must be a non-empty string"}

        if not OPENWEATHER_API_KEY:
            return {"error": "OPENWEATHER_API_KEY environment variable not set"}

        logger.info("Tool call: get_weather location=%s", location)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    OPENWEATHER_URL,
                    params={
                        "q": location,
                        "appid": OPENWEATHER_API_KEY,
                        "units": "imperial",
                    },
                )

            if resp.status_code == 404:
                return {"error": f"Location not found: {location}"}

            resp.raise_for_status()
            data = resp.json()

            main = data.get("main", {})
            wind = data.get("wind", {})
            weather_list = data.get("weather", [{}])

            return {
                "location": data.get("name", location),
                "temperature": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "description": weather_list[0].get("description", "unknown"),
                "humidity": main.get("humidity"),
                "wind_speed": wind.get("speed"),
            }

        except httpx.HTTPStatusError as exc:
            logger.error("Weather API HTTP error: %s", exc)
            return {"error": f"Weather API error: {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.error("Weather API request error: %s", exc)
            return {"error": f"Weather API request failed: {exc}"}
