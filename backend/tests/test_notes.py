"""Notes extraction: tool-call parsing, slot authority, JSON fallback, schema repair."""

from __future__ import annotations

import pytest

from src.agent.notes import NotesExtractor, validate_and_repair
from src.agent.state import ConversationState
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall

_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_name": {"type": "string"},
        "years_experience": {"type": "string"},
        "primary_stack": {"type": "string"},
        "availability": {"type": "string"},
        "remote_setup": {"type": "string"},
        "salary_expectation": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "overall_fit": {"type": "string", "enum": ["strong", "moderate", "weak", "unknown"]},
    },
    "required": [
        "years_experience", "primary_stack", "availability",
        "remote_setup", "salary_expectation", "overall_fit",
    ],
}


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


def _state_with_slots() -> ConversationState:
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
    llm = ToolCallLLM({
        "years_experience": "WRONG",
        "overall_fit": "strong",
        "strengths": ["clear communicator"],
    })
    notes = await NotesExtractor(llm, _SCHEMA).extract(_state_with_slots())

    assert notes["years_experience"] == "6 years"          # slot wins
    assert notes["primary_stack"] == "Python, FastAPI"
    assert notes["overall_fit"] == "strong"                # enrichment kept
    assert notes["strengths"] == ["clear communicator"]


@pytest.mark.asyncio
async def test_json_fallback_when_model_does_not_call_the_tool() -> None:
    payload = '{"overall_fit": "moderate", "concerns": ["notice period"]}'
    extractor = NotesExtractor(TextJsonLLM(f"Here: {payload}"), _SCHEMA)
    notes = await extractor.extract(_state_with_slots())

    assert notes["overall_fit"] == "moderate"
    assert notes["concerns"] == ["notice period"]
    assert notes["salary_expectation"] == "75k euros"      # slots still applied


@pytest.mark.asyncio
async def test_invalid_or_incomplete_notes_are_repaired_not_saved_raw() -> None:
    # Empty slots: required fields rely on the model, which returns invalid output.
    state = ConversationState(call_id="c2")
    state.add_turn("user", "Some chat.")
    llm = ToolCallLLM({"overall_fit": "excellent", "strengths": "great communicator"})
    notes = await NotesExtractor(llm, _SCHEMA).extract(state)

    assert notes["overall_fit"] == "unknown"                 # invalid enum clamped
    assert notes["strengths"] == ["great communicator"]      # coerced to a list
    assert notes["years_experience"] == ""                   # required-but-missing -> present
    assert set(_SCHEMA["properties"]) == set(notes)          # exactly the schema fields


def test_validate_and_repair_drops_unknown_keys() -> None:
    repaired = validate_and_repair(
        {"overall_fit": "weak", "hallucinated": "nope"}, _SCHEMA
    )
    assert "hallucinated" not in repaired
    assert repaired["overall_fit"] == "weak"
