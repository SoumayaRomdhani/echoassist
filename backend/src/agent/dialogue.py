"""Interview dialogue state machine (domain-config-driven).

Reads the ordered ``states`` from the domain YAML and drives a structured
screening interview. Each caller turn is classified (answer / question / done /
unclear); the manager then decides ask-next vs answer-via-RAG and fills slots
(ROADMAP §Sprint 3). It works on text only — STT/TTS live in the orchestrator —
so it is fully unit-testable without models.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from src.agent.domain import DomainConfig
from src.agent.grounding import GroundedResponder, strip_citations
from src.agent.guardrails import redact_pii
from src.agent.jsonutil import extract_json
from src.agent.state import ConversationState, StateStore
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role

log = logging.getLogger("echoassist.agent.dialogue")


# --------------------------------------------------------------------------- #
# Flow definition                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class State:
    id: str
    type: str            # "question" | "grounded_qa" | "close"
    prompt: str
    slot: str | None = None


def load_states(domain: DomainConfig) -> list[State]:
    return [
        State(
            id=raw["id"], type=raw["type"], prompt=str(raw["prompt"]).strip(), slot=raw.get("slot")
        )
        for raw in domain.flow.get("states", [])
    ]


def static_lines(domain: DomainConfig) -> list[str]:
    """Every deterministic line the agent can speak — for TTS pre-synthesis (L5).

    Mirrors verbatim what the orchestrator and this manager say, so the warmed
    strings hit the cache exactly: the consent-phase lines (greeting, re-prompt,
    decline) plus, for the interview, each state ``prompt``, the bare transition
    ``ack`` and the ``Sorry —`` re-ask. The disclosure is excluded: it is spoken
    once, synchronously, before any background warm could help. Grounded answers
    are dynamic and excluded.

    The ack is warmed **on its own** ("Thanks."), not joined to the next question:
    the streaming path (``synthesize_streaming``) splits "Thanks. <question>" on the
    sentence boundary and synthesizes each half separately, so the bare ack + the
    bare prompt are the strings actually requested. Warming the joined form would
    never be hit on the live path (and would burn an extra TTS call per question).

    Returns lines de-duplicated, in roughly the order they are first spoken, so a
    warm covers the soonest-needed lines first.
    """
    lines: list[str] = [
        line.strip()
        for line in (domain.greeting, domain.consent_reprompt, domain.consent_decline)
        if line and line.strip()
    ]
    ack = str(domain.flow.get("transition_ack") or "").strip()
    if ack:
        lines.append(ack)                                # spoken alone before an advanced question
    for state in load_states(domain):
        if not state.prompt:
            continue
        lines.append(state.prompt)                       # start / skip / re-ask / done-advance
        if state.type == "question":
            lines.append(f"Sorry — {state.prompt}")      # re-ask after an unclear answer

    seen: set[str] = set()
    return [line for line in lines if not (line in seen or seen.add(line))]


# --------------------------------------------------------------------------- #
# Turn classification                                                         #
# --------------------------------------------------------------------------- #
class TurnIntent(StrEnum):
    ANSWER = "answer"
    QUESTION = "question"
    DONE = "done"
    UNCLEAR = "unclear"


@dataclass(frozen=True, slots=True)
class TurnDecision:
    intent: TurnIntent
    answer_value: str = ""
    caller_question: str = ""


class TurnClassifier(Protocol):
    async def classify(self, question: str, utterance: str) -> TurnDecision: ...


_CLASSIFY_SYSTEM = (
    'You label one caller utterance during a phone job-screening interview. The '
    'interviewer just asked: "{question}". Reply with ONLY a JSON object, nothing else:\n'
    '{{"intent": "answer|question|done|unclear", "answer_value": "", "caller_question": ""}}\n'
    "- answer: the caller answered the interviewer's question; put a short normalized "
    "value in answer_value.\n"
    "- question: the caller asked their own question instead; put it in caller_question.\n"
    "- done: the caller signaled they have no more questions or nothing to add.\n"
    "- unclear: you cannot tell."
)


class LLMTurnClassifier:
    """Classifies a turn via a single JSON-returning LLM call (provider-agnostic)."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def classify(self, question: str, utterance: str) -> TurnDecision:
        messages = [
            Message(Role.SYSTEM, _CLASSIFY_SYSTEM.format(question=question)),
            Message(Role.USER, utterance),
        ]
        data = extract_json((await self._llm.chat(messages)).text) or {}
        try:
            intent = TurnIntent(str(data.get("intent", "unclear")).lower())
        except ValueError:
            intent = TurnIntent.UNCLEAR
        return TurnDecision(
            intent=intent,
            answer_value=str(data.get("answer_value") or "").strip(),
            caller_question=str(data.get("caller_question") or "").strip(),
        )


# --------------------------------------------------------------------------- #
# Dialogue manager                                                            #
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class DialogueTurn:
    text: str
    ended: bool
    citations: list[str] = field(default_factory=list)
    intent: TurnIntent | None = None


@dataclass(frozen=True, slots=True)
class _Grounded:
    """A reply part to be answered from the knowledge base."""

    question: str


@dataclass(slots=True)
class _Reply:
    """A planned reply: literal text and/or grounded questions, plus the end flag."""

    parts: list  # list[str | _Grounded]
    ended: bool
    intent: TurnIntent | None = None


