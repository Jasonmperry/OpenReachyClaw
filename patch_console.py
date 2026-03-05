#!/usr/bin/env python3
"""Patch conversation app console.py to add robot control API endpoints.

Run on the Jetson after deploying:
  python3 ~/OpenReachyClaw/patch_console.py

This injects /control/* endpoints into the settings FastAPI app.
"""

import sys
from pathlib import Path

CONSOLE_PY = Path.home() / "reachy_mini_conversation_app/src/reachy_mini_conversation_app/console.py"
MARKER = "        self._settings_initialized = True"
ALREADY_PATCHED = "/control/status"

PATCH = '''
        # ---- Robot Control Endpoints (added by OpenReachyClaw) ----

        import json as _json

        @self._settings_app.get("/control/status")
        def _control_status():
            """Return robot connection state and sleep/wake status."""
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None or deps.reachy_mini is None:
                    return JSONResponse({"connected": False, "awake": False})
                rm = deps.reachy_mini
                # Check if robot is responsive
                connected = True
                # Reachy Mini uses goto_sleep / wake_up; check internal state if available
                awake = True
                if hasattr(rm, '_is_sleeping'):
                    awake = not rm._is_sleeping
                elif hasattr(rm, 'is_awake'):
                    awake = rm.is_awake
                return JSONResponse({"connected": connected, "awake": awake})
            except Exception as e:
                return JSONResponse({"connected": False, "awake": False, "error": str(e)})

        @self._settings_app.post("/control/sleep")
        async def _control_sleep():
            """Put Reachy to sleep — stops conversation, motors go limp."""
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None or deps.reachy_mini is None:
                    return JSONResponse({"error": "Robot not ready"}, status_code=503)
                deps.reachy_mini.goto_sleep()
                # Also stop any active voice session
                try:
                    if hasattr(self, "handler") and self.handler:
                        await self.handler.shutdown()
                except Exception:
                    pass
                return JSONResponse({"status": "sleeping", "message": "Rosie is now sleeping"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @self._settings_app.post("/control/wake")
        async def _control_wake():
            """Wake Reachy up — motors engage, ready for conversation."""
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None or deps.reachy_mini is None:
                    return JSONResponse({"error": "Robot not ready"}, status_code=503)
                deps.reachy_mini.wake_up()
                # Restart voice session if handler is available
                try:
                    if hasattr(self, "handler") and self.handler:
                        await self.handler.start_up()
                except Exception:
                    pass
                return JSONResponse({"status": "awake", "message": "Rosie is awake and ready"})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @self._settings_app.post("/control/dance")
        async def _control_dance(request: _FastAPIRequest):
            try:
                raw = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid_json"}, status_code=400)
            move = str(raw.get("move", "random")).strip()
            repeat = int(raw.get("repeat", 1))
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None:
                    return JSONResponse({"error": "Robot not ready — handler not initialized"}, status_code=503)
                mod = sys.modules.get("reachy_mini_conversation_app.tools.core_tools")
                if mod and hasattr(mod, "dispatch_tool_call"):
                    result = await mod.dispatch_tool_call("dance", _json.dumps({"move": move, "repeat": repeat}), deps)
                    return JSONResponse(result)
                return JSONResponse({"error": "tools not loaded"}, status_code=503)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @self._settings_app.post("/control/emotion")
        async def _control_emotion(request: _FastAPIRequest):
            try:
                raw = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid_json"}, status_code=400)
            emotion = str(raw.get("emotion", "")).strip()
            if not emotion:
                return JSONResponse({"error": "emotion required"}, status_code=400)
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None:
                    return JSONResponse({"error": "Robot not ready — handler not initialized"}, status_code=503)
                mod = sys.modules.get("reachy_mini_conversation_app.tools.core_tools")
                if mod and hasattr(mod, "dispatch_tool_call"):
                    result = await mod.dispatch_tool_call("play_emotion", _json.dumps({"emotion": emotion}), deps)
                    return JSONResponse(result)
                return JSONResponse({"error": "tools not loaded"}, status_code=503)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @self._settings_app.post("/control/stop")
        async def _control_stop():
            try:
                deps = self.handler.deps if hasattr(self, "handler") and self.handler else None
                if deps is None:
                    return JSONResponse({"error": "Robot not ready"}, status_code=503)
                mod = sys.modules.get("reachy_mini_conversation_app.tools.core_tools")
                if mod and hasattr(mod, "dispatch_tool_call"):
                    await mod.dispatch_tool_call("stop_dance", "{}", deps)
                    await mod.dispatch_tool_call("stop_emotion", "{}", deps)
                    return JSONResponse({"status": "stopped"})
                return JSONResponse({"error": "tools not loaded"}, status_code=503)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @self._settings_app.get("/control/dances")
        def _control_dances():
            try:
                from reachy_mini_dances_library.collection.dance import AVAILABLE_MOVES
                return JSONResponse({"moves": list(AVAILABLE_MOVES.keys())})
            except Exception:
                return JSONResponse({"moves": []})

        @self._settings_app.get("/control/emotions")
        def _control_emotions():
            try:
                from reachy_mini.motion.recorded_move import RecordedMoves
                recorded = RecordedMoves("pollen-robotics/reachy-mini-emotions-library")
                emotions = [{"name": n, "description": recorded.get(n).description} for n in recorded.list_moves()]
                return JSONResponse({"emotions": emotions})
            except Exception as e:
                return JSONResponse({"emotions": [], "error": str(e)})

        @self._settings_app.post("/control/restart")
        async def _control_restart():
            try:
                if hasattr(self, "handler") and self.handler:
                    await self.handler.shutdown()
                    await self.handler.start_up()
                    return JSONResponse({"status": "restarted", "message": "Voice session restarted"})
                return JSONResponse({"error": "handler not available"}, status_code=503)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

'''


def main():
    if not CONSOLE_PY.exists():
        print(f"ERROR: {CONSOLE_PY} not found")
        sys.exit(1)

    content = CONSOLE_PY.read_text()

    if ALREADY_PATCHED in content:
        print("Already patched — skipping.")
        return

    if MARKER not in content:
        print(f"ERROR: marker '{MARKER}' not found in console.py")
        sys.exit(1)

    content = content.replace(MARKER, PATCH + "\n" + MARKER)
    CONSOLE_PY.write_text(content)
    print(f"OK: Control routes patched into {CONSOLE_PY}")


if __name__ == "__main__":
    main()
