"""LLM failover — graceful degradation across providers (ARCHITECTURE.md §10).

Wraps a primary LLM and one or more fallbacks behind the same
:class:`LLMProvider` interface. When the primary fails (quota exhaustion,
transport error — anything raised as a :class:`ProviderError`), the next
provider answers. The switch is always logged and optionally reported through
``on_degrade`` — never silent. If every provider fails the last error
propagates, so callers can degrade to a safe spoken fallback.

Switching the primary is still an env var; this only adds resilience when the
primary is temporarily unavailable, e.g. Gemini's daily free-tier quota.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, ToolSpec

log = logging.getLogger("echoassist.providers.failover")

# Reported as (failed_provider_name, next_provider_name | None, error). May be async.
DegradeHook = Callable[[str, str | None, ProviderError], Awaitable[None] | None]


class FailoverLLM(LLMProvider):
    def __init__(
        self,
        primary: LLMProvider,
        *fallbacks: LLMProvider,
        on_degrade: DegradeHook | None = None,
    ) -> None:
        if not fallbacks:
            raise ValueError("FailoverLLM needs at least one fallback provider")
        self._providers = (primary, *fallbacks)
        self._on_degrade = on_degrade

    def _name(self, index: int) -> str:
        return type(self._providers[index]).__name__

    async def _degraded(self, index: int, exc: ProviderError) -> None:
        nxt = self._name(index + 1) if index + 1 < len(self._providers) else None
        log.warning(
            "LLM provider %s failed (%s); %s",
            self._name(index),
            exc,
            f"failing over to {nxt}" if nxt else "no fallback left",
        )
        if self._on_degrade is not None:
            result = self._on_degrade(self._name(index), nxt, exc)
            if inspect.isawaitable(result):
                await result

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        last_exc: ProviderError | None = None
        for index, provider in enumerate(self._providers):
            try:
                return await provider.chat(messages, tools)
            except ProviderError as exc:
                last_exc = exc
                await self._degraded(index, exc)
        assert last_exc is not None  # the loop ran at least once
        raise last_exc

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        last_exc: ProviderError | None = None
        for index, provider in enumerate(self._providers):
            started = False
            try:
                async for delta in provider.chat_stream(messages, tools):
                    started = True
                    yield delta
                return
            except ProviderError as exc:
                # Once a delta is out we cannot transparently switch mid-utterance.
                if started:
                    raise
                last_exc = exc
                await self._degraded(index, exc)
        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()
