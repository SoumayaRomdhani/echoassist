"""Large-language-model provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.providers.types import LLMResponse, Message, ToolSpec


class LLMProvider(ABC):
    """Chat LLM with optional tool calling.

    ``chat`` is the core contract (text + tool calls). ``chat_stream`` yields
    text deltas for low-latency synthesis; a non-streaming default is provided
    so every provider supports it.
    """

    @abstractmethod
    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        """Return one assistant turn for the given conversation."""
        raise NotImplementedError

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        """Yield text deltas. Default: emit the full response in one chunk."""
        response = await self.chat(messages, tools)
        if response.text:
            yield response.text

    async def aclose(self) -> None:  # noqa: B027 — optional override hook, default no-op
        """Release any held resources. Override if needed."""
