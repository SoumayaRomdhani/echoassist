"""Interview dialogue state machine, validated with fakes (no models/Redis)."""

from __future__ import annotations

import pytest

from src.agent.dialogue import (
    DialogueManager,
    LLMTurnClassifier,
    MetaKind,
    TurnDecision,
    TurnIntent,
    detect_meta,
)
from src.agent.domain import DomainConfig
from src.agent.grounding import GroundedAnswer
from src.agent.state import ConversationState, InMemoryStateStore
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse


def _domain() -> DomainConfig:
    flow = {
        "transition_ack": "Thanks.",
        "states": [
            {"id": "experience", "type": "question", "slot": "years_experience",
             "prompt": "How many years of experience do you have?"},
            {"id": "stack", "type": "question", "slot": "primary_stack",
             "prompt": "What is your main tech stack?"},
            {"id": "qa", "type": "grounded_qa", "prompt": "Any questions for me?"},
            {"id": "close", "type": "close", "prompt": "Thanks, goodbye."},
        ],
    }
    return DomainConfig(
        name="screening", language="en", disclosure="d", greeting="g",
        system_prompt="s", consent_reprompt="r", consent_decline="x", flow=flow,
    )


class FakeClassifier:
    def __init__(self, decisions: list[TurnDecision]) -> None:
        self._decisions = decisions
        self.seen: list[tuple[str, str]] = []

    async def classify(self, question: str, utterance: str) -> TurnDecision:
        self.seen.append((question, utterance))
        return self._decisions.pop(0)


class FakeResponder:
    def __init__(self, answer: GroundedAnswer) -> None:
        self._answer = answer
        self.questions: list[str] = []

    async def answer(self, question: str) -> GroundedAnswer:
        self.questions.append(question)
        return self._answer

    async def answer_streaming(self, question: str):
        self.questions.append(question)
        yield self._answer.text


def _manager(decisions, responder, *, state=None):
    state = state or ConversationState(call_id="c1")
    return DialogueManager(
        classifier=FakeClassifier(decisions),
        responder=responder,
        domain=_domain(),
        state=state,
        store=InMemoryStateStore(),
    )


def _responder(text="ok", citations=None) -> FakeResponder:
    return FakeResponder(GroundedAnswer(text=text, citations=citations or []))


