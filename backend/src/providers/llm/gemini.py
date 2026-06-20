"""Google Gemini LLM (free-tier-friendly default for dev).

Uses the ``google-genai`` SDK (imported lazily). Supports text and function
calling: tools are passed as function declarations, and the model's function
calls are surfaced as :class:`ToolCall` for the caller to execute and feed back.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.providers.errors import ProviderConfigError, ProviderError, ProviderQuotaError
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, Role, ToolCall, ToolSpec

if TYPE_CHECKING:
    from google import genai

log = logging.getLogger("echoassist.llm.gemini")

_QUOTA_MESSAGE = (
    "Gemini rate limit / quota exceeded. Wait ~60s and retry, or switch to a local "
    "model with LLM_PROVIDER=ollama in backend/.env."
)


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return getattr(exc, "code", None) == 429 or "resource_exhausted" in text or "quota" in text


def _to_provider_error(exc: Exception) -> ProviderError:
    """Map a Gemini API error to a clean ProviderError (no raw traceback for the user)."""
    if _is_quota_error(exc):
        return ProviderQuotaError(_QUOTA_MESSAGE)
    code = getattr(exc, "code", None)
    message = (getattr(exc, "message", None) or str(exc))[:200]
    return ProviderError(f"Gemini API error ({code}): {message} — please retry in a moment.")


def _to_gemini_schema(schema: dict) -> dict:
    """Convert a standard JSON Schema to Gemini's (uppercase ``type`` values)."""
    if not isinstance(schema, dict):
        return schema
    converted: dict = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            converted[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            converted[key] = {k: _to_gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            converted[key] = _to_gemini_schema(value)
        else:
            converted[key] = value
    return converted


def _build_contents(messages: list[Message], types) -> tuple[str, list]:
    """Split messages into a Gemini ``system_instruction`` + ``contents`` list."""
    system_parts: list[str] = []
    contents: list = []
    for message in messages:
        if message.role is Role.SYSTEM:
            system_parts.append(message.content)
        elif message.role is Role.TOOL:
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=message.name or "tool", response={"result": message.content}
                        )
                    ],
                )
            )
        elif message.role is Role.ASSISTANT and message.tool_calls:
            parts = [
                types.Part(function_call=types.FunctionCall(name=tc.name, args=tc.arguments))
                for tc in message.tool_calls
            ]
            contents.append(types.Content(role="model", parts=parts))
        else:
            role = "model" if message.role is Role.ASSISTANT else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=message.content)]))
    return "\n\n".join(system_parts).strip(), contents


def _extract_text(response) -> str:
    parts: list[str] = []
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if getattr(part, "text", None):
                parts.append(part.text)
    return "".join(parts).strip()


class GeminiLLM(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> None:
        if not api_key:
            raise ProviderConfigError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and add it to backend/.env"
            )
        from google import genai

        self._client: genai.Client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _config(self, types, system_instruction: str, tools: list[ToolSpec] | None):
        kwargs = {
            "system_instruction": system_instruction or None,
            "temperature": self._temperature,
            "max_output_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters=_to_gemini_schema(t.parameters),
                        )
                        for t in tools
                    ]
                )
            ]
            # We run the tool loop ourselves; don't let the SDK auto-execute callables.
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )
        return types.GenerateContentConfig(**kwargs)

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        from google.genai import errors as genai_errors
        from google.genai import types

        system_instruction, contents = _build_contents(messages, types)
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=self._config(types, system_instruction, tools),
            )
        except genai_errors.APIError as exc:
            raise _to_provider_error(exc) from exc
        tool_calls = [
            ToolCall(
                id=getattr(fc, "id", None) or f"{fc.name}-{i}",
                name=fc.name,
                arguments=dict(fc.args or {}),
            )
            for i, fc in enumerate(response.function_calls or [])
        ]
        return LLMResponse(text=_extract_text(response), tool_calls=tool_calls)

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        from google.genai import types

        system_instruction, contents = _build_contents(messages, types)
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=self._config(types, system_instruction, tools),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
