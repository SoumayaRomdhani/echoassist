"""Grounded responder tool loop, validated with a fake LLM + retriever."""

from __future__ import annotations

import pytest

from src.agent.grounding import SEARCH_TOOL, GroundedResponder
from src.providers.errors import ProviderError
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
    assert "one more detail" in answer.text.lower()


def _grounded_llm(answer_text: str, query: str) -> ScriptedLLM:
    call = ToolCall("c1", "search_knowledge_base", {"query": query})
    return ScriptedLLM([LLMResponse(text="", tool_calls=[call]), LLMResponse(text=answer_text)])


class ToolFailsLLM(LLMProvider):
    """Fails when function calling is offered (like Groq `tool_use_failed`), answers otherwise."""

    def __init__(self, answer_text: str) -> None:
        self._answer_text = answer_text
        self.tools_offered: list[bool] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.tools_offered.append(tools is not None)
        if tools is not None:
            raise ProviderError("tool_use_failed")
        return LLMResponse(text=self._answer_text)

    async def chat_stream(self, messages, tools=None):
        if tools is not None:
            raise ProviderError("tool_use_failed")
        yield self._answer_text


@pytest.mark.asyncio
async def test_answer_falls_back_to_retrieve_then_read_when_tool_calling_fails() -> None:
    # The live failure: Groq returns tool_use_failed on the in-call RAG search tool.
    chunk = ScoredChunk(Chunk("faq.md#0", "faq.md", "It is fully remote.", 0), 2.0)
    retriever = FakeRetriever([chunk])
    llm = ToolFailsLLM("Yes, the role is fully remote [faq.md].")

    answer = await _responder(llm, retriever).answer("Is this role remote?")

    assert llm.tools_offered[0] is True                    # tried tool calling first
    assert retriever.queries == ["Is this role remote?"]   # fell back: retrieved on the question
    assert answer.citations == ["faq.md"]                  # still grounded
    assert answer.text == "Yes, the role is fully remote."


@pytest.mark.asyncio
async def test_answer_fallback_still_refuses_when_nothing_confident() -> None:
    llm = ToolFailsLLM("Made-up answer.")
    answer = await _responder(llm, FakeRetriever([])).answer("Is this role remote?")

    assert answer.tool_calls == 0 and answer.citations == []
    assert "made-up" not in answer.text.lower()            # deterministic refusal, not invention
    assert "one more detail" in answer.text.lower()


@pytest.mark.asyncio
async def test_answer_streaming_falls_back_when_tool_calling_fails() -> None:
    chunk = ScoredChunk(Chunk("faq.md#0", "faq.md", "It is fully remote.", 0), 2.0)
    llm = ToolFailsLLM("Yes, fully remote [faq.md].")

    deltas = [
        d async for d in _responder(llm, FakeRetriever([chunk])).answer_streaming("Remote?")
    ]

    assert "".join(deltas) == "Yes, fully remote [faq.md]."


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
    assert "one more detail" in answer.text.lower()   # deterministic refusal


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


@pytest.mark.asyncio
async def test_deterministic_fallback_never_mentions_knowledge_base() -> None:
    """Fallback must never leak the internal 'knowledge base' phrasing to the caller (req 5)."""
    llm = _grounded_llm("The answer is 42.", "anything")
    responder = GroundedResponder(
        llm, FakeRetriever([]), system_prompt="s", min_confidence=0.1
    )
    answer = await responder.answer("something out of scope")
    assert "knowledge base" not in answer.text.lower()


@pytest.mark.asyncio
async def test_domain_fallback_wording_is_used_when_configured() -> None:
    """A domain may override the fallback wording; the engine uses it verbatim (req 5, 7)."""
    custom = "Let me open a ticket and a colleague will call you back."
    llm = _grounded_llm("Invented steps.", "anything")
    responder = GroundedResponder(
        llm, FakeRetriever([]), system_prompt="s", min_confidence=0.1, fallback_message=custom
    )
    answer = await responder.answer("unresolved issue")
    assert answer.text == custom
    assert "invented" not in answer.text.lower()
    assert "knowledge base" not in answer.text.lower()


@pytest.mark.asyncio
async def test_streaming_fallback_uses_configured_wording() -> None:
    """The streaming path shares the same configurable, KB-free fallback."""
    custom = "I'll have a teammate follow up with you shortly."
    responder = GroundedResponder(
        _grounded_llm("x", "q"), FakeRetriever([]), system_prompt="s",
        min_confidence=0.1, fallback_message=custom,
    )
    out = "".join([delta async for delta in responder.answer_streaming("out of scope")])
    assert out == custom
    assert "knowledge base" not in out.lower()


