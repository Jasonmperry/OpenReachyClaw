"""OpenReachyClaw — Reachy Mini App with voice + text channels.

Subclasses ReachyMiniApp to run Pollen's voice pipeline alongside
our text brain (Chat Completions) and OpenClaw webhook server.

Initialises:
- Structured logging (console + rotating file)
- SQLite-backed persistent memory
- Face recognition tools
- Idle heartbeat behaviors (looking around, emotions, presence detection)
- Security/greeting system (identify visitors, remember faces)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from reachy_mini import ReachyMini, ReachyMiniApp

from openreachyclaw.bridges.openclaw import OpenClawBridge
from openreachyclaw.config import get_openai_api_key, validate_config
from openreachyclaw.memory import get_memory_store
from openreachyclaw.text_brain import TextBrain
from openreachyclaw.tools.notify import NotifyTools, TOOLS_SCHEMA as NOTIFY_TOOLS_SCHEMA
from openreachyclaw.webhook import set_text_brain, set_registered_tools, start_webhook_server

logger = logging.getLogger(__name__)


class OpenReachyClaw(ReachyMiniApp):  # type: ignore[misc]
    """Reachy Mini app: Pollen's voice pipeline + OpenClaw text channels."""

    custom_app_url = "http://0.0.0.0:7860/"
    dont_start_webserver = False

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        # Validate config and log integration status.
        status = validate_config()
        logger.info("Integration status: %s", status)

        # Initialise persistent memory on startup.
        store = get_memory_store()
        logger.info("Persistent memory ready (%s)", store._db_path)

        # Start text channel + idle behaviors in a background thread.
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
        """Start the webhook server, text brain, idle behaviors, and OpenClaw bridge."""
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

        # 2b. Register tools for the web UI's Tools & Skills tab.
        _register_tools_for_ui()

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

        # 6. Start idle heartbeat + greeting system.
        idle_behavior, greeter = await _start_idle_system(tool_executor)

        logger.info("Text channels ready — webhook + OpenClaw + idle behaviors running")

        # 7. Wait for shutdown signal.
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            if idle_behavior:
                await idle_behavior.stop()
            await brain.close()
            await bridge.stop()
            webhook_task.cancel()


async def _start_idle_system(tool_executor: Any) -> tuple:
    """Initialise the heartbeat idle behaviors and presence greeter.

    Returns (idle_behavior, greeter) — either may be None if setup fails.
    """
    try:
        from openreachyclaw.heartbeat import IdleBehavior
        from openreachyclaw.greeter import PresenceGreeter

        store = get_memory_store()

        # Camera frame getter — tries to get a frame from Pollen's camera worker.
        def get_frame():
            try:
                import sys
                mod = sys.modules.get("reachy_mini_conversation_app.tools.core_tools")
                if mod and hasattr(mod, "_deps") and mod._deps and mod._deps.camera_worker:
                    return mod._deps.camera_worker.get_latest_frame()
            except Exception:
                pass
            return None

        # Tool dispatcher for heartbeat (adapts dict-based executor to json-string based)
        async def heartbeat_dispatcher(name: str, args_json: str, deps: Any) -> Any:
            args = json.loads(args_json)
            return await tool_executor(name, args)

        # Create greeter
        greeter = PresenceGreeter(
            camera_frame_getter=get_frame,
            tool_dispatcher=heartbeat_dispatcher,
            memory_store=store,
        )

        # Presence callback for heartbeat — delegates to greeter
        async def on_presence(frame: Any) -> None:
            result = await greeter.check_and_greet()
            if result.person_detected:
                if result.identified:
                    logger.info("Greeted %s: %s", result.name, result.greeting_text)
                else:
                    logger.info("Unknown person detected, photo: %s", result.photo_path)

        # Create and start idle behavior
        idle = IdleBehavior(
            tool_dispatcher=heartbeat_dispatcher,
            frame_getter=get_frame,
            on_presence_detected=on_presence,
        )
        idle.start()

        logger.info("Idle behaviors + presence greeter active")
        return idle, greeter

    except Exception:
        logger.warning("Could not start idle behaviors — continuing without them", exc_info=True)
        return None, None


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


def _register_tools_for_ui() -> None:
    """Collect all tool descriptions and register them for the web UI."""
    tools: list[dict] = []

    # Our custom tools
    from openreachyclaw.tools.faces import LearnFace, WhoIsThis, ListPeople
    from openreachyclaw.tools.remember import Remember, Recall

    for cls in [LearnFace, WhoIsThis, ListPeople, Remember, Recall]:
        tools.append({"name": cls.name, "description": cls.description})

    # Notify tools
    tools.append({"name": "send_message_to_channel", "description": "Send a text message to a channel (Slack, Discord, etc.)"})
    tools.append({"name": "send_photo_to_channel", "description": "Send a photo to a channel with an optional caption."})

    # Try to discover Pollen's built-in tools
    try:
        from reachy_mini_conversation_app.tools.core_tools import get_all_tools
        for t in get_all_tools():
            name = getattr(t, "name", None) or type(t).__name__
            desc = getattr(t, "description", "")
            tools.append({"name": name, "description": desc})
    except (ImportError, Exception):
        # Pollen tools not available — add known built-ins manually
        for name, desc in [
            ("move_head", "Move Rosie's head (pan/tilt in degrees)."),
            ("play_emotion", "Play an emotion animation."),
            ("stop_emotion", "Stop the current emotion animation."),
            ("dance", "Perform a dance move."),
            ("stop_dance", "Stop the current dance."),
            ("take_photo", "Capture a photo from the camera."),
        ]:
            tools.append({"name": name, "description": desc})

    # Add optional tools if configured
    try:
        from openreachyclaw.tools.weather import Weather
        tools.append({"name": Weather.name, "description": Weather.description})
    except (ImportError, AttributeError):
        pass

    try:
        from openreachyclaw.tools.web_search import WebSearch
        tools.append({"name": WebSearch.name, "description": WebSearch.description})
    except (ImportError, AttributeError):
        pass

    try:
        from openreachyclaw.tools.send_sms import SendSMS
        tools.append({"name": SendSMS.name, "description": SendSMS.description})
    except (ImportError, AttributeError):
        pass

    try:
        from openreachyclaw.tools.take_order import TakeOrder
        tools.append({"name": TakeOrder.name, "description": TakeOrder.description})
    except (ImportError, AttributeError):
        pass

    try:
        from openreachyclaw.tools.horoscope import Horoscope
        tools.append({"name": Horoscope.name, "description": Horoscope.description})
    except (ImportError, AttributeError):
        pass

    try:
        from openreachyclaw.tools.nano_banana import NanoBanana
        tools.append({"name": NanoBanana.name, "description": NanoBanana.description})
    except (ImportError, AttributeError):
        pass

    set_registered_tools(tools)
    logger.info("Registered %d tools for web UI", len(tools))


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
