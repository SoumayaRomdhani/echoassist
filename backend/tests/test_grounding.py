"""Grounded responder tool loop, validated with a fake LLM + retriever."""

from __future__ import annotations

import pytest

from src.agent.grounding import SEARCH_TOOL, GroundedResponder
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall
from src.rag.types import Chunk, ScoredChunk


class ScriptedLLM(LLMProvider):
    """Returns queued responses; records whether tools were offered each call."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.calls = 0
        self.tools_offered: list[bool] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.tools_offered.append(tools is not None)
        self.calls += 1
        return self._responses.pop(0)


class FakeRetriever:
    def __init__(self, chunks: list[ScoredChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[ScoredChunk]:
        self.queries.append(query)
        return self._chunks


def _responder(llm, retriever) -> GroundedResponder:
    return GroundedResponder(llm, retriever, system_prompt="You are a screening assistant.")


@pytest.mark.asyncio
async def test_tool_loop_retrieves_then_answers_with_citation() -> None:
    chunk = ScoredChunk(Chunk("interview_process.md#0", "interview_process.md", "...", 0), 1.0)
    retriever = FakeRetriever([chunk])
    search_call = ToolCall("c1", "search_knowledge_base", {"query": "process"})
    llm = ScriptedLLM(
        [
            LLMResponse(text="", tool_calls=[search_call]),
            LLMResponse(text="The process has four stages [interview_process.md]."),
        ]
    )

    answer = await _responder(llm, retriever).answer("What is the interview process?")

    assert retriever.queries == ["process"]
    assert answer.tool_calls == 1
    assert answer.citations == ["interview_process.md"]   # citation kept in metadata
    assert answer.text == "The process has four stages."  # ...but stripped from spoken text
    assert "[" not in answer.text
    assert answer.retrieved == [chunk]
    assert llm.tools_offered[0] is True  # tools were offered to the model


@pytest.mark.asyncio
async def test_direct_answer_without_tool_call() -> None:
    llm = ScriptedLLM([LLMResponse(text="I don't have that information.")])
    answer = await _responder(llm, FakeRetriever([])).answer("unrelated question")

    assert answer.tool_calls == 0
    assert answer.citations == []
    assert "don't have" in answer.text


def test_search_tool_schema_is_well_formed() -> None:
    assert SEARCH_TOOL.name == "search_knowledge_base"
    assert SEARCH_TOOL.parameters["required"] == ["query"]
    assert SEARCH_TOOL.parameters["properties"]["query"]["type"] == "string"


def test_spoken_strips_citations_and_tidies_punctuation() -> None:
    from src.agent.grounding import _spoken

    assert _spoken("It is fully remote [remote_work_policy.md].") == "It is fully remote."
    assert _spoken("Pay is 65k [a.md] to 85k [b.md].") == "Pay is 65k to 85k."
    assert "[" not in _spoken("See [x.md] for details [y.md]")
