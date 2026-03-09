"""Idle behavior system for Rosie the robot.

Runs a background asyncio task that periodically performs subtle idle
behaviors when Rosie is not in an active conversation:
  - Small random head movements (looking around the room)
  - Subtle idle emotions (curious, thoughtful, attentive)
  - Periodic camera checks for nearby people

This module is deliberately decoupled from the Pollen framework.  It
accepts a ``tool_dispatcher`` callable and a ``frame_getter`` callable
instead of importing anything from Pollen directly.

Designed for the Jetson Nano (8GB): no ML models are loaded — presence
detection simply checks whether a camera frame is available and
optionally delegates to an external tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

IDLE_TIMEOUT_S = 30.0          # Seconds after last interaction before idle behaviors start
LOOK_INTERVAL_RANGE = (15, 30) # Seconds between random head movements
CURIOSITY_INTERVAL_RANGE = (45, 90)   # Seconds between subtle emotion plays
PRESENCE_CHECK_RANGE = (30, 60)       # Seconds between camera presence checks
CONVERSATION_TRACK_RANGE = (3, 8)     # Seconds between tracking glances during conversation

# Head movement limits (degrees).  Keep movements small and natural.
PAN_RANGE = (-25, 25)
TILT_RANGE = (-10, 15)

# Subtle emotions suitable for idle state (nothing dramatic).
IDLE_EMOTIONS = ("curious", "thoughtful", "attentive")

# Conversation tracking — small head adjustments to look at the speaker.
CONVERSATION_TRACK_PAN = (-8, 8)
CONVERSATION_TRACK_TILT = (-4, 6)

# ---------------------------------------------------------------------------
# Predefined look patterns
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HeadPose:
    """A target head pose in degrees."""
    pan: float
    tilt: float


# Named look patterns — each is a short sequence of poses to step through.
LOOK_PATTERNS: dict[str, list[HeadPose]] = {
    "scan_room": [
        HeadPose(pan=-20, tilt=0),
        HeadPose(pan=0, tilt=5),
        HeadPose(pan=20, tilt=0),
        HeadPose(pan=0, tilt=0),
    ],
    "glance_left": [
        HeadPose(pan=-18, tilt=3),
        HeadPose(pan=0, tilt=0),
    ],
    "glance_right": [
        HeadPose(pan=18, tilt=3),
        HeadPose(pan=0, tilt=0),
    ],
    "look_up_thoughtful": [
        HeadPose(pan=5, tilt=12),
        HeadPose(pan=-5, tilt=8),
        HeadPose(pan=0, tilt=0),
    ],
}


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# tool_dispatcher(name, args_json, deps) -> result
ToolDispatcher = Callable[[str, str, Any], Awaitable[Any]]

# frame_getter() -> numpy array | None
FrameGetter = Callable[[], Any]

# presence_callback(frame) -> called when a new person may be present
PresenceCallback = Callable[..., Awaitable[None]]


# ---------------------------------------------------------------------------
# IdleBehavior
# ---------------------------------------------------------------------------

@dataclass
class IdleBehavior:
    """Background idle-behavior loop for Rosie.

    Parameters
    ----------
    tool_dispatcher:
        Async callable ``(tool_name, args_json, deps) -> result`` used to
        invoke ``move_head`` and ``play_emotion`` without importing Pollen.
    frame_getter:
        Callable that returns the latest camera frame (numpy array) or
        ``None`` if the camera is unavailable.
    tool_deps:
        The ``ToolDependencies`` (or equivalent) object passed as the
        third argument to *tool_dispatcher*.  May be ``None`` if your
        dispatcher doesn't need it.
    on_presence_detected:
        Optional async callback fired when the presence check finds a
        camera frame available (i.e. someone might be in view).  Use
        this to trigger a greeting / security flow.
    idle_timeout:
        Seconds after the last interaction before idle behaviors begin.
    """

    tool_dispatcher: ToolDispatcher
    frame_getter: FrameGetter
    tool_deps: Any = None
    on_presence_detected: Optional[PresenceCallback] = None
    idle_timeout: float = IDLE_TIMEOUT_S

    # --- internal state (not constructor args) ---
    _last_interaction: float = field(default_factory=time.monotonic, init=False)
    _is_idle: bool = field(default=False, init=False)
    _is_in_conversation: bool = field(default=False, init=False)
    _task: Optional[asyncio.Task[None]] = field(default=None, init=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    # ------------------------------------------------------------------
    # Public API — interaction / conversation tracking
    # ------------------------------------------------------------------

    def notify_interaction(self) -> None:
        """Call when voice or text activity occurs to reset the idle timer."""
        self._last_interaction = time.monotonic()
        if self._is_idle:
            logger.debug("Interaction received — leaving idle state")
            self._is_idle = False

    def notify_conversation_start(self) -> None:
        """Call when an active conversation begins (suppresses idle behaviors)."""
        self._is_in_conversation = True
        self._is_idle = False
        self._last_interaction = time.monotonic()
        logger.debug("Conversation started — idle behaviors suppressed")

    def notify_conversation_end(self) -> None:
        """Call when a conversation finishes (idle timer restarts)."""
        self._is_in_conversation = False
        self._last_interaction = time.monotonic()
        logger.debug("Conversation ended — idle timer restarted")

    # ------------------------------------------------------------------
    # Public API — state queries
    # ------------------------------------------------------------------

    @property
    def is_idle(self) -> bool:
        return self._is_idle

    @property
    def is_in_conversation(self) -> bool:
        return self._is_in_conversation

    @property
    def last_interaction_time(self) -> float:
        return self._last_interaction

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the idle-behavior background task.

        Safe to call multiple times — only one task will run.
        """
        if self._task is not None and not self._task.done():
            logger.warning("IdleBehavior already running")
            return
        self._stop_event.clear()
        self._task = asyncio.ensure_future(self._run_loop())
        logger.info("IdleBehavior started")

    async def stop(self) -> None:
        """Cleanly shut down the background task."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("IdleBehavior stopped")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main loop — schedules idle actions when appropriate."""

        # Stagger initial timers so everything doesn't fire at once.
        next_look = time.monotonic() + random.uniform(*LOOK_INTERVAL_RANGE)
        next_emotion = time.monotonic() + random.uniform(*CURIOSITY_INTERVAL_RANGE)
        next_presence = time.monotonic() + random.uniform(*PRESENCE_CHECK_RANGE)
        next_track = time.monotonic() + random.uniform(*CONVERSATION_TRACK_RANGE)

        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(1.0)  # tick rate — 1 Hz is plenty
                now = time.monotonic()

                # Determine whether we are idle.
                idle_elapsed = now - self._last_interaction
                was_idle = self._is_idle
                self._is_idle = (
                    idle_elapsed >= self.idle_timeout
                    and not self._is_in_conversation
                )

                if self._is_idle and not was_idle:
                    logger.info(
                        "Entering idle state (%.1fs since last interaction)",
                        idle_elapsed,
                    )

                # During conversation: suppress random behaviors but allow
                # subtle head tracking so Rosie looks at the speaker.
                if self._is_in_conversation:
                    if now >= next_track:
                        next_track = now + random.uniform(*CONVERSATION_TRACK_RANGE)
                        await self._track_speaker()
                    continue

                # --- Presence check (runs even when not fully idle) ---
                if now >= next_presence:
                    next_presence = now + random.uniform(*PRESENCE_CHECK_RANGE)
                    await self._check_presence()

                # Only do look-around and emotion when truly idle.
                if not self._is_idle:
                    continue

                # --- Random head movement ---
                if now >= next_look:
                    next_look = now + random.uniform(*LOOK_INTERVAL_RANGE)
                    await self._look_around()

                # --- Subtle idle emotion ---
                if now >= next_emotion:
                    next_emotion = now + random.uniform(*CURIOSITY_INTERVAL_RANGE)
                    await self._play_idle_emotion()

        except asyncio.CancelledError:
            logger.debug("Idle loop cancelled")
        except Exception:
            logger.exception("Idle loop crashed — stopping idle behaviors")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _move_head(self, pan: float, tilt: float) -> None:
        """Send a move_head command via the tool dispatcher."""
        args = json.dumps({"pan": round(pan, 1), "tilt": round(tilt, 1)})
        try:
            await self.tool_dispatcher("move_head", args, self.tool_deps)
        except Exception:
            logger.debug("move_head call failed (non-critical)", exc_info=True)

    async def _play_emotion(self, emotion: str) -> None:
        """Send a play_emotion command via the tool dispatcher."""
        args = json.dumps({"emotion": emotion})
        try:
            await self.tool_dispatcher("play_emotion", args, self.tool_deps)
        except Exception:
            logger.debug("play_emotion call failed (non-critical)", exc_info=True)

    async def _look_around(self) -> None:
        """Execute a random look pattern or a single random head movement."""
        if random.random() < 0.6:
            # Use a named pattern.
            pattern_name = random.choice(list(LOOK_PATTERNS.keys()))
            poses = LOOK_PATTERNS[pattern_name]
            logger.debug("Idle look pattern: %s", pattern_name)
            for pose in poses:
                if self._stop_event.is_set() or self._is_in_conversation:
                    return
                await self._move_head(pose.pan, pose.tilt)
                await asyncio.sleep(random.uniform(1.5, 3.0))
        else:
            # Single random small movement.
            pan = random.uniform(*PAN_RANGE)
            tilt = random.uniform(*TILT_RANGE)
            logger.debug("Idle random look: pan=%.1f tilt=%.1f", pan, tilt)
            await self._move_head(pan, tilt)

    async def _play_idle_emotion(self) -> None:
        """Play a subtle idle emotion."""
        emotion = random.choice(IDLE_EMOTIONS)
        logger.debug("Idle emotion: %s", emotion)
        await self._play_emotion(emotion)

    async def _track_speaker(self) -> None:
        """Small head adjustment during conversation to look at the speaker.

        Unlike idle look-around, these movements are subtle and centred
        near the forward-facing position, giving the impression that
        Rosie is maintaining eye contact or glancing at the person
        speaking to her.
        """
        pan = random.uniform(*CONVERSATION_TRACK_PAN)
        tilt = random.uniform(*CONVERSATION_TRACK_TILT)
        logger.debug("Conversation tracking: pan=%.1f tilt=%.1f", pan, tilt)
        await self._move_head(pan, tilt)

    async def _check_presence(self) -> None:
        """Check whether someone is visible on camera.

        This is intentionally lightweight — no ML model, just verifying
        that a camera frame is available.  If a frame exists *and* we
        are idle (no recent interaction), we fire the presence callback
        so the caller can trigger a greeting or security flow.
        """
        try:
            frame = self.frame_getter()
        except Exception:
            logger.debug("frame_getter raised (camera may be offline)", exc_info=True)
            return

        if frame is None:
            return

        # Frame available — someone might be in front of the camera.
        if self._is_idle and self.on_presence_detected is not None:
            logger.info("Presence detected while idle — triggering callback")
            try:
                await self.on_presence_detected(frame)
            except Exception:
                logger.exception("on_presence_detected callback failed")
