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


def _grounded_llm(answer_text: str, query: str) -> ScriptedLLM:
    call = ToolCall("c1", "search_knowledge_base", {"query": query})
    return ScriptedLLM([LLMResponse(text="", tool_calls=[call]), LLMResponse(text=answer_text)])


@pytest.mark.asyncio
async def test_french_question_is_grounded_with_citation() -> None:
    src = "politique_teletravail_fr.md"
    chunk = ScoredChunk(Chunk(f"{src}#0", src, ".", 0), 2.0)
    llm = _grounded_llm(f"Le poste est en télétravail intégral [{src}].", "télétravail")
    answer = await _responder(llm, FakeRetriever([chunk])).answer("Puis-je télétravailler ?")

    assert answer.citations == [src]
    assert "télétravail" in answer.text and "[" not in answer.text


@pytest.mark.asyncio
async def test_french_without_accents_from_stt_still_grounded() -> None:
    src = "remuneration_avantages_fr.md"
    chunk = ScoredChunk(Chunk(f"{src}#0", src, ".", 0), 2.0)
    llm = _grounded_llm(f"La fourchette est 65 000 a 85 000 euros [{src}].", "salaire")
    answer = await _responder(llm, FakeRetriever([chunk])).answer(
        "Quelle est la fourchette de salaire ?"
    )

    assert answer.citations == [src]


@pytest.mark.asyncio
async def test_off_domain_low_confidence_is_deterministically_refused() -> None:
    weak = ScoredChunk(Chunk("x.md#0", "x.md", "irrelevant", 0), -5.0)  # confidence ~0.007
    retriever = FakeRetriever([weak])
    # Even though the model tries to answer after weak context, we must refuse.
    llm = _grounded_llm("The weather is sunny today.", "weather")
    responder = GroundedResponder(
        llm, retriever, system_prompt="You are a screening assistant.", min_confidence=0.1
    )
    answer = await responder.answer("What's the weather in Paris?")

    assert answer.retrieved == []          # weak chunk filtered by the gate
    assert answer.citations == []
    assert "sunny" not in answer.text      # hallucination NOT returned
    assert "recruiter" in answer.text.lower()   # deterministic refusal


@pytest.mark.asyncio
async def test_no_confident_chunk_never_invents_an_answer() -> None:
    retriever = FakeRetriever([])  # nothing retrieved at all
    llm = _grounded_llm("Made-up answer.", "anything")
    responder = GroundedResponder(
        llm, retriever, system_prompt="You are a screening assistant.", min_confidence=0.1
    )
    answer = await responder.answer("Off-topic question?")

    assert answer.retrieved == [] and answer.citations == []
    assert "made-up" not in answer.text.lower()


# --- Retrieve-then-read path (L3): retrieve first, read in a single LLM call ------- #
def _read_responder(llm, retriever) -> GroundedResponder:
    return GroundedResponder(
        llm, retriever, system_prompt="You are a screening assistant.", retrieve_then_read=True
    )


@pytest.mark.asyncio
async def test_retrieve_then_read_answers_in_one_llm_call() -> None:
    chunk = ScoredChunk(Chunk("interview_process.md#0", "interview_process.md", "...", 0), 1.0)
    retriever = FakeRetriever([chunk])
    llm = ScriptedLLM([LLMResponse(text="Four stages [interview_process.md].")])

    answer = await _read_responder(llm, retriever).answer("What is the interview process?")

    assert retriever.queries == ["What is the interview process?"]  # direct retrieve, no tool hop
    assert llm.calls == 1                          # one read call (the tool loop took two)
    assert llm.tools_offered == [False]            # no tool offered on the read path
    assert answer.tool_calls == 0
    assert answer.citations == ["interview_process.md"]
    assert answer.text == "Four stages." and answer.retrieved == [chunk]


@pytest.mark.asyncio
async def test_retrieve_then_read_refuses_without_calling_the_llm() -> None:
    llm = ScriptedLLM([])  # no confident chunk -> the LLM must never be reached
    answer = await _read_responder(llm, FakeRetriever([])).answer("Off-topic?")

    assert llm.calls == 0
    assert answer.retrieved == [] and answer.citations == []
    assert "recruiter" in answer.text.lower()


@pytest.mark.asyncio
async def test_retrieve_then_read_gate_filters_weak_chunks() -> None:
    weak = ScoredChunk(Chunk("x.md#0", "x.md", "irrelevant", 0), -5.0)  # confidence ~0.007
    llm = ScriptedLLM([])  # gate drops the weak chunk -> refuse without an LLM call
    responder = GroundedResponder(
        llm, FakeRetriever([weak]), system_prompt="s", min_confidence=0.1, retrieve_then_read=True
    )
    answer = await responder.answer("What's the weather in Paris?")

    assert llm.calls == 0 and answer.retrieved == []
    assert "recruiter" in answer.text.lower()


@pytest.mark.asyncio
async def test_retrieve_then_read_streaming_streams_grounded_answer() -> None:
    chunk = ScoredChunk(Chunk("remote_work_policy.md#0", "remote_work_policy.md", ".", 0), 2.0)
    llm = ScriptedLLM([LLMResponse(text="It is fully remote [remote_work_policy.md].")])

    responder = _read_responder(llm, FakeRetriever([chunk]))
    deltas = [d async for d in responder.answer_streaming("is it remote?")]

    assert "".join(deltas) == "It is fully remote [remote_work_policy.md]."
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_retrieve_then_read_streaming_refuses_without_confident_chunk() -> None:
    llm = ScriptedLLM([])
    responder = _read_responder(llm, FakeRetriever([]))
    deltas = [d async for d in responder.answer_streaming("Off-topic?")]

    assert "recruiter" in "".join(deltas).lower()
    assert llm.calls == 0


def test_search_tool_schema_is_well_formed() -> None:
    assert SEARCH_TOOL.name == "search_knowledge_base"
    assert SEARCH_TOOL.parameters["required"] == ["query"]
    assert SEARCH_TOOL.parameters["properties"]["query"]["type"] == "string"


def test_spoken_strips_citations_and_tidies_punctuation() -> None:
    from src.agent.grounding import _spoken

    assert _spoken("It is fully remote [remote_work_policy.md].") == "It is fully remote."
    assert _spoken("Pay is 65k [a.md] to 85k [b.md].") == "Pay is 65k to 85k."
    assert "[" not in _spoken("See [x.md] for details [y.md]")
