"""Post-call summary generation."""

from __future__ import annotations

import pytest

from src.agent.state import ConversationState
from src.agent.summary import SummaryGenerator
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message


class EchoLLM(LLMProvider):
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.seen: list[Message] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.seen = list(messages)
        return LLMResponse(text=self._reply)


@pytest.mark.asyncio
async def test_summary_uses_the_transcript() -> None:
    state = ConversationState(call_id="c1")
    state.add_turn("assistant", "How many years of experience do you have?")
    state.add_turn("user", "About six years with Python.")

    llm = EchoLLM("The candidate has six years of Python experience.")
    summary = await SummaryGenerator(llm).summarize(state)

    assert summary == "The candidate has six years of Python experience."
    assert any("six years" in m.content for m in llm.seen)  # transcript reached the model


@pytest.mark.asyncio
async def test_empty_transcript_returns_fallback_without_calling_llm() -> None:
    llm = EchoLLM("should not be used")
    summary = await SummaryGenerator(llm).summarize(ConversationState(call_id="c1"))

    assert "no transcript" in summary.lower()
    assert llm.seen == []  # short-circuited
