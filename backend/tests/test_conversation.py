"""Conversational agent: the model decides when to search, keeps context, declines off-topic.

Validated with a scripted LLM + fake retriever (no real models). These tests pin the
architecture the fluency depends on: RAG only when the model asks for it, follow-ups answered
from the conversation, and a graceful (context-keeping) decline instead of a canned reset.
"""

from __future__ import annotations

import pytest

from src.agent.conversation import ConversationAgent
from src.agent.dialogue import DialogueManager
from src.agent.domain import DomainConfig
from src.agent.state import ConversationState, InMemoryStateStore
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, Message, Role, ToolCall
from src.rag.types import Chunk, ScoredChunk


class ScriptedLLM(LLMProvider):
    """Returns queued responses; records the messages it saw and whether tools were offered."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.tools_offered: list[bool] = []
        self.seen: list[Message] = []

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.tools_offered.append(tools is not None)
        self.seen = list(messages)
        self.calls += 1
        return self._responses.pop(0)


class FakeRetriever:
    def __init__(self, chunks: list[ScoredChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[ScoredChunk]:
        self.queries.append(query)
        return self._chunks


def _state(*turns: tuple[str, str], **kw) -> ConversationState:
    state = ConversationState(call_id="c", **kw)
    for role, text in turns:
        state.add_turn(role, text)
    return state


def _agent(llm, retriever, **kw) -> ConversationAgent:
    return ConversationAgent(llm, retriever, system_prompt="You are a support agent.", **kw)


def _chunk(source: str) -> ScoredChunk:
    return ScoredChunk(Chunk(f"{source}#0", source, "some passage", 0), 2.0)


# --------------------------------------------------------------------------- #
# The core decision: search only when the model asks                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_follow_up_is_answered_without_searching() -> None:
    llm = ScriptedLLM([LLMResponse(text="Great — go ahead and forget the network.")])
    retriever = FakeRetriever([_chunk("wifi_network.md")])
    state = _state(("assistant", "Can your phone connect?"), ("user", "yes, it connects"))

    reply = await _agent(llm, retriever).respond(state)

    assert reply.used_rag is False
    assert retriever.queries == []            # NO retrieval for a follow-up
    assert "forget the network" in reply.text
    assert llm.tools_offered == [True]        # the tool was offered; the model chose not to use it


@pytest.mark.asyncio
async def test_factual_question_triggers_search_and_cites() -> None:
    retriever = FakeRetriever([_chunk("wifi_network.md")])
    search = ToolCall("c1", "search_knowledge_base", {"query": "wifi not connecting"})
    llm = ScriptedLLM([
        LLMResponse(text="", tool_calls=[search]),
        LLMResponse(text="Try restarting your router [wifi_network.md]."),
    ])

    reply = await _agent(llm, retriever).respond(_state(("user", "my wifi won't connect")))

    assert reply.used_rag is True
    assert retriever.queries == ["wifi not connecting"]
    assert reply.citations == ["wifi_network.md"]
    assert reply.text == "Try restarting your router."   # citation stripped from spoken text


@pytest.mark.asyncio
async def test_off_topic_declines_gracefully_and_keeps_context() -> None:
    """Off-topic must NOT reset the conversation — the model declines and steers back."""
    llm = ScriptedLLM([
        LLMResponse(text="I can only help with your Wi-Fi issue — did forgetting the network work?")
    ])
    retriever = FakeRetriever([])
    state = _state(
        ("assistant", "Try forgetting the network."),
        ("user", "who is the president of France?"),
    )

    reply = await _agent(llm, retriever).respond(state)

    assert reply.used_rag is False
    assert retriever.queries == []
    assert "Wi-Fi" in reply.text
    assert "which system" not in reply.text.lower()      # NOT the old canned reset


@pytest.mark.asyncio
async def test_empty_retrieval_still_answers_from_context_no_canned_refuse() -> None:
    """The model may search, find nothing, and still reply gracefully (no hard canned refusal)."""
    search = ToolCall("c1", "search_knowledge_base", {"query": "x"})
    llm = ScriptedLLM([
        LLMResponse(text="", tool_calls=[search]),
        LLMResponse(text="I don't have that specific detail — I can raise a ticket for you."),
    ])
    agent = ConversationAgent(
        llm, FakeRetriever([]), system_prompt="s", min_confidence=0.1
    )

    reply = await agent.respond(_state(("user", "some obscure thing")))

    assert reply.used_rag is True
    assert "raise a ticket" in reply.text
    assert "knowledge base" not in reply.text.lower()


@pytest.mark.asyncio
async def test_agent_receives_the_whole_conversation_history() -> None:
    llm = ScriptedLLM([LLMResponse(text="Okay, let's try the next step.")])
    state = _state(
        ("user", "my laptop is slow"),
        ("assistant", "try a restart"),
        ("user", "done, still slow"),
    )

    await _agent(llm, FakeRetriever([])).respond(state)

    user_texts = [m.content for m in llm.seen if m.role is Role.USER]
    assert "my laptop is slow" in user_texts          # it remembers the original issue
    assert "done, still slow" in user_texts


@pytest.mark.asyncio
async def test_state_note_is_injected_into_the_system_prompt() -> None:
    llm = ScriptedLLM([LLMResponse(text="ok")])
    await _agent(llm, FakeRetriever([])).respond(
        _state(("user", "hi")), state_note="Current issue: slow laptop",
    )
    system = next(m.content for m in llm.seen if m.role is Role.SYSTEM)
    assert "Current issue: slow laptop" in system


# --------------------------------------------------------------------------- #
# Streaming                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_streaming_direct_answer_does_not_search() -> None:
    llm = ScriptedLLM([LLMResponse(text="Sure, take your time.")])
    retriever = FakeRetriever([])

    used_rag, stream = await _agent(llm, retriever).begin_stream(_state(("user", "hold on a sec")))
    out = "".join([d async for d in stream])

    assert used_rag is False
    assert retriever.queries == []
    assert "take your time" in out


@pytest.mark.asyncio
async def test_streaming_factual_answer_searches_first() -> None:
    retriever = FakeRetriever([_chunk("a.md")])
    search = ToolCall("c1", "search_knowledge_base", {"query": "reset password"})
    llm = ScriptedLLM([
        LLMResponse(text="", tool_calls=[search]),
        LLMResponse(text="Go to reset.acteek.local [a.md]."),
    ])

    state = _state(("user", "how do I reset?"))
    used_rag, stream = await _agent(llm, retriever).begin_stream(state)
    out = "".join([d async for d in stream])

    assert used_rag is True
    assert retriever.queries == ["reset password"]
    assert "reset.acteek.local" in out


# --------------------------------------------------------------------------- #
# DialogueManager integration (grounded_qa states use the agent)              #
# --------------------------------------------------------------------------- #
def _grounded_domain() -> DomainConfig:
    flow = {
        "states": [
            {"id": "support", "type": "grounded_qa", "prompt": "What can I help with?"},
            {"id": "close", "type": "close", "prompt": "Glad I could help. Bye!"},
        ],
    }
    return DomainConfig(
        name="helpdesk", language="en", disclosure="d", greeting="g",
        system_prompt="s", consent_reprompt="r", consent_decline="x", flow=flow,
    )


class _StubResponder:
    """Unused on the agent path; present because DialogueManager requires a responder."""

    async def answer(self, *a, **k): ...
    async def answer_streaming(self, *a, **k):
        if False:
            yield ""


class _StubClassifier:
    async def classify(self, question, utterance):  # must NOT be called on the agent path
        raise AssertionError("classifier should not run for a grounded_qa agent turn")


def _manager(agent) -> DialogueManager:
    return DialogueManager(
        classifier=_StubClassifier(),
        responder=_StubResponder(),
        agent=agent,
        domain=_grounded_domain(),
        state=ConversationState(call_id="c1", state_index=0),
        store=InMemoryStateStore(),
    )


@pytest.mark.asyncio
async def test_dialogue_agent_follow_up_does_not_retrieve() -> None:
    llm = ScriptedLLM([LLMResponse(text="Sure — go ahead and reconnect, then tell me.")])
    retriever = FakeRetriever([])
    mgr = _manager(_agent(llm, retriever))

    turn = await mgr.handle_turn("yes it connects")

    assert retriever.queries == []            # follow-up -> no RAG
    assert turn.ended is False
    assert "reconnect" in turn.text
    assert mgr.state.transcript[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_dialogue_agent_closing_advances_to_close_without_an_llm_call() -> None:
    llm = ScriptedLLM([])                     # must NOT be called — closing is deterministic
    mgr = _manager(_agent(llm, FakeRetriever([])))

    turn = await mgr.handle_turn("thank you, I solved my problem")

    assert turn.ended is True
    assert mgr.finished is True
    assert turn.text == "Glad I could help. Bye!"
    assert llm.calls == 0
