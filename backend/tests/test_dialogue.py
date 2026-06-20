"""Interview dialogue state machine, validated with fakes (no models/Redis)."""

from __future__ import annotations

import pytest

from src.agent.dialogue import DialogueManager, LLMTurnClassifier, TurnDecision, TurnIntent
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
