"""HTTP client for the OpenClaw messaging gateway."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from openreachyclaw.config import get_openclaw_url

logger = logging.getLogger(__name__)


class OpenClawBridge:
    """Talks to an OpenClaw instance on localhost."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or get_openclaw_url()).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._health_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        healthy = await self.health_check()
        if healthy:
            logger.info("OpenClaw connected at %s", self.base_url)
        else:
            logger.warning("OpenClaw not reachable at %s — will retry", self.base_url)
        self._health_task = asyncio.create_task(self._periodic_health())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_channels(self) -> list[dict]:
        try:
            resp = await self._client.get("/api/channels")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to list channels: %s", exc)
            return []

    async def send_text(self, channel: str, recipient: str, text: str) -> bool:
        return await self._send({"channel": channel, "recipient": recipient, "text": text})

    async def send_photo(
        self, channel: str, recipient: str, image_path: str, caption: str = ""
    ) -> bool:
        path = Path(image_path)
        if not path.exists():
            logger.error("Image file not found: %s", image_path)
            return False
        try:
            files = {"image": (path.name, path.read_bytes(), "image/jpeg")}
            data = {"channel": channel, "recipient": recipient, "caption": caption}
            resp = await self._client.post("/api/send", data=data, files=files)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.error("Failed to send photo: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send(self, payload: dict) -> bool:
        try:
            resp = await self._client.post("/api/send", json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.error("Failed to send message: %s", exc)
            return False

    async def _periodic_health(self) -> None:
        while True:
            await asyncio.sleep(60)
            ok = await self.health_check()
            if not ok:
                logger.warning("OpenClaw health check failed — is it running?")
