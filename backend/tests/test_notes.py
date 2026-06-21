"""Notes extraction: tool-call parsing, slot authority, JSON fallback."""

from __future__ import annotations

import pytest

from src.agent.notes import NotesExtractor
from src.agent.state import ConversationState
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall

_SCHEMA = {"type": "object", "properties": {}}


class ToolCallLLM(LLMProvider):
    def __init__(self, arguments: dict) -> None:
        self._arguments = arguments

    async def chat(self, messages, tools=None) -> LLMResponse:
        call = ToolCall("n1", "record_screening_notes", self._arguments)
        return LLMResponse(text="", tool_calls=[call])


class TextJsonLLM(LLMProvider):
    def __init__(self, text: str) -> None:
        self._text = text

    async def chat(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(text=self._text)


def _state() -> ConversationState:
    state = ConversationState(call_id="c1")
    state.slots = {
        "years_experience": "6 years",
        "primary_stack": "Python, FastAPI",
        "availability": "3 weeks",
        "remote_setup": "remote, Tunis CET",
        "salary_expectation": "75k euros",
    }
    state.add_turn("user", "I have six years with Python.")
    return state


@pytest.mark.asyncio
async def test_slots_are_authoritative_over_model_output() -> None:
    # Model returns a wrong experience but rich enrichment.
    llm = ToolCallLLM({
        "years_experience": "WRONG",
        "overall_fit": "strong",
        "strengths": ["clear communicator"],
    })
    notes = await NotesExtractor(llm, _SCHEMA).extract(_state())

    assert notes["years_experience"] == "6 years"          # slot wins
    assert notes["primary_stack"] == "Python, FastAPI"     # slot filled even if model omitted it
    assert notes["overall_fit"] == "strong"                # enrichment kept
    assert notes["strengths"] == ["clear communicator"]


@pytest.mark.asyncio
async def test_json_fallback_when_model_does_not_call_the_tool() -> None:
    payload = '{"overall_fit": "moderate", "concerns": ["notice period"]}'
    llm = TextJsonLLM(f"Here are the notes: {payload}")
    notes = await NotesExtractor(llm, _SCHEMA).extract(_state())

    assert notes["overall_fit"] == "moderate"
    assert notes["concerns"] == ["notice period"]
    assert notes["salary_expectation"] == "75k euros"      # slots still applied