class DialogueManager:
    def __init__(
        self,
        *,
        classifier: TurnClassifier,
        responder: GroundedResponder,
        domain: DomainConfig,
        state: ConversationState,
        store: StateStore,
        max_question_retries: int = 2,
        redact: bool = True,
    ) -> None:
        self._classifier = classifier
        self._responder = responder
        self._states = load_states(domain)
        self._ack = str(domain.flow.get("transition_ack") or "").strip()
        self._state = state
        self._store = store
        self._max_question_retries = max_question_retries
        self._redact = redact

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def finished(self) -> bool:
        return self._current is None

    @property
    def _current(self) -> State | None:
        index = self._state.state_index
        return self._states[index] if 0 <= index < len(self._states) else None

    async def record_consent(self) -> None:
        """Mark consent granted in the call state and persist it."""
        self._state.consent_granted = True
        await self._store.save(self._state)

    async def start(self) -> str:
        """Return (and record) the interviewer's first line — the first question."""
        first = self._states[0]
        self._state.add_turn("assistant", first.prompt)
        await self._store.save(self._state)
        return first.prompt

    async def handle_turn(self, transcript: str) -> DialogueTurn:
        """Non-streaming turn: materialize the whole reply, then return it."""
        current = self._current
        if current is None:
            return DialogueTurn(text="", ended=True)
        transcript, decision = await self._begin_turn(current, transcript)
        plan = self._plan(current, transcript, decision)

        pieces: list[str] = []
        citations: list[str] = []
        for part in plan.parts:
            if isinstance(part, _Grounded):
                answer = await self._responder.answer(part.question)
                pieces.append(answer.text)
                citations.extend(answer.citations)
            else:
                pieces.append(part)
        text = " ".join(p for p in pieces if p).strip()

        self._state.add_turn("assistant", text)
        await self._store.save(self._state)
        return DialogueTurn(text=text, ended=plan.ended, citations=citations, intent=plan.intent)

    async def handle_turn_streaming(self, transcript: str) -> AsyncIterator[str]:
        """Streaming turn: yield reply text deltas (grounded answers via the LLM stream).

        Same decision/slot logic as :meth:`handle_turn`; the reply is streamed so
        audio can start at the first sentence. The recorded assistant turn is the
        spoken (citation-stripped) text. Check :attr:`finished` afterwards for end.
        """
        current = self._current
        if current is None:
            return
        transcript, decision = await self._begin_turn(current, transcript)
        plan = self._plan(current, transcript, decision)

        raw = ""
        for part in plan.parts:
            if isinstance(part, _Grounded):
                async for delta in self._responder.answer_streaming(part.question):
                    raw += delta
                    yield delta
            else:
                chunk = f"{part} "
                raw += chunk
                yield chunk

        self._state.add_turn("assistant", strip_citations(raw))
        await self._store.save(self._state)

    # --- shared turn logic -------------------------------------------------
    async def _begin_turn(self, current: State, transcript: str) -> tuple[str, TurnDecision]:
        # Mask PII at the input so it never reaches the persisted state (Redis) or slots.
        if self._redact:
            transcript = redact_pii(transcript)
        self._state.add_turn("user", transcript)
        decision = await self._classifier.classify(current.prompt, transcript)
        return transcript, decision

    def _plan(self, current: State, transcript: str, decision: TurnDecision) -> _Reply:
        """Decide the reply (and apply slot/state mutations); deliver it later."""
        if current.type == "question":
            return self._plan_question(current, transcript, decision)
        if current.type == "grounded_qa":
            return self._plan_grounded_qa(transcript, decision)
        return _Reply(parts=[current.prompt], ended=True)  # close

    def _plan_question(self, state: State, transcript: str, decision: TurnDecision) -> _Reply:
        if decision.intent is TurnIntent.QUESTION:
            question = decision.caller_question or transcript
            self._state.query_history.append(question)
            # Answer their question, then re-ask the current interview question.
            return _Reply([_Grounded(question), state.prompt], ended=False, intent=decision.intent)
        if decision.intent is TurnIntent.ANSWER:
            if state.slot:
                self._state.slots[state.slot] = decision.answer_value or transcript
            self._state.question_attempts.pop(state.id, None)
            return self._advance(prepend_ack=True)

        # done / unclear: re-ask, but skip after too many failed attempts.
        attempts = self._state.question_attempts.get(state.id, 0) + 1
        self._state.question_attempts[state.id] = attempts
        if attempts >= self._max_question_retries:
            if state.slot:
                self._state.slots[state.slot] = ""  # leave unanswered
            log.info("skipping question '%s' after %d unclear attempts", state.id, attempts)
            return self._advance(prepend_ack=False)
        return _Reply([f"Sorry — {state.prompt}"], ended=False, intent=decision.intent)

    def _plan_grounded_qa(self, transcript: str, decision: TurnDecision) -> _Reply:
        if decision.intent is TurnIntent.DONE:
            return self._advance(prepend_ack=False)
        question = decision.caller_question or transcript
        self._state.query_history.append(question)
        return _Reply([_Grounded(question)], ended=False, intent=decision.intent)

    def _advance(self, *, prepend_ack: bool) -> _Reply:
        self._state.state_index += 1
        nxt = self._current
        if nxt is None:
            return _Reply([], ended=True)
        text = f"{self._ack} {nxt.prompt}".strip() if prepend_ack and self._ack else nxt.prompt
        if nxt.type == "close":
            self._state.state_index = len(self._states)  # close is the last line
            return _Reply([text], ended=True)
        return _Reply([text], ended=False)
