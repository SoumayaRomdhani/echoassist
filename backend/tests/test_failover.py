"""LLM failover — graceful degradation across providers (never silent)."""

from __future__ import annotations

import pytest

from src.providers.errors import ProviderError, ProviderQuotaError
from src.providers.llm.base import LLMProvider
from src.providers.llm.failover import FailoverLLM
from src.providers.types import LLMResponse, Message, Role


class _OkLLM(LLMProvider):
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self._text)

    async def chat_stream(self, messages, tools=None):
        self.calls += 1
        for token in self._text.split():
            yield token + " "


class _FailingLLM(LLMProvider):
    def __init__(self, exc: ProviderError) -> None:
        self._exc = exc
        self.calls = 0

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
        raise self._exc

    async def chat_stream(self, messages, tools=None):
        self.calls += 1
        raise self._exc
        yield  # pragma: no cover - makes this an async generator


_MESSAGES = [Message(Role.USER, "hi")]


def test_failover_requires_a_fallback() -> None:
    with pytest.raises(ValueError, match="at least one fallback"):
        FailoverLLM(_OkLLM("a"))


@pytest.mark.asyncio
async def test_primary_used_when_healthy() -> None:
    primary, fallback = _OkLLM("primary"), _OkLLM("fallback")
    response = await FailoverLLM(primary, fallback).chat(_MESSAGES)
    assert response.text == "primary"
    assert fallback.calls == 0   # fallback never touched


@pytest.mark.asyncio
async def test_falls_over_to_secondary_on_quota() -> None:
    primary = _FailingLLM(ProviderQuotaError("daily quota"))
    fallback = _OkLLM("fallback")
    events: list[tuple[str, str | None, str]] = []

    def record(failed, nxt, exc):
        events.append((failed, nxt, str(exc)))

    failover = FailoverLLM(primary, fallback, on_degrade=record)
    response = await failover.chat(_MESSAGES)

    assert response.text == "fallback"
    assert primary.calls == 1 and fallback.calls == 1
    assert events == [("_FailingLLM", "_OkLLM", "daily quota")]   # degradation reported


@pytest.mark.asyncio
async def test_raises_when_all_providers_fail() -> None:
    primary = _FailingLLM(ProviderError("down"))
    secondary = _FailingLLM(ProviderQuotaError("also down"))
    with pytest.raises(ProviderQuotaError, match="also down"):
        await FailoverLLM(primary, secondary).chat(_MESSAGES)


@pytest.mark.asyncio
async def test_stream_fails_over_before_first_token() -> None:
    primary = _FailingLLM(ProviderQuotaError("quota"))
    fallback = _OkLLM("hello world")
    deltas = [d async for d in FailoverLLM(primary, fallback).chat_stream(_MESSAGES)]
    assert "".join(deltas).strip() == "hello world"


@pytest.mark.asyncio
async def test_async_degrade_hook_is_awaited() -> None:
    seen: list[str] = []

    async def hook(failed, nxt, exc):
        seen.append(failed)

    failover = FailoverLLM(_FailingLLM(ProviderError("x")), _OkLLM("ok"), on_degrade=hook)
    await failover.chat(_MESSAGES)
    assert seen == ["_FailingLLM"]