# --------------------------------------------------------------------------- #
# Retrieve-then-read (caller-led flows pass a clean search query)             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_retrieve_then_read_grounds_on_given_query_without_tool_roundtrip() -> None:
    """With a clean search_query the responder retrieves first and reads — it never lets the
    model skip retrieval (the live bug where a good answer was replaced by the fallback)."""
    chunk = ScoredChunk(Chunk("laptop_slow.md#0", "laptop_slow.md", "free disk space", 0), 2.0)
    retriever = FakeRetriever([chunk])
    llm = ScriptedLLM([LLMResponse(text="Let's free up disk space [laptop_slow.md].")])

    answer = await _responder(llm, retriever).answer(
        "Recent caller context: laptop slow\nCaller replied: still slow",
        search_query="slow laptop disk space Task Manager",
    )

    assert retriever.queries == ["slow laptop disk space Task Manager"]  # our clean query drove it
    assert llm.calls == 1 and llm.tools_offered == [False]  # one read call, no search tool hop
    assert answer.citations == ["laptop_slow.md"]
    assert answer.text == "Let's free up disk space."


@pytest.mark.asyncio
async def test_retrieve_then_read_falls_back_without_calling_the_model() -> None:
    weak = ScoredChunk(Chunk("x.md#0", "x.md", "irrelevant", 0), -5.0)  # below the gate
    llm = ScriptedLLM([])  # must NOT be consulted when nothing is confidently retrieved
    responder = GroundedResponder(
        llm, FakeRetriever([weak]), system_prompt="s", min_confidence=0.1
    )
    answer = await responder.answer("ctx", search_query="off topic")

    assert llm.calls == 0
    assert answer.citations == []
    assert "knowledge base" not in answer.text.lower()


@pytest.mark.asyncio
async def test_retrieve_then_read_streaming_grounds_on_query() -> None:
    src = "vpn_troubleshooting.md"
    chunk = ScoredChunk(Chunk(f"{src}#0", src, "reset", 0), 2.0)
    retriever = FakeRetriever([chunk])
    llm = ScriptedLLM([LLMResponse(text="Restart the VPN client [vpn_troubleshooting.md].")])

    deltas = [
        d async for d in _responder(llm, retriever).answer_streaming(
            "Caller replied: still failing", search_query="vpn authentication failed"
        )
    ]

    assert retriever.queries == ["vpn authentication failed"]
    assert "Restart the VPN client" in "".join(deltas)


def test_search_tool_schema_is_well_formed() -> None:
    assert SEARCH_TOOL.name == "search_knowledge_base"
    assert SEARCH_TOOL.parameters["required"] == ["query"]
    assert SEARCH_TOOL.parameters["properties"]["query"]["type"] == "string"


def test_spoken_strips_citations_and_tidies_punctuation() -> None:
    from src.agent.grounding import _spoken

    assert _spoken("It is fully remote [remote_work_policy.md].") == "It is fully remote."
    assert _spoken("Pay is 65k [a.md] to 85k [b.md].") == "Pay is 65k to 85k."
    assert "[" not in _spoken("See [x.md] for details [y.md]")


def test_spoken_removes_dangling_reference_phrases_left_by_citations() -> None:
    """After citation removal the audio must not contain broken half-phrases (req 6)."""
    from src.agent.grounding import _spoken

    # "as mentioned in.", "according to.", "... steps in.", and a bare dangling "in".
    assert _spoken("Use the portal as mentioned in [account_permissions.md].") == "Use the portal."
    assert _spoken("Reset it, according to [password_reset.md].") == "Reset it."
    assert _spoken("The next step is in [laptop_slow.md].") == "The next step is."
    assert (
        _spoken("I found the troubleshooting steps in [laptop_slow.md]. Let's restart.")
        == "I found the troubleshooting steps. Let's restart."
    )
    # No dangling "in"/"according to"/"as mentioned in" survives anywhere.
    for broken in ("according to.", "as mentioned in.", " in.", "steps in."):
        assert broken not in _spoken("Do X, according to [a.md]. See it as mentioned in [b.md].")
    # A possessive before the citation is absorbed too ("as per our." was leaking into audio).
    assert _spoken("I'll follow up, as per our [escalation_policy.md].") == "I'll follow up."
    assert _spoken("It's in the [manual.md].") == "It's."


def test_spoken_strips_passive_aggressive_phrases() -> None:
    """"as I mentioned earlier" / "as I said" must never reach the caller's ears."""
    from src.agent.grounding import _spoken

    assert (
        _spoken("Let's reset your password, as I mentioned earlier, can you try that?")
        == "Let's reset your password, can you try that?"
    )
    assert "as i said" not in _spoken("As I said, go to the portal.").lower()
    assert _spoken("As I said, go to the portal.") == "go to the portal."


def test_spoken_preserves_legitimate_words_before_punctuation() -> None:
    """A real word that merely sits before punctuation (no citation) must survive."""
    from src.agent.grounding import _spoken

    assert _spoken("Please log in.") == "Please log in."
    assert _spoken("Sign in to continue.") == "Sign in to continue."
    assert _spoken("That depends on the plan.") == "That depends on the plan."
