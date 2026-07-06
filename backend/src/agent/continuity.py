"""Domain-agnostic conversation continuity.

The voice agent's biggest quality problem is treating every caller turn as an
isolated retrieval query: it forgets the active issue, re-asks answered questions,
over-refuses normal follow-ups ("yes", "I tried that", "only in video calls"), and
occasionally invents a next step that was never in the retrieved passages.

This module fixes that generically — screening, helpdesk, and any future domain get
smoother multi-turn behaviour with no engine-specific code. It keeps a small rolling
memory on :class:`~src.agent.state.ConversationState` (active topic, the agent's last
question, steps already suggested, steps the caller reported failed, recent sources)
and uses it to:

- recognise terse follow-up fragments so they are never searched on their own;
- fold the active topic + the agent's last question + already-failed steps into the
  retrieval query, so retrieval keeps pulling the *same* procedure and the model can
  continue to the *next* documented step (not a hallucinated one);
- surface all of this to the grounded responder as plain context lines.

RAG stays the single source of factual truth: this module only assembles context and
conversational anchors — it never supplies facts, steps, or policies itself. Domains may
tune it purely through optional YAML (`retrieval_hints`, `continuity_prompt`,
`escalation_wording`); the mechanism lives here.
"""

from __future__ import annotations

import re

from src.agent.domain import DomainConfig
from src.agent.state import ConversationState

# Terse follow-up turns that only make sense against the active topic. Anchored at the
# start of the utterance (or as a short whole reply) so a real new question — e.g.
# "no internet at all, what should I check?" — is not mistaken for a bare "no".
_FOLLOWUP_RE = re.compile(
    r"^\s*(?:"
    r"yes|yeah|yep|yup|ok(?:ay)?|sure|correct|right|no|nope|nah|not really"
    r"|i (?:tried|did|already tried|already did) that|tried that|did that|already (?:tried|did)"
    r"|it (?:didn'?t|does\s?n'?t|still doesn'?t|still does\s?n'?t) work"
    r"|didn'?t work|does\s?n'?t work|not working|didn'?t help|no luck|no change"
    r"|still (?:not working|broken|the same|nothing|doesn'?t|does\s?n'?t)"
    r"|same (?:problem|issue|thing)|same as before"
    r"|tell me more|more please|go on|continue|next|and then|then what|what else|what now"
    r"|only (?:in|when|during|sometimes|if)|sometimes|not always|all the time|every time"
    r"|that worked|it works now|it'?s working|fixed|resolved|all good|solved"
    r")\b",
    re.I,
)

# A follow-up that reports the previously-suggested step did not resolve the issue.
_FAILURE_RE = re.compile(
    r"\b(?:"
    r"tried that|did that|already (?:tried|did)"
    r"|didn'?t work|does\s?n'?t work|not working|didn'?t help|no luck|no change"
    r"|still (?:not working|broken|the same|nothing|doesn'?t|does\s?n'?t)"
    r"|same (?:problem|issue|thing)|no difference"
    r")\b",
    re.I,
)

# The caller confirming the issue is resolved (so we stop suggesting more steps).
_RESOLVED_RE = re.compile(
    r"\b(?:that worked|it works now|it'?s working|it is working|fixed now|fixed it"
    r"|resolved|all good|solved|no longer|working now)\b",
    re.I,
)

_MAX_STEPS = 6      # cap rolling lists so state stays small and Redis-cheap
_MAX_SOURCES = 6


def is_followup_fragment(text: str) -> bool:
    """True for terse replies ("yes", "I tried that", "only in video calls") that must be
    interpreted against the active topic rather than retrieved as a standalone query."""
    return bool(_FOLLOWUP_RE.match(text or ""))


def indicates_failure(text: str) -> bool:
    """True when the caller reports the previously-suggested step did not work."""
    return bool(_FAILURE_RE.search(text or ""))


def indicates_resolution(text: str) -> bool:
    """True when the caller confirms the issue is now resolved."""
    return bool(_RESOLVED_RE.search(text or ""))


def _load_hints(raw: object) -> list[tuple[str, str]]:
    """Optional domain-configured query expansions ({trigger: expansion} in the YAML)."""
    if not isinstance(raw, dict):
        return []
    hints: list[tuple[str, str]] = []
    for key, value in raw.items():
        trigger = str(key).strip().lower()
        hint = str(value).strip()
        if trigger and hint:
            hints.append((trigger, hint))
    return hints


def _append_capped(items: list[str], value: str, cap: int) -> None:
    value = value.strip()
    if not value or value in items:
        return
    items.append(value)
    if len(items) > cap:
        del items[: len(items) - cap]


