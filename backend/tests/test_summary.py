"""Post-call summary generation: transcript use, empty/truncated guards, retry."""

from __future__ import annotations

import pytest

from src.agent.state import ConversationState
from src.agent.summary import SummaryGenerator
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message


class ScriptedLLM(LLMProvider):
    """Returns queued replies (repeats the last); records call count + last messages."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls = 0
        self.seen: list[Message] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.seen = list(messages)
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return LLMResponse(text=reply)


def _state() -> ConversationState:
    state = ConversationState(call_id="c1")
    state.add_turn("assistant", "How many years of experience do you have?")
    state.add_turn("user", "About six years with Python.")
    return state


@pytest.mark.asyncio
async def test_complete_summary_is_used_as_is() -> None:
    llm = ScriptedLLM(["The candidate has six years of Python experience and is available soon."])
    summary = await SummaryGenerator(llm).summarize(_state())

    assert summary.startswith("The candidate has six years")
    assert llm.calls == 1                                   # no retry needed
    assert any("six years" in m.content for m in llm.seen)  # transcript reached the model


@pytest.mark.asyncio
async def test_truncated_summary_triggers_one_retry_then_falls_back() -> None:
    llm = ScriptedLLM(["They are"])  # truncated, both attempts
    summary = await SummaryGenerator(llm).summarize(_state())

    assert llm.calls == 2                  # retried exactly once
    assert summary != "They are"           # truncated output not returned
    assert "no reliable summary" in summary.lower()


@pytest.mark.asyncio
async def test_retry_recovers_a_complete_summary() -> None:
    llm = ScriptedLLM(["They are", "The candidate has six years of solid Python experience."])
    summary = await SummaryGenerator(llm).summarize(_state())

    assert llm.calls == 2
    assert summary.startswith("The candidate has six years")


@pytest.mark.asyncio
async def test_empty_transcript_returns_fallback_without_calling_llm() -> None:
    llm = ScriptedLLM(["unused"])
    summary = await SummaryGenerator(llm).summarize(ConversationState(call_id="c1"))

    assert "no transcript" in summary.lower()
    assert llm.calls == 0
