"""Interview dialogue state machine (domain-config-driven).

Reads the ordered ``states`` from the domain YAML and drives a structured
screening interview. Each caller turn is classified (answer / question / done /
unclear); the manager then decides ask-next vs answer-via-RAG and fills slots
(ROADMAP §Sprint 3). It works on text only — STT/TTS live in the orchestrator —
so it is fully unit-testable without models.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from src.agent.continuity import ContinuityTracker, is_closing
from src.agent.conversation import ConversationAgent
from src.agent.domain import DomainConfig
from src.agent.grounding import Citation, GroundedResponder, strip_citations
from src.agent.guardrails import redact_pii, refusal_message
from src.agent.jsonutil import extract_json
from src.agent.state import ConversationState, StateStore
from src.observability import latency
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


def _load_acks(domain: DomainConfig) -> list[str]:
    """Transition acknowledgements from the domain YAML (``transition_ack:`` — string or list)."""
    raw = domain.flow.get("transition_ack")
    if isinstance(raw, list):
        return [str(ack).strip() for ack in raw if str(ack).strip()]
    text = str(raw).strip() if raw else ""
    return [text] if text else []


# --------------------------------------------------------------------------- #
# Turn classification                                                         #
# --------------------------------------------------------------------------- #
class TurnIntent(StrEnum):
    ANSWER = "answer"
    QUESTION = "question"          # a substantive domain question -> RAG
    META = "meta"                 # procedural / small-talk / clarification -> canned reply, no RAG
    DONE = "done"
    UNCLEAR = "unclear"


class MetaKind(StrEnum):
    """The shape of a meta utterance, so we can give it the right canned reply."""

    REPEAT = "repeat"             # "can you repeat?" -> re-read the current line
    PERMISSION = "permission"     # "can I ask a question?" -> "of course, go ahead"
    WAIT = "wait"                 # "hold on / one sec" -> "take your time"


# Conservative keyword fast-path: unambiguous procedural/small-talk phrases that must NOT
# trigger retrieval. Kept phrase-anchored (not bare words like "wait"/"what") so a real
# answer or question is never mislabelled — the classifier's "meta" intent catches the rest.
_META_RULES: tuple[tuple[MetaKind, re.Pattern[str]], ...] = (
    (MetaKind.REPEAT, re.compile(
        r"\b(can|could) you repeat\b|\brepeat (that|the question)\b|\bsay that again\b"
        r"|\bcome again\b|\bdidn'?t (catch|hear|get) that\b|\bpardon( me)?\b", re.I)),
    (MetaKind.PERMISSION, re.compile(
        r"\b(can|could|may) i ask\b[^?]{0,25}\bquestion\b|\bquick question\b"
        r"|\bask you (a|one|something)\b", re.I)),
    (MetaKind.WAIT, re.compile(
        r"\bhold on\b|\bhang on\b|\bone (sec|second|moment)\b"
        r"|\b(give me|just) a (sec|second|moment)\b", re.I)),
)


def detect_meta(utterance: str) -> MetaKind | None:
    """Match a clear procedural/small-talk phrase (repeat / permission / hold on), else None.

    A free, deterministic fast-path so common meta utterances skip the classifier LLM *and*
    retrieval entirely — "can I ask a question?" should be an instant "go ahead", not a
    knowledge-base search that costs an embed + rerank + LLM read.
    """
    for kind, pattern in _META_RULES:
        if pattern.search(utterance):
            return kind
    return None


async def _empty_stream() -> AsyncIterator[str]:
    """An async iterator that yields nothing (for a turn with no current state)."""
    for _ in ():
        yield _


# Bracketed source markers (e.g. "[laptop_slow.md]") left in raw streamed text before
# citation stripping — used to tell a grounded step apart from conversational glue.
_SOURCE_MARKER = re.compile(r"\[([^\[\]]+?\.[a-z0-9]+)\]", re.I)


def _sources_in(text: str) -> list[str]:
    return _SOURCE_MARKER.findall(text)


@dataclass(frozen=True, slots=True)
class TurnDecision:
    intent: TurnIntent
    answer_value: str = ""
    caller_question: str = ""
    meta: MetaKind | None = None   # set for TurnIntent.META (keyword fast-path); None from the LLM


class TurnClassifier(Protocol):
    async def classify(self, question: str, utterance: str) -> TurnDecision: ...


_CLASSIFY_SYSTEM = (
    'You label one caller utterance during a voice-agent conversation. The '
    'agent just asked: "{question}". Reply with ONLY a JSON object, nothing else:\n'
    '{{"intent": "answer|question|meta|done|unclear", "answer_value": "", "caller_question": ""}}\n'
    "- answer: the caller answered the agent's current question; put a short normalized "
    "value in answer_value.\n"
    "- question: the caller asked a substantive domain question or reported a new issue "
    "that needs the knowledge base; put it in caller_question.\n"
    "- meta: a procedural or small-talk remark that is NOT a knowledge question — e.g. asking "
    "permission to ask, asking you to repeat, or saying to hold on.\n"
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
    details: list[Citation] = field(default_factory=list)  # per-source page/heading provenance


@dataclass(frozen=True, slots=True)
class _Grounded:
    """A reply part to be answered from the knowledge base.

    ``question`` is the rich context the model reads; ``search_query`` is the clean query used
    for retrieval. When ``search_query`` is set the responder retrieves-then-reads (always
    grounds on that query); when empty it falls back to letting the model choose its own
    search (screening's one-shot question detours).
    """

    question: str
    search_query: str = ""


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
        agent: ConversationAgent | None = None,
        max_question_retries: int = 2,
        redact: bool = True,
    ) -> None:
        self._classifier = classifier
        self._responder = responder
        # Caller-led (grounded_qa) states are handled by the conversational agent when provided:
        # the model holds the full conversation and decides when to search (agent/conversation.py).
        # When it is None the legacy classify -> retrieve-then-read path runs (keeps old tests).
        self._agent = agent
        self._fallback = (domain.flow.get("fallback_prompt") or "").strip() or refusal_message()
        self._states = load_states(domain)
        # Domain-agnostic multi-turn continuity (active topic, last question, tried/failed
        # steps, sources) + context-anchored query building. See agent/continuity.py.
        self._continuity = ContinuityTracker.from_domain(domain)
        # Transition acknowledgements, spoken before the next question so the flow isn't
        # abrupt. A pool (domain YAML `transition_ack:` may be a string or a list) rotated for
        # variety, so the agent doesn't repeat the same word every turn.
        self._acks = _load_acks(domain)
        self._ack_i = 0
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
        if self._agent is not None and current.type == "grounded_qa":
            return await self._agent_turn(transcript)
        transcript, decision = await self._begin_turn(current, transcript)
        with latency.span("router_ms"):
            plan = self._plan(current, transcript, decision)
        latency.observe(
            intent=decision.intent.value,
            is_rag=any(isinstance(p, _Grounded) for p in plan.parts),
        )

        pieces: list[str] = []
        citations: list[str] = []
        details: list[Citation] = []
        for part in plan.parts:
            if isinstance(part, _Grounded):
                answer = await self._responder.answer(
                    part.question, search_query=part.search_query or None
                )
                pieces.append(answer.text)
                citations.extend(answer.citations)
                details.extend(answer.details)
            else:
                pieces.append(part)
        text = " ".join(p for p in pieces if p).strip()

        self._continuity.record_assistant(self._state, text, citations)
        self._state.add_turn("assistant", text)
        await self._store.save(self._state)
        return DialogueTurn(
            text=text, ended=plan.ended, citations=citations, intent=plan.intent, details=details
        )

    async def begin_streaming_turn(self, transcript: str) -> tuple[bool, AsyncIterator[str]]:
        """Classify + plan the turn eagerly, then return ``(is_rag, reply-text stream)``.

        Exposing ``is_rag`` *before* the (slow) retrieval lets the live caller decide whether
        to cover the wait with a filler — it never changes what the caller ultimately hears.
        Same decision/slot logic as :meth:`handle_turn`; consume the stream, then check
        :attr:`finished`. The recorded assistant turn is the spoken (citation-stripped) text.
        """
        current = self._current
        if current is None:
            return False, _empty_stream()
        if self._agent is not None and current.type == "grounded_qa":
            return await self._agent_stream(transcript)
        transcript, decision = await self._begin_turn(current, transcript)
        with latency.span("router_ms"):
            plan = self._plan(current, transcript, decision)
        is_rag = any(isinstance(part, _Grounded) for part in plan.parts)
        latency.observe(intent=decision.intent.value, is_rag=is_rag)
        return is_rag, self._stream_plan(plan)

    # --- conversational agent path (caller-led grounded_qa states) ---------
    def _record_user(self, transcript: str) -> str:
        if self._redact:
            transcript = redact_pii(transcript)
        self._state.add_turn("user", transcript)
        return transcript

    def _advance_to_close(self) -> str:
        """Jump to the flow's close line and mark the interview finished."""
        close = next((s for s in self._states if s.type == "close"), None)
        self._state.state_index = len(self._states)  # finished
        return close.prompt if close else ""

    async def _agent_turn(self, transcript: str) -> DialogueTurn:
        transcript = self._record_user(transcript)
        if is_closing(transcript):
            text = self._advance_to_close()
            self._state.add_turn("assistant", text)
            await self._store.save(self._state)
            return DialogueTurn(text=text, ended=True)

        self._continuity.remember_user_turn(self._state, transcript)
        note = self._continuity.state_note(self._state)
        reply = await self._agent.respond(self._state, state_note=note)
        text = reply.text or self._fallback
        self._continuity.record_assistant(self._state, text, reply.citations)
        self._state.add_turn("assistant", text)
        await self._store.save(self._state)
        latency.observe(is_rag=reply.used_rag)
        return DialogueTurn(
            text=text, ended=False, citations=reply.citations, details=reply.details
        )

    async def _agent_stream(self, transcript: str) -> tuple[bool, AsyncIterator[str]]:
        transcript = self._record_user(transcript)
        if is_closing(transcript):
            text = self._advance_to_close()
            return False, self._closing_stream(text)

        self._continuity.remember_user_turn(self._state, transcript)
        note = self._continuity.state_note(self._state)
        used_rag, raw_stream = await self._agent.begin_stream(self._state, state_note=note)
        latency.observe(is_rag=used_rag)
        return used_rag, self._wrap_agent_stream(raw_stream)

    async def _closing_stream(self, text: str) -> AsyncIterator[str]:
        self._state.add_turn("assistant", text)
        await self._store.save(self._state)
        if text:
            yield text

    async def _wrap_agent_stream(self, raw_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        raw = ""
        async for delta in raw_stream:
            raw += delta
            yield delta
        spoken = strip_citations(raw)
        self._continuity.record_assistant(self._state, spoken, _sources_in(raw))
        self._state.add_turn("assistant", spoken)
        await self._store.save(self._state)

    async def _stream_plan(self, plan: _Reply) -> AsyncIterator[str]:
        raw = ""
        for part in plan.parts:
            if isinstance(part, _Grounded):
                stream = self._responder.answer_streaming(
                    part.question, search_query=part.search_query or None
                )
                async for delta in stream:
                    raw += delta
                    yield delta
            else:
                chunk = f"{part} "
                raw += chunk
                yield chunk
        spoken = strip_citations(raw)
        self._continuity.record_assistant(self._state, spoken, _sources_in(raw))
        self._state.add_turn("assistant", spoken)
        await self._store.save(self._state)

    async def handle_turn_streaming(self, transcript: str) -> AsyncIterator[str]:
        """Streaming turn (no filler): classify+plan, then stream the reply deltas."""
        _is_rag, stream = await self.begin_streaming_turn(transcript)
        async for delta in stream:
            yield delta

    # --- shared turn logic -------------------------------------------------
    async def _begin_turn(self, current: State, transcript: str) -> tuple[str, TurnDecision]:
        # Mask PII at the input so it never reaches the persisted state (Redis) or slots.
        if self._redact:
            transcript = redact_pii(transcript)
        self._state.add_turn("user", transcript)
        kind = detect_meta(transcript)
        if kind is not None:
            # Clear meta phrase — skip the classifier LLM and retrieval entirely.
            return transcript, TurnDecision(intent=TurnIntent.META, meta=kind)
        with latency.span("classifier_ms"):
            decision = await self._classifier.classify(current.prompt, transcript)
        return transcript, decision

    def _plan(self, current: State, transcript: str, decision: TurnDecision) -> _Reply:
        """Decide the reply (and apply slot/state mutations); deliver it later."""
        if decision.intent is TurnIntent.META:
            # In a caller-led (grounded_qa) flow with an active issue, only the cheap KEYWORD meta
            # (repeat / permission / hold-on, which set decision.meta) gets a canned reply.
            # Everything else the classifier calls "meta" — "yes", "exactly", "then what?", "help
            # me", "say it simply" — is grounded WITH context, so the model acts on it / advances
            # instead of re-dumping its last line ("Of course. Of course. ...").
            keyword_meta = decision.meta is not None
            if current.type == "grounded_qa" and self._state.active_topic and not keyword_meta:
                decision = TurnDecision(
                    intent=TurnIntent.ANSWER,
                    answer_value=decision.answer_value,
                    caller_question=decision.caller_question,
                )
            else:
                return self._plan_meta(current, decision)  # canned reply, no retrieval, stay put
        if current.type == "question":
            return self._plan_question(current, transcript, decision)
        if current.type == "grounded_qa":
            return self._plan_grounded_qa(transcript, decision)
        return _Reply(parts=[current.prompt], ended=True)  # close

    def _last_assistant_line(self) -> str:
        """The last thing the agent actually said (not the static state prompt), so a 'repeat'
        or generic meta re-anchor doesn't jump back to the opening line mid-conversation."""
        return next(
            (t["text"] for t in reversed(self._state.transcript)
             if t.get("role") == "assistant" and t.get("text")),
            "",
        )

    def _plan_meta(self, current: State, decision: TurnDecision) -> _Reply:
        """A procedural/small-talk turn: reply cheaply and stay put (no RAG). Re-anchors to the
        agent's *last line*, not the state prompt, so it never resets to the opening greeting."""
        anchor = self._last_assistant_line() or current.prompt
        if decision.meta is MetaKind.REPEAT:
            text = f"Sure — {anchor}"
        elif decision.meta is MetaKind.WAIT:
            text = "Take your time."
        elif decision.meta is MetaKind.PERMISSION:
            text = "Of course, go ahead."
        else:  # classifier-detected meta without a specific kind: acknowledge + re-anchor
            # Strip a leading "Of course"/"Sure" from the anchor so we never stack "Of course.
            # Of course. ..." when re-anchoring on a line that already opened that way.
            clean_anchor = re.sub(r"^(?:of course|sure|okay|ok)[.,!]?\s*", "", anchor, flags=re.I)
            text = f"Of course. {clean_anchor}".strip()
        return _Reply([text], ended=False, intent=TurnIntent.META)

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
        # Fold this turn into the continuity memory, then retrieve with a CLEAN query while the
        # model reads the RICH context — so a terse follow-up ("yes", "I tried that", "only in
        # video calls") keeps the same issue and the agent never skips retrieval.
        self._continuity.note_user_turn(self._state, transcript, decision)
        context = self._continuity.build_context(self._state, transcript, decision)
        search_query = self._continuity.build_search_query(self._state, transcript, decision)
        self._state.query_history.append(search_query)
        return _Reply(
            [_Grounded(context, search_query=search_query)], ended=False, intent=decision.intent
        )

    def _next_ack(self) -> str:
        """The next transition acknowledgement, cycling the pool so it isn't always the same."""
        if not self._acks:
            return ""
        ack = self._acks[self._ack_i % len(self._acks)]
        self._ack_i += 1
        return ack

    def _advance(self, *, prepend_ack: bool) -> _Reply:
        self._state.state_index += 1
        nxt = self._current
        if nxt is None:
            return _Reply([], ended=True)
        ack = self._next_ack() if prepend_ack else ""
        text = f"{ack} {nxt.prompt}".strip() if ack else nxt.prompt
        if nxt.type == "close":
            self._state.state_index = len(self._states)  # close is the last line
            return _Reply([text], ended=True)
        return _Reply([text], ended=False)
