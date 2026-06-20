"""Interview dialogue state machine (domain-config-driven).

Reads the ordered ``states`` from the domain YAML and drives a structured
screening interview. Each caller turn is classified (answer / question / done /
unclear); the manager then decides ask-next vs answer-via-RAG and fills slots
(ROADMAP §Sprint 3). It works on text only — STT/TTS live in the orchestrator —
so it is fully unit-testable without models.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from src.agent.domain import DomainConfig
from src.agent.grounding import GroundedResponder
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


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class LLMTurnClassifier:
    """Classifies a turn via a single JSON-returning LLM call (provider-agnostic)."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def classify(self, question: str, utterance: str) -> TurnDecision:
        messages = [
            Message(Role.SYSTEM, _CLASSIFY_SYSTEM.format(question=question)),
            Message(Role.USER, utterance),
        ]
        data = _extract_json((await self._llm.chat(messages)).text) or {}
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
    ) -> None:
        self._classifier = classifier
        self._responder = responder
        self._states = load_states(domain)
        self._ack = str(domain.flow.get("transition_ack") or "").strip()
        self._state = state
        self._store = store
        self._max_question_retries = max_question_retries

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
        current = self._current
        if current is None:
            return DialogueTurn(text="", ended=True)

        self._state.add_turn("user", transcript)
        decision = await self._classifier.classify(current.prompt, transcript)

        if current.type == "question":
            turn = await self._handle_question(current, transcript, decision)
        elif current.type == "grounded_qa":
            turn = await self._handle_grounded_qa(transcript, decision)
        else:  # close
            turn = DialogueTurn(text=current.prompt, ended=True)

        self._state.add_turn("assistant", turn.text)
        await self._store.save(self._state)
        return turn

    # --- per-state handlers ------------------------------------------------
    async def _handle_question(
        self, state: State, transcript: str, decision: TurnDecision
    ) -> DialogueTurn:
        if decision.intent is TurnIntent.QUESTION:
            answer = await self._answer_question(decision, transcript)
            # Answer their question, then re-ask the current interview question.
            return DialogueTurn(
                text=f"{answer.text} {state.prompt}",
                ended=False,
                citations=answer.citations,
                intent=decision.intent,
            )
        if decision.intent is TurnIntent.ANSWER:
            if state.slot:
                self._state.slots[state.slot] = decision.answer_value or transcript
            self._state.question_attempts.pop(state.id, None)
            return self._advance(prepend_ack=True)

        # done / unclear: re-ask, but skip the question after too many failed attempts
        # so a non-answering caller can't loop the interview forever.
        attempts = self._state.question_attempts.get(state.id, 0) + 1
        self._state.question_attempts[state.id] = attempts
        if attempts >= self._max_question_retries:
            if state.slot:
                self._state.slots[state.slot] = ""  # leave unanswered
            log.info("skipping question '%s' after %d unclear attempts", state.id, attempts)
            return self._advance(prepend_ack=False)
        return DialogueTurn(text=f"Sorry — {state.prompt}", ended=False, intent=decision.intent)

    async def _handle_grounded_qa(self, transcript: str, decision: TurnDecision) -> DialogueTurn:
        if decision.intent is TurnIntent.DONE:
            return self._advance(prepend_ack=False)
        answer = await self._answer_question(decision, transcript)
        # Stay in grounded Q&A so the caller can ask follow-ups.
        return DialogueTurn(
            text=answer.text, ended=False, citations=answer.citations, intent=decision.intent
        )

    # --- helpers -----------------------------------------------------------
    async def _answer_question(self, decision: TurnDecision, transcript: str):
        question = decision.caller_question or transcript
        self._state.query_history.append(question)
        return await self._responder.answer(question)

    def _advance(self, *, prepend_ack: bool) -> DialogueTurn:
        self._state.state_index += 1
        nxt = self._current
        if nxt is None:
            return DialogueTurn(text="", ended=True)
        text = f"{self._ack} {nxt.prompt}".strip() if prepend_ack and self._ack else nxt.prompt
        if nxt.type == "close":
            # The close line is the last thing said; mark the flow finished.
            self._state.state_index = len(self._states)
            return DialogueTurn(text=text, ended=True)
        return DialogueTurn(text=text, ended=False)