class ContinuityTracker:
    """Maintains the rolling continuity memory and builds context-anchored queries.

    Stateless with respect to a call: every method operates on the passed-in
    :class:`ConversationState`, so it is trivially unit-testable and shares the same
    persistence path as the rest of the state. All domain tuning comes from optional
    YAML fields, so the behaviour is generic across current and future domains.
    """

    def __init__(
        self,
        *,
        hints: list[tuple[str, str]] | None = None,
        continuity_prompt: str = "",
        escalation_wording: str = "",
    ) -> None:
        self._hints = hints or []
        self._continuity_prompt = continuity_prompt.strip()
        self._escalation_wording = escalation_wording.strip()

    @classmethod
    def from_domain(cls, domain: DomainConfig) -> ContinuityTracker:
        flow = domain.flow
        return cls(
            hints=_load_hints(flow.get("retrieval_hints")),
            continuity_prompt=str(flow.get("continuity_prompt") or "").strip(),
            escalation_wording=str(flow.get("escalation_wording") or "").strip(),
        )

    # --- updates -----------------------------------------------------------
    def note_user_turn(self, state: ConversationState, transcript: str, decision) -> None:
        """Fold the caller's turn into the continuity memory (call before building a query).

        ``decision`` is a ``TurnDecision`` (imported lazily by the caller to avoid a cycle);
        we only read ``intent``, ``caller_question`` and ``answer_value`` off it.
        """
        followup = is_followup_fragment(transcript)
        # A genuinely new issue/question (not a terse follow-up) becomes the active topic.
        new_issue = (decision.caller_question or "").strip()
        if new_issue and not followup:
            state.active_topic = new_issue
        elif not state.active_topic and not followup:
            state.active_topic = transcript.strip()

        # "I tried that / it didn't work" retires the last suggested step to failed_steps,
        # so the query tells retrieval+model to move on to the NEXT documented step.
        if indicates_failure(transcript) and state.suggested_steps:
            _append_capped(state.failed_steps, state.suggested_steps[-1], _MAX_STEPS)

    def record_assistant(
        self, state: ConversationState, spoken_text: str, citations: list[str]
    ) -> None:
        """Remember what the agent just said: its question, any suggested step, and sources."""
        text = (spoken_text or "").strip()
        if not text:
            return
        if text.rstrip().endswith("?"):
            state.last_assistant_question = text
        # A grounded, non-question reply is a concrete suggested step the caller may later
        # report as failed. Only capture grounded replies (with citations) so conversational
        # glue (acks, clarifying questions) is not mistaken for a documented step.
        elif citations:
            _append_capped(state.suggested_steps, text, _MAX_STEPS)
        for source in citations:
            _append_capped(state.recent_sources, source, _MAX_SOURCES)

    # --- query building ----------------------------------------------------
    # NOTE: retrieval and reading are deliberately split. A cross-encoder reranker and a dense
    # embedder match best on short, focused text, so the *search* query is clean keywords
    # (topic + current turn + hints). The verbose continuity guidance goes only into the
    # *context* the model reads alongside the retrieved passages — never into the embedded
    # query, where instructions like "ask a clarifying question" would both dilute the vector
    # and tempt the model to skip retrieval entirely.
    def build_search_query(self, state: ConversationState, transcript: str, decision) -> str:
        """Clean, keyword-focused query for retrieval — anchored on the active topic so a
        terse follow-up ("only on wifi", "it didn't work") still pulls the same procedure."""
        current = (decision.caller_question or decision.answer_value or transcript).strip()
        followup = is_followup_fragment(transcript)

        ordered: list[str] = []
        # For a terse follow-up, lead with the remembered topic so keywords aren't just "yes".
        if state.active_topic and (followup or state.active_topic.lower() not in current.lower()):
            ordered.append(state.active_topic)
        ordered.append(current or transcript)
        ordered.extend(self._matched_hints(" ".join([state.active_topic, transcript, current])))

        seen: set[str] = set()
        clean: list[str] = []
        for piece in ordered:
            piece = piece.strip()
            key = piece.lower()
            if piece and key not in seen:
                seen.add(key)
                clean.append(piece)
        return ". ".join(clean)

    def build_context(self, state: ConversationState, transcript: str, decision) -> str:
        """Rich, human-readable context the model reads with the retrieved passages: recent
        caller turns, the agent's last question, the active topic, already-failed steps, and
        explicit anti-hallucination / escalation guidance — so it advances to the next real
        step and never re-asks or invents one."""
        from src.agent.dialogue import TurnIntent  # local import: avoid module cycle

        previous_turns = state.transcript[:-1]  # the current user turn was just appended
        recent_users = [
            str(t["text"]) for t in previous_turns if t.get("role") == "user" and t.get("text")
        ][-2:]
        last_assistant = state.last_assistant_question or next(
            (t["text"] for t in reversed(previous_turns) if t.get("role") == "assistant"), ""
        )
        current = (decision.caller_question or decision.answer_value or transcript).strip()
        searchable = " ".join([*recent_users, str(last_assistant), transcript, current])

        parts: list[str] = []
        if recent_users:
            parts.append(f"Recent caller context: {' | '.join(recent_users)}")
        if last_assistant:
            parts.append(f"Agent's last question: {last_assistant}")
        if state.active_topic and state.active_topic not in (current, transcript):
            parts.append(f"Active issue or topic: {state.active_topic}")
        if decision.intent is TurnIntent.ANSWER:
            parts.append(f"Caller replied: {current}")
        else:
            parts.append(f"Current caller turn: {transcript}")
        if current and current != transcript:
            parts.append(f"Normalized issue or question: {current}")
        if state.failed_steps:
            parts.append(
                "Steps already tried without success: " + "; ".join(state.failed_steps)
            )
        hints = self._matched_hints(searchable)
        if hints:
            parts.append(f"Relevant KB search hints: {' | '.join(hints)}")
        if self._continuity_prompt:
            parts.append(self._continuity_prompt)
        guidance = (
            "Stay on the caller's active issue. Give exactly one next step or one clarifying "
            "question, using only the retrieved passages. If a step was already tried, continue "
            "with the NEXT step from the passages — never invent a step that is not in them. If "
            "the passages do not cover it, do not say so literally; offer to escalate or have a "
            "human follow up."
        )
        if self._escalation_wording:
            guidance += f" Escalation wording to use if needed: {self._escalation_wording}"
        parts.append(guidance)
        return "\n".join(parts)

    def _matched_hints(self, text: str) -> list[str]:
        text_lower = text.lower()
        seen: set[str] = set()
        matches: list[str] = []
        for trigger, hint in self._hints:
            if trigger in text_lower and hint not in seen:
                seen.add(hint)
                matches.append(hint)
        return matches
