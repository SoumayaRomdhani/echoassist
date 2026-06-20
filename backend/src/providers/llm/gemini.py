"""Google Gemini LLM (free-tier-friendly default for dev).

Uses the ``google-genai`` SDK. The SDK is imported lazily so the rest of the app
runs without it installed. Tool calling is wired through Sprint 2; Sprint 1 uses
the text path only.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.providers.errors import ProviderConfigError
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, Role, ToolSpec

if TYPE_CHECKING:
    from google import genai

log = logging.getLogger("echoassist.llm.gemini")


def _split_messages(messages: list[Message]) -> tuple[str, list[dict]]:
    """Split our messages into a Gemini ``system_instruction`` + ``contents`` list.

    Gemini roles are ``user`` and ``model``; system text is passed separately.
    """
    system_parts: list[str] = []
    contents: list[dict] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            system_parts.append(message.content)
        else:
            role = "model" if message.role is Role.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
    return "\n\n".join(system_parts).strip(), contents


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

    def _config(self, system_instruction: str):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=self._temperature,
            max_output_tokens=self._max_tokens,
        )

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        system_instruction, contents = _split_messages(messages)
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=self._config(system_instruction),
        )
        usage = None
        if getattr(response, "usage_metadata", None) is not None:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
            }
        return LLMResponse(text=(response.text or "").strip(), usage=usage)

    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[str]:
        system_instruction, contents = _split_messages(messages)
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=self._config(system_instruction),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
