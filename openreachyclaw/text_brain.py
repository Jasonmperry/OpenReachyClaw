"""Text brain — Chat Completions API for text-channel conversations."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from openreachyclaw.config import (
    get_history_max_messages,
    get_history_ttl_seconds,
    get_openai_api_key,
    get_text_model,
)

logger = logging.getLogger(__name__)

# Tools that only make sense over voice (head movement, emotions with body motion).
VOICE_ONLY_TOOLS = {"play_emotion", "stop_emotion", "move_head"}

# Max tool-call rounds per incoming message to avoid infinite loops.
MAX_TOOL_ROUNDS = 5


class ConversationHistory:
    """Per-conversation sliding-window message history with TTL."""

    def __init__(self, max_messages: int | None = None, ttl_seconds: int | None = None):
        self.max_messages = max_messages or get_history_max_messages()
        self.ttl_seconds = ttl_seconds or get_history_ttl_seconds()
        self._conversations: dict[str, list[dict]] = {}
        self._last_active: dict[str, float] = {}

    def key(self, channel: str, sender: str, thread_id: str = "") -> str:
        return f"{channel}:{sender}:{thread_id}" if thread_id else f"{channel}:{sender}"

    def get(self, conv_key: str) -> list[dict]:
        self._expire(conv_key)
        return list(self._conversations.get(conv_key, []))

    def append(self, conv_key: str, message: dict) -> None:
        if conv_key not in self._conversations:
            self._conversations[conv_key] = []
        self._conversations[conv_key].append(message)
        # Trim to window size.
        if len(self._conversations[conv_key]) > self.max_messages:
            self._conversations[conv_key] = self._conversations[conv_key][
                -self.max_messages :
            ]
        self._last_active[conv_key] = time.monotonic()

    def _expire(self, conv_key: str) -> None:
        last = self._last_active.get(conv_key)
        if last is not None and (time.monotonic() - last) > self.ttl_seconds:
            self._conversations.pop(conv_key, None)
            self._last_active.pop(conv_key, None)


class TextBrain:
    """Handles text-channel messages via the Chat Completions API."""

    def __init__(
        self,
        system_instructions: str,
        tools_schema: list[dict],
        tool_executor: Any = None,
    ):
        self.system_instructions = system_instructions
        self.tools_schema = [
            t for t in tools_schema if t.get("function", {}).get("name") not in VOICE_ONLY_TOOLS
        ]
        self.tool_executor = tool_executor
        self.history = ConversationHistory()
        self._api_key = get_openai_api_key()
        self._model = get_text_model()
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=60.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def handle_message(
        self,
        channel: str,
        sender: str,
        display_name: str,
        text: str,
        thread_id: str = "",
    ) -> str:
        conv_key = self.history.key(channel, sender, thread_id)

        # Build system prompt with channel context.
        system = (
            f"{self.system_instructions}\n\n"
            f"You are replying on {channel} to {display_name}. "
            f"Keep responses concise and text-friendly. "
            f"Do not use play_emotion or move_head — those are voice-only."
        )

        # Append user message.
        self.history.append(conv_key, {"role": "user", "content": text})

        messages = [{"role": "system", "content": system}] + self.history.get(conv_key)

        # Tool call loop.
        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self._chat_completion(messages, use_tools=True)
            choice = resp["choices"][0]
            assistant_msg = choice["message"]

            # Append the assistant message to history.
            self.history.append(conv_key, assistant_msg)
            messages.append(assistant_msg)

            if choice["finish_reason"] != "tool_calls" or not assistant_msg.get("tool_calls"):
                # Done — return text content.
                return assistant_msg.get("content") or ""

            # Execute tool calls.
            for tool_call in assistant_msg["tool_calls"]:
                result = await self._execute_tool(tool_call)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
                self.history.append(conv_key, tool_msg)
                messages.append(tool_msg)

        # Exhausted rounds — return whatever we have.
        logger.warning("Max tool rounds reached for %s", conv_key)
        return assistant_msg.get("content") or "Sorry, that took too many steps. Could you try again?"

    async def _chat_completion(self, messages: list[dict], use_tools: bool) -> dict:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if use_tools and self.tools_schema:
            payload["tools"] = self.tools_schema

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def _execute_tool(self, tool_call: dict) -> str:
        name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid arguments for {name}"})

        if self.tool_executor is None:
            return json.dumps({"error": f"No tool executor — cannot run {name}"})

        try:
            result = await self.tool_executor(name, args)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)})
