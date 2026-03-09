"""OpenReachyClaw — Reachy Mini App with voice + text channels.

Subclasses ReachyMiniApp to run Pollen's voice pipeline alongside
our text brain (Chat Completions) and OpenClaw webhook server.

Initialises:
- Structured logging (console + rotating file)
- SQLite-backed persistent memory
- Face recognition tools
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from reachy_mini import ReachyMini, ReachyMiniApp

from openreachyclaw.bridges.openclaw import OpenClawBridge
from openreachyclaw.config import get_openai_api_key
from openreachyclaw.memory import get_memory_store
from openreachyclaw.text_brain import TextBrain
from openreachyclaw.tools.notify import NotifyTools, TOOLS_SCHEMA as NOTIFY_TOOLS_SCHEMA
from openreachyclaw.webhook import set_text_brain, start_webhook_server

logger = logging.getLogger(__name__)


class OpenReachyClaw(ReachyMiniApp):  # type: ignore[misc]
    """Reachy Mini app: Pollen's voice pipeline + OpenClaw text channels."""

    custom_app_url = "http://0.0.0.0:7860/"
    dont_start_webserver = False

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        # Initialise persistent memory on startup.
        store = get_memory_store()
        logger.info("Persistent memory ready (%s)", store._db_path)

        # Start text channel infrastructure in a background thread.
        text_thread = threading.Thread(
            target=self._run_text_channels,
            args=(reachy_mini, stop_event),
            daemon=True,
            name="text-channels",
        )
        text_thread.start()

        # Run Pollen's voice pipeline (blocks until stop_event).
        self._run_voice_pipeline(reachy_mini, stop_event)

    def _run_voice_pipeline(
        self, reachy_mini: ReachyMini, stop_event: threading.Event
    ) -> None:
        """Start Pollen's conversation app voice pipeline."""
        from reachy_mini_conversation_app.main import parse_args, run

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        args, _ = parse_args()
        instance_path = self._get_instance_path().parent

        run(
            args,
            robot=reachy_mini,
            app_stop_event=stop_event,
            settings_app=self.settings_app,
            instance_path=instance_path,
        )

    def _run_text_channels(
        self, reachy_mini: ReachyMini, stop_event: threading.Event
    ) -> None:
        """Start the webhook server, text brain, and OpenClaw bridge."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._text_channel_main(reachy_mini, stop_event))
        except Exception:
            logger.exception("Text channel loop crashed")
        finally:
            loop.close()

    async def _text_channel_main(
        self, reachy_mini: ReachyMini, stop_event: threading.Event
    ) -> None:
        """Async entry point for text channel services."""
        # 1. Connect to OpenClaw.
        bridge = OpenClawBridge()
        await bridge.start()

        # 2. Build tool executor from our custom tools.
        notify_tools = NotifyTools(bridge)
        tool_executor = _build_tool_executor(notify_tools)

        # 3. Load personality (same instructions as voice brain).
        system_instructions = _load_system_instructions()

        # 4. Start text brain.
        brain = TextBrain(
            system_instructions=system_instructions,
            tools_schema=NOTIFY_TOOLS_SCHEMA,
            tool_executor=tool_executor,
        )

        # 5. Wire up webhook server and start it.
        set_text_brain(brain)
        webhook_task = await start_webhook_server()

        logger.info("Text channels ready — webhook + OpenClaw bridge running")

        # 6. Wait for shutdown signal.
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            await brain.close()
            await bridge.stop()
            webhook_task.cancel()


def _load_system_instructions() -> str:
    """Load personality instructions using Pollen's profile system."""
    try:
        from reachy_mini_conversation_app.prompts import get_session_instructions
        return get_session_instructions()
    except ImportError:
        logger.warning("Could not import Pollen prompts — using fallback instructions")
        return (
            "You are a friendly and helpful desktop robot. "
            "You can chat with people on text channels like Slack and Discord."
        )


def _build_tool_executor(notify_tools: NotifyTools) -> Any:
    """Return an async callable that dispatches tool calls by name."""
    registry = {
        "send_message_to_channel": notify_tools,
        "send_photo_to_channel": notify_tools,
    }

    async def executor(name: str, args: dict) -> str:
        handler = registry.get(name)
        if handler is None:
            # Try Pollen's tool dispatch for shared tools (camera, etc.).
            try:
                from reachy_mini_conversation_app.tools.core_tools import dispatch_tool_call
                import json
                result = await dispatch_tool_call(name, json.dumps(args), None)
                return json.dumps(result) if not isinstance(result, str) else result
            except (ImportError, Exception) as exc:
                logger.error("Tool dispatch failed for %s: %s", name, exc)
                return f'{{"error": "Unknown tool: {name}", "detail": "{exc}"}}'
        return await handler.execute(name, args)

    return executor


def cli_entry() -> None:
    """CLI entry point: openreachyclaw command."""
    from openreachyclaw.logging_setup import setup_logging
    setup_logging()

    logger.info("OpenReachyClaw starting up")
    app = OpenReachyClaw()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        logger.info("Shutting down (keyboard interrupt)")
        app.stop()


if __name__ == "__main__":
    cli_entry()
