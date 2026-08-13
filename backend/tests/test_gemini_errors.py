"""Gemini SDK errors become clean ProviderErrors — so FailoverLLM can fail over,
including on the streaming path (the live bug: a 429 mid-interview crashed the call)."""

from __future__ import annotations

import pytest

from src.providers.errors import ProviderError, ProviderQuotaError
from src.providers.llm.gemini import GeminiLLM, _to_provider_error
from src.providers.types import Message, Role


def test_to_provider_error_maps_quota_to_quota_error() -> None:
    class _Err(Exception):
        code = 429

    assert isinstance(_to_provider_error(_Err("resource_exhausted")), ProviderQuotaError)


def test_to_provider_error_maps_other_errors_to_provider_error() -> None:
    class _Err(Exception):
        code = 500

    err = _to_provider_error(_Err("boom"))
    assert isinstance(err, ProviderError) and not isinstance(err, ProviderQuotaError)


@pytest.mark.asyncio
async def test_chat_stream_wraps_sdk_error_so_failover_can_catch_it() -> None:
    genai_errors = pytest.importorskip("google.genai.errors")

    class _FakeQuota(genai_errors.APIError):
        def __init__(self) -> None:  # bypass APIError's arg-heavy constructor
            self.code = 429
            self.message = "quota"

        def __str__(self) -> str:
            return "RESOURCE_EXHAUSTED quota"

    class _Models:
        async def generate_content_stream(self, **kwargs):
            raise _FakeQuota()

    llm = GeminiLLM(api_key="dummy")
    llm._client = type("C", (), {"aio": type("A", (), {"models": _Models()})()})()

    with pytest.raises(ProviderQuotaError):  # a wrapped ProviderError, not the raw SDK ClientError
        _ = [delta async for delta in llm.chat_stream([Message(Role.USER, "hi")])]