@pytest.mark.asyncio
async def test_start_returns_first_question() -> None:
    mgr = _manager([], _responder())
    assert await mgr.start() == "How many years of experience do you have?"
    assert mgr.state.transcript[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_answer_fills_slot_and_advances_with_ack() -> None:
    mgr = _manager([TurnDecision(TurnIntent.ANSWER, answer_value="6 years")], _responder())
    await mgr.start()
    turn = await mgr.handle_turn("I have six years")

    assert mgr.state.slots["years_experience"] == "6 years"
    assert turn.text == "Thanks. What is your main tech stack?"
    assert turn.ended is False


@pytest.mark.asyncio
async def test_caller_question_is_answered_then_question_reasked() -> None:
    responder = _responder("It is fully remote [remote_work_policy.md].", ["remote_work_policy.md"])
    mgr = _manager([TurnDecision(TurnIntent.QUESTION, caller_question="is it remote?")], responder)
    await mgr.start()
    turn = await mgr.handle_turn("wait, is it remote?")

    assert "It is fully remote" in turn.text
    assert "How many years of experience" in turn.text   # re-asked, not advanced
    assert turn.citations == ["remote_work_policy.md"]
    assert mgr.state.slots == {}
    assert responder.questions == ["is it remote?"]
    assert mgr.state.query_history == ["is it remote?"]


@pytest.mark.asyncio
async def test_grounded_qa_done_advances_to_close_and_ends() -> None:
    state = ConversationState(call_id="c1", state_index=2)  # start in grounded_qa
    mgr = _manager([TurnDecision(TurnIntent.DONE)], _responder(), state=state)
    turn = await mgr.handle_turn("no, that's all")

    assert turn.text == "Thanks, goodbye."
    assert turn.ended is True
    assert mgr.finished is True


@pytest.mark.asyncio
async def test_full_flow_runs_to_close() -> None:
    decisions = [
        TurnDecision(TurnIntent.ANSWER, answer_value="6"),
        TurnDecision(TurnIntent.ANSWER, answer_value="Python/FastAPI"),
        TurnDecision(TurnIntent.DONE),
    ]
    mgr = _manager(decisions, _responder())
    await mgr.start()

    await mgr.handle_turn("six years")
    t2 = await mgr.handle_turn("python and fastapi")
    assert t2.text == "Thanks. Any questions for me?"
    t3 = await mgr.handle_turn("nope")

    assert t3.ended is True
    assert mgr.finished is True
    assert mgr.state.slots == {"years_experience": "6", "primary_stack": "Python/FastAPI"}


@pytest.mark.asyncio
async def test_transition_acks_rotate_so_it_is_not_always_thanks() -> None:
    flow = {
        "transition_ack": ["Thanks.", "Got it.", "Great."],
        "states": [
            {"id": "q1", "type": "question", "slot": "a", "prompt": "Q one?"},
            {"id": "q2", "type": "question", "slot": "b", "prompt": "Q two?"},
            {"id": "q3", "type": "question", "slot": "c", "prompt": "Q three?"},
            {"id": "close", "type": "close", "prompt": "Bye."},
        ],
    }
    domain = DomainConfig(
        name="x", language="en", disclosure="d", greeting="g", system_prompt="s",
        consent_reprompt="r", consent_decline="x", flow=flow,
    )
    mgr = DialogueManager(
        classifier=FakeClassifier([
            TurnDecision(TurnIntent.ANSWER, answer_value="1"),
            TurnDecision(TurnIntent.ANSWER, answer_value="2"),
        ]),
        responder=_responder(), domain=domain,
        state=ConversationState(call_id="c1"), store=InMemoryStateStore(),
    )
    await mgr.start()

    t1 = await mgr.handle_turn("one")
    t2 = await mgr.handle_turn("two")

    assert t1.text == "Thanks. Q two?"
    assert t2.text == "Got it. Q three?"   # rotated to the next ack, not "Thanks." again


@pytest.mark.asyncio
async def test_question_skipped_after_max_unclear_attempts() -> None:
    decisions = [TurnDecision(TurnIntent.UNCLEAR), TurnDecision(TurnIntent.UNCLEAR)]
    mgr = _manager(decisions, _responder())
    await mgr.start()

    first = await mgr.handle_turn("uh, what?")
    assert first.text.startswith("Sorry —")   # attempt 1: re-ask
    assert mgr.state.slots == {}

    second = await mgr.handle_turn("hmm")      # attempt 2 (max): skip + advance
    assert "main tech stack" in second.text
    assert second.ended is False
    assert mgr.state.slots["years_experience"] == ""  # left unanswered


def test_detect_meta_matches_phrases_but_not_real_answers_or_questions() -> None:
    assert detect_meta("Actually, can I ask a question?") is MetaKind.PERMISSION
    assert detect_meta("sorry, could you repeat the question") is MetaKind.REPEAT
    assert detect_meta("hold on, one sec") is MetaKind.WAIT
    # Real answers / questions must NOT be caught — they still need the classifier / RAG.
    assert detect_meta("I have six years of experience") is None
    assert detect_meta("wait, is it remote?") is None            # bare "wait" is not meta
    assert detect_meta("what is the salary range?") is None
    assert detect_meta("can I ask about the salary?") is None    # substantive -> classifier


@pytest.mark.asyncio
async def test_meta_permission_skips_classifier_and_retrieval() -> None:
    responder = _responder("company info [x.md]", ["x.md"])
    mgr = _manager([], responder)          # empty decisions: classify must NOT be called
    await mgr.start()

    turn = await mgr.handle_turn("Actually, can I ask a question?")

    assert turn.text == "Of course, go ahead."
    assert turn.ended is False
    assert responder.questions == []       # no retrieval
    assert mgr._classifier.seen == []      # classifier LLM skipped (deterministic fast-path)
    assert mgr.state.slots == {} and mgr.state.state_index == 0   # stayed on the question


@pytest.mark.asyncio
async def test_meta_repeat_rereads_the_current_question() -> None:
    mgr = _manager([], _responder())
    await mgr.start()

    turn = await mgr.handle_turn("sorry, can you repeat that?")

    assert turn.text == "Sure — How many years of experience do you have?"
    assert turn.ended is False
    assert mgr._classifier.seen == []


@pytest.mark.asyncio
async def test_llm_classified_meta_skips_retrieval() -> None:
    responder = _responder("info", ["x.md"])
    # No keyword match -> classifier is consulted and returns meta (no specific kind).
    mgr = _manager([TurnDecision(TurnIntent.META)], responder)
    await mgr.start()

    turn = await mgr.handle_turn("hmm, let me think about how to phrase this")

    assert turn.ended is False
    assert responder.questions == []                     # meta never retrieves
    assert "How many years" in turn.text                 # generic meta re-anchors to the question


@pytest.mark.asyncio
async def test_begin_streaming_turn_flags_rag_only_for_substantive_questions() -> None:
    # A caller QUESTION -> grounded -> is_rag True (worth a filler).
    mgr = _manager([TurnDecision(TurnIntent.QUESTION, caller_question="is it remote?")],
                   _responder("It is remote."))
    await mgr.start()
    is_rag, stream = await mgr.begin_streaming_turn("wait, is it remote?")
    _ = [d async for d in stream]
    assert is_rag is True

    # A slot ANSWER -> not RAG (no filler).
    mgr = _manager([TurnDecision(TurnIntent.ANSWER, answer_value="6")], _responder())
    await mgr.start()
    is_rag, stream = await mgr.begin_streaming_turn("six years")
    _ = [d async for d in stream]
    assert is_rag is False

    # A meta keyword phrase -> not RAG, classifier skipped.
    mgr = _manager([], _responder())
    await mgr.start()
    is_rag, stream = await mgr.begin_streaming_turn("can I ask a question?")
    _ = [d async for d in stream]
    assert is_rag is False
    assert mgr._classifier.seen == []


@pytest.mark.asyncio
async def test_record_consent_persists_to_store() -> None:
    state = ConversationState(call_id="c1")
    store = InMemoryStateStore()
    mgr = DialogueManager(
        classifier=FakeClassifier([]), responder=_responder(),
        domain=_domain(), state=state, store=store,
    )
    await mgr.record_consent()

    assert state.consent_granted is True
    loaded = await store.load("c1")
    assert loaded is not None and loaded.consent_granted is True


class _JsonLLM(LLMProvider):
    def __init__(self, text: str) -> None:
        self._text = text

    async def chat(self, messages, tools=None) -> LLMResponse:
        return LLMResponse(text=self._text)


@pytest.mark.asyncio
async def test_llm_classifier_parses_json_amid_prose() -> None:
    llm = _JsonLLM('Sure: {"intent": "answer", "answer_value": "5 years", "caller_question": ""}.')
    decision = await LLMTurnClassifier(llm).classify("How many years?", "about five")
    assert decision.intent is TurnIntent.ANSWER
    assert decision.answer_value == "5 years"


@pytest.mark.asyncio
async def test_llm_classifier_falls_back_to_unclear_on_bad_json() -> None:
    decision = await LLMTurnClassifier(_JsonLLM("no json here")).classify("q", "u")
    assert decision.intent is TurnIntent.UNCLEAR
