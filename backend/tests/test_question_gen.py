"""Question generation from a job description: tool-call parsing, JSON fallback, guardrails."""

from __future__ import annotations

import pytest

from src.agent.question_gen import QuestionGenerator, normalize_questions
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall


class ToolCallLLM(LLMProvider):
    def __init__(self, arguments: dict) -> None:
        self._arguments = arguments

    async def chat(self, messages, tools=None) -> LLMResponse:
        call = ToolCall("q1", "record_questions", self._arguments)
        return LLMResponse(text="", tool_calls=[call])


class TextJsonLLM(LLMProvider):
    def __init__(self, text: str) -> None:
        self._text = text

    async def chat(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(text=self._text)


class ToolFailsThenJsonLLM(LLMProvider):
    """Raises on tool calls (like a model that can't do function calling), JSON otherwise."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def chat(self, messages, tools=None) -> LLMResponse:
        if tools:
            raise ProviderError("tool_use_failed")
        return LLMResponse(text=self._text)


# --------------------------------------------------------------------------- #
# normalize_questions — guardrails (pure, no LLM)                             #
# --------------------------------------------------------------------------- #
def test_normalize_assigns_ids_slots_and_enabled() -> None:
    out = normalize_questions([{"text": "How many years of Python?", "slot": "years_python"}])
    assert out == [
        {"id": "q1", "text": "How many years of Python?", "slot": "years_python", "enabled": True}
    ]


def test_normalize_slugifies_and_dedupes_slots() -> None:
    out = normalize_questions([
        {"text": "Do you know React?"},              # slot derived from text
        {"text": "Do you know React?"},              # duplicate -> uniquified
    ])
    assert out[0]["slot"] == "do_you_know_react"
    assert out[1]["slot"] == "do_you_know_react_2"


def test_normalize_drops_empty_and_bare_strings_supported() -> None:
    out = normalize_questions(["   ", "Are you available immediately?", {"text": ""}])
    assert len(out) == 1
    assert out[0]["text"] == "Are you available immediately?"
    assert out[0]["slot"] == "are_you_available_immediately"


def test_normalize_clamps_count() -> None:
    raw = [{"text": f"Question number {i}?"} for i in range(20)]
    out = normalize_questions(raw, max_questions=3)
    assert len(out) == 3
    assert [q["id"] for q in out] == ["q1", "q2", "q3"]


# --------------------------------------------------------------------------- #
# QuestionGenerator — LLM paths (mocked)                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generate_via_tool_call() -> None:
    llm = ToolCallLLM({"questions": [
        {"text": "Years of experience with Go?", "slot": "years_go"},
        {"text": "Comfortable with on-call rotations?"},
    ]})
    out = await QuestionGenerator(llm).generate("Senior Go engineer, on-call required.")
    assert [q["slot"] for q in out] == ["years_go", "comfortable_with_on_call_rotations"]
    assert all(q["enabled"] for q in out)


class FlattenedToolCallsLLM(LLMProvider):
    """Reproduces Gemini flattening an array into one tool call per question."""

    async def chat(self, messages, tools=None) -> LLMResponse:
        calls = [
            ToolCall("c1", "record_questions", {"text": "Years with Python?", "slot": "years_py"}),
            ToolCall("c2", "record_questions", {"text": "Comfortable with on-call?"}),
        ]
        return LLMResponse(text="", tool_calls=calls)


class EmptyToolThenJsonLLM(LLMProvider):
    """Gemini-like: an EMPTY tool response (no error, no call), then valid JSON without tools."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def chat(self, messages, tools=None) -> LLMResponse:
        if tools is not None:
            return LLMResponse(text="", tool_calls=[])  # the Gemini failure mode
        return LLMResponse(text=self._payload)


@pytest.mark.asyncio
async def test_generate_retries_via_json_when_tool_path_is_empty() -> None:
    # Reproduces the live bug: Gemini emits an empty function call (not an error, so failover
    # never fires) -> 0 questions. The JSON retry must recover them.
    payload = '{"questions": ["Years in cloud security?", "AWS IAM experience?"]}'
    out = await QuestionGenerator(EmptyToolThenJsonLLM(payload)).generate("Cloud Security role")
    assert [q["text"] for q in out] == ["Years in cloud security?", "AWS IAM experience?"]


@pytest.mark.asyncio
async def test_generate_handles_flattened_tool_calls() -> None:
    # No "questions" key + one call per item — must still yield both questions, not [].
    out = await QuestionGenerator(FlattenedToolCallsLLM()).generate("Backend role")
    assert [q["slot"] for q in out] == ["years_py", "comfortable_with_on_call"]


@pytest.mark.asyncio
async def test_generate_accepts_array_of_strings() -> None:
    llm = ToolCallLLM({"questions": ["Years with Go?", "Notice period?"]})
    out = await QuestionGenerator(llm).generate("Go role")
    assert [q["text"] for q in out] == ["Years with Go?", "Notice period?"]
    assert [q["slot"] for q in out] == ["years_with_go", "notice_period"]


@pytest.mark.asyncio
async def test_generate_via_text_json_when_no_tool_call() -> None:
    payload = '{"questions": [{"text": "Notice period?", "slot": "notice"}]}'
    out = await QuestionGenerator(TextJsonLLM(f"Sure: {payload}")).generate("Backend role")
    assert out == [{"id": "q1", "text": "Notice period?", "slot": "notice", "enabled": True}]


@pytest.mark.asyncio
async def test_generate_falls_back_to_json_when_tool_call_errors() -> None:
    payload = '{"questions": [{"text": "Availability to start?"}]}'
    out = await QuestionGenerator(ToolFailsThenJsonLLM(payload)).generate("Data engineer")
    assert len(out) == 1
    assert out[0]["slot"] == "availability_to_start"


@pytest.mark.asyncio
async def test_generate_tolerates_garbage_payload() -> None:
    out = await QuestionGenerator(TextJsonLLM("no json here")).generate("Anything")
    assert out == []
