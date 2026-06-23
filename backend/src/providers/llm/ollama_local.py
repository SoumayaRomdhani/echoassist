"""Ollama LLM (fully-local, zero-cost alternative).

Same :class:`LLMProvider` contract as Gemini — selecting it is purely an env
change (``LLM_PROVIDER=ollama``). Requires a running Ollama server and a pulled
model (e.g. ``ollama pull qwen3``). Supports text and function calling.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from src.observability.tracing import span
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, Role, ToolCall, ToolSpec

log = logging.getLogger("echoassist.llm.ollama")


def _to_ollama_messages(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.role is Role.ASSISTANT and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content,
                    "tool_calls": [
                        {"function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in m.tool_calls
                    ],
                }
            )
        elif m.role is Role.TOOL:
            out.append({"role": "tool", "content": m.content, "tool_name": m.name or "tool"})
        else:
            out.append({"role": m.role.value, "content": m.content})
    return out


def _to_ollama_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


class OllamaLLM(LLMProvider):
    def __init__(
        self,
        *,
        host: str = "http://localhost:11434",
        model: str = "qwen3",
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> None:
        from ollama import AsyncClient

        self._client = AsyncClient(host=host)
        self._model = model
        self._options = {"temperature": temperature, "num_predict": max_tokens}

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        with span("llm.chat", **{"llm.provider": "ollama", "llm.model": self._model}):
            response = await self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                tools=_to_ollama_tools(tools) if tools else None,
                options=self._options,
            )
        message = response["message"]
        tool_calls = [
            ToolCall(
                id=f"{call['function']['name']}-{i}",
                name=call["function"]["name"],
                arguments=_as_dict(call["function"]["arguments"]),
            )
            for i, call in enumerate(message.get("tool_calls") or [])
        ]
        return LLMResponse(
            text=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            finish_reason=response.get("done_reason"),
        )

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        with span("llm.chat_stream", **{"llm.provider": "ollama", "llm.model": self._model}):
            stream = await self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                options=self._options,
                stream=True,
            )
            async for chunk in stream:
                piece = chunk.get("message", {}).get("content")
                if piece:
                    yield piece


def _as_dict(arguments) -> dict:
    """Ollama returns arguments as a dict; tolerate a JSON string just in case."""
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return dict(arguments or {})
