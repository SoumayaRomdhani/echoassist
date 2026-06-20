"""Ollama LLM (fully-local, zero-cost alternative).

Same :class:`LLMProvider` contract as Gemini — selecting it is purely an env
change (``LLM_PROVIDER=ollama``). Requires a running Ollama server and a pulled
model (e.g. ``ollama pull qwen3``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, ToolSpec

log = logging.getLogger("echoassist.llm.ollama")


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

    def _to_messages(self, messages: list[Message]) -> list[dict]:
        return [{"role": m.role.value, "content": m.content} for m in messages]

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        response = await self._client.chat(
            model=self._model,
            messages=self._to_messages(messages),
            options=self._options,
        )
        return LLMResponse(
            text=(response["message"]["content"] or "").strip(),
            finish_reason=response.get("done_reason"),
        )

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        stream = await self._client.chat(
            model=self._model,
            messages=self._to_messages(messages),
            options=self._options,
            stream=True,
        )
        async for chunk in stream:
            piece = chunk.get("message", {}).get("content")
            if piece:
                yield piece
