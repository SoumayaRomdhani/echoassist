"""Groq LLM (free, fast cloud drop-in — Sprint 8 Path B).

Same :class:`LLMProvider` contract as Gemini/Ollama — selecting it is purely an
env change (``LLM_PROVIDER=groq``). Groq serves open models (Llama, ...) on
custom inference hardware at very high tokens/sec, and its free tier is far more
generous than Gemini's (e.g. ~14,400 requests/day for ``llama-3.1-8b-instant``),
so the live voice loop runs fast and doesn't exhaust quota after a few turns.

Uses the ``groq`` SDK (imported lazily); the API is OpenAI-compatible. Supports
text and tool calling: tools are passed as OpenAI-style ``function`` definitions,
and the model's ``tool_calls`` are surfaced as :class:`ToolCall` for the caller
to execute and feed back as TOOL messages.

The default model is ``llama-3.3-70b-versatile``: it does function calling
reliably, which the app depends on (RAG ``SEARCH_TOOL`` and notes extraction).
``llama-3.1-8b-instant`` is faster/higher-quota but frequently emits malformed
tool calls (Groq 400 ``tool_use_failed``) — only safe when no tool paths are hit.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.observability.tracing import span
from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, Role, ToolCall, ToolSpec

if TYPE_CHECKING:
    import groq

log = logging.getLogger("echoassist.llm.groq")

_QUOTA_MESSAGE = (
    "Groq rate limit / quota exceeded. Wait a moment and retry, set "
    "LLM_FALLBACK_PROVIDER in backend/.env for automatic degradation, or check "
    "limits at https://console.groq.com/settings/limits"
)


def _to_provider_error(exc: groq.APIError) -> ProviderError:
    """Map a Groq API error to a clean ProviderError (no raw traceback for the user)."""
    import groq

    if isinstance(exc, groq.RateLimitError):
        return ProviderQuotaError(_QUOTA_MESSAGE)
    status = getattr(exc, "status_code", None)
    message = (getattr(exc, "message", None) or str(exc))[:200]
    return ProviderError(f"Groq API error ({status}): {message} — please retry in a moment.")


def _to_groq_messages(messages: list[Message]) -> list[dict]:
    """Convert our messages to OpenAI-style chat messages (Groq's wire format)."""
    out: list[dict] = []
    for m in messages:
        if m.role is Role.ASSISTANT and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        elif m.role is Role.TOOL:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or m.name or "tool",
                    "content": m.content,
                }
            )
        else:
            out.append({"role": m.role.value, "content": m.content})
    return out


def _to_groq_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def _as_dict(arguments) -> dict:
    """Groq returns tool-call arguments as a JSON string; tolerate a dict just in case."""
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return dict(arguments or {})


class GroqLLM(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "GROQ_API_KEY is not set. Get a free key at "
                "https://console.groq.com/keys and add it to backend/.env"
            )
        import groq

        self._client = groq.AsyncGroq(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _request_kwargs(self, messages: list[Message], tools: list[ToolSpec] | None) -> dict:
        kwargs: dict = {
            "model": self._model,
            "messages": _to_groq_messages(messages),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = _to_groq_tools(tools)
        return kwargs

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        import groq

        with span("llm.chat", **{"llm.provider": "groq", "llm.model": self._model}):
            try:
                response = await self._client.chat.completions.create(
                    **self._request_kwargs(messages, tools)
                )
            except groq.APIError as exc:
                raise _to_provider_error(exc) from exc

        choice = response.choices[0]
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=_as_dict(tc.function.arguments),
            )
            for tc in (choice.message.tool_calls or [])
        ]
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=(choice.message.content or "").strip(),
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=(
                {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}
                if usage
                else None
            ),
        )

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        import groq

        with span("llm.chat_stream", **{"llm.provider": "groq", "llm.model": self._model}):
            try:
                stream = await self._client.chat.completions.create(
                    **self._request_kwargs(messages, tools), stream=True
                )
                async for chunk in stream:
                    piece = chunk.choices[0].delta.content
                    if piece:
                        yield piece
            except groq.APIError as exc:
                raise _to_provider_error(exc) from exc

    async def aclose(self) -> None:
        await self._client.close()
