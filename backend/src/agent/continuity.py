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
    r"|only (?:in|on|when|during|sometimes|if|with|for)|sometimes|not always|all the time"
    r"|every time"
    r"|that worked|it works now|it'?s working|fixed|resolved|all good|solved"
    r")\b",
    re.I,
)

# A follow-up that asks to CONTINUE the current issue / get the next step ("then what?",
# "what now", "next", "it didn't work", "same problem"). Distinct from a resolution ("that
# worked") or "no more". Used so the engine keeps the thread instead of treating it as small
# talk and resetting to the opening line.
_CONTINUATION_RE = re.compile(
    r"\b(?:"
    r"then what|what next|what'?s next|whats next|and then|and after|after that|next step|next"
    r"|now what|so what do|go on|carry on|keep going|continue|tell me more|what else"
    r"|what (?:to do|do i do|should i do|do we do)|what do i do then|what to do then"
    r"|other (?:solution|option)s?|another (?:option|way|solution)|any other (?:option|way)"
    r"|tried that|did that|didn'?t work|does\s?n'?t work|not working|didn'?t help|no luck"
    r"|no change|still (?:not working|broken|the same|nothing|doesn'?t|does\s?n'?t)"
    r"|same (?:problem|issue|thing)"
    r")\b",
    re.I,
)

# A plain acceptance of the agent's previous offer ("yes", "go ahead", "please do") — used to
# stop the agent re-offering/looping once the caller has already said yes.
_AFFIRM_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please(?:\s+do(?:\s+that)?)?|go ahead|do that|do it"
    r"|sounds good|absolutely|of course|that works|let'?s do (?:it|that))\b",
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


def is_continuation(text: str) -> bool:
    """True when the caller wants the NEXT step of the current issue ("then what?", "next",
    "it didn't work") — a thread-continuing turn that must never be treated as small talk or
    reset the conversation to the opening line."""
    return bool(_CONTINUATION_RE.search(text or ""))


def is_affirmation(text: str) -> bool:
    """True for a plain 'yes / go ahead / please do' — used to detect the caller accepting the
    agent's previous offer, so the agent confirms and moves on instead of repeating it."""
    return bool(_AFFIRM_RE.match(text or ""))


# The caller did not understand, or wants the agent to do the step WITH them ("what?", "say
# it simply", "help me do that", "what prompts?", "which button?"). These must NOT trigger a
# fresh answer or a verbatim repeat — the agent re-explains its LAST point as one micro-step.
_REPAIR_RE = re.compile(
    r"(?:^|\b)(?:"
    r"huh|what\?|come again"
    r"|(?:i )?(?:didn'?t|don'?t|do not|can'?t) (?:understand|get it|get that|follow|know how)"
    r"|not sure (?:how|what)|what do you mean|what does that mean|make it simple"
    r"|say (?:that|it)?\s*(?:again\s*)?(?:more\s*)?(?:simply|simpler|slower)"
    r"|(?:in )?simpler?(?: terms| words)?|too (?:fast|complicated|technical)"
    r"|can you (?:explain|clarify|simplify)|explain (?:that|it)"
    r"|help me (?:do|with)|do it (?:for|with) me|walk me through|step by step|guide me"
    r"|what (?:prompt|button|link|page|option|step)s?\b|which (?:one|button|link|option)"
    r"|where (?:is|do|should)|how exactly|how do i do (?:it|that|this)"
    r")",
    re.I,
)


def is_repair(text: str) -> bool:
    """True when the caller signals they did not understand or wants hands-on help with the
    CURRENT step — so the agent re-explains its last message more simply, never repeats it."""
    return bool(_REPAIR_RE.search(text or ""))


# A short turn built around a back-reference pronoun ("how do I do THAT?", "help with IT")
# points at the active topic, so it must not overwrite it — a general anaphora signal, not a
# per-phrase rule.
_BACKREF_RE = re.compile(r"\b(?:that|this|it|those|them)\b", re.I)


def refers_back(text: str) -> bool:
    """True for a short utterance that leans on a back-reference pronoun (anaphora)."""
    return len((text or "").split()) <= 8 and bool(_BACKREF_RE.search(text or ""))


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
        # A "what next?" / "it didn't work" continuation or a repair ("what?", "help me") must
        # NEVER become the topic (the live bug where "What to do then?" overwrote the issue).
        thread = (
            is_followup_fragment(transcript)
            or is_continuation(transcript)
            or is_repair(transcript)
            or refers_back(transcript)
        )
        new_issue = (decision.caller_question or "").strip()
        if new_issue and not thread:
            state.active_topic = new_issue
        elif not state.active_topic and not thread:
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
        # Any grounded reply (with citations) is a step we've now COVERED — track it even when it
        # ends with a question, so the agent advances to a new step instead of re-suggesting one
        # it already gave (the live "go in circles around Task Manager" loop). Conversational glue
        # (acks, clarifying questions with no citation) is not a documented step, so it's skipped.
        if citations:
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
        """Clean, semantic query for retrieval — anchored on the active topic and (for a
        thread-continuing turn) the caller's evolving detail plus the last step the agent
        gave, so "then what?" / "it didn't work" / "only on wifi" keep pulling the SAME
        procedure instead of resetting or drifting to another document.

        Deliberately free of instruction text and keyword dumps: the embedder/reranker match
        best on concise, on-topic language. Domain ``retrieval_hints`` live only in the context
        the model reads (build_context), never here — a stray word like "laptop" in an email
        problem should not drag in slow-laptop keywords.
        """
        current = (decision.caller_question or decision.answer_value or transcript).strip()
        repair = is_repair(transcript)
        thread = repair or is_followup_fragment(transcript) or is_continuation(transcript)
        # The document the agent is already working from (its most recent citation, humanized) —
        # the single strongest anchor to keep retrieval on the same procedure.
        recent_source = next(
            (s.replace(".md", "").replace("_", " ") for s in reversed(state.recent_sources)), ""
        )

        ordered: list[str] = []
        if state.active_topic and (thread or state.active_topic.lower() not in current.lower()):
            ordered.append(state.active_topic)
        # A repair turn ("what?", "help me", "say it simply") carries no search value of its own,
        # so we search the topic + the doc in play — never the vague words (which polluted the
        # query and made retrieval loop on the same generic chunk).
        if not repair:
            ordered.append(current or transcript)
        if thread and recent_source:
            ordered.append(recent_source)

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
        # Progress tracker: the steps already given, so the agent ADVANCES to a new one instead
        # of circling back to a covered step or falsely claiming one is done.
        if state.suggested_steps:
            covered = "; ".join(f'"{s}"' for s in state.suggested_steps)
            parts.append(
                "Steps you have ALREADY given the caller (do NOT repeat any of these; pick a "
                f"genuinely DIFFERENT next step, and never go back to an earlier one): {covered}"
            )
        hints = self._matched_hints(searchable)
        if hints:
            parts.append(f"Relevant KB search hints: {' | '.join(hints)}")
        if self._continuity_prompt:
            parts.append(self._continuity_prompt)

        # Situation-specific instruction about the caller's LAST turn: repair (didn't understand)
        # -> simplify the CURRENT step; acceptance/answer (said yes / gave the info) -> act on it;
        # otherwise -> never repeat your last line.
        if is_repair(transcript) and last_assistant:
            parts.append(
                "The caller did NOT understand your previous message, or wants you to do it "
                f"WITH them. Your previous message was: \"{last_assistant}\". Do NOT repeat it and "
                "do NOT jump back to an earlier step. Re-explain THIS SAME step far more simply: "
                "give ONLY the very first concrete action to take right now, in one short plain "
                "sentence, and ask them to tell you when it's done."
            )
        elif last_assistant.rstrip().endswith("?") and (
            is_affirmation(transcript) or decision.intent is TurnIntent.ANSWER
        ):
            parts.append(
                "The caller has just answered or agreed to your last question. ACT on their "
                "answer and move forward — do NOT ask them to confirm what they just told you, "
                "and do NOT repeat the question."
            )
        elif last_assistant:
            parts.append(
                f"You already said: \"{last_assistant}\". Do NOT repeat it or reword it — either "
                "give the NEXT step, or break the current step into a simpler sub-step."
            )

        guidance = (
            "Reply the way a calm, competent human agent would on a call. Do NOT echo or restate "
            "what the caller just said, and do NOT narrate your sources — never say \"according "
            "to\", \"the guide\", \"the document\", \"the procedure\", \"the knowledge base\", "
            "\"as I mentioned\", or \"as I said\". You CANNOT do anything on the caller's device "
            "or account yourself — never claim you did something (\"I've done\", \"I've gone "
            "ahead\", \"I've reset it\"); ask the caller to do each step and tell you the result. "
            "Give one clear next step or one short question in your own natural words, then stop. "
            "Don't start over or repeat a step already covered above. If a step was tried and "
            "failed, continue with the NEXT step — never invent one. If the caller goes off-topic, "
            "briefly say you can only help with their issue, then continue from the CURRENT step. "
            "If nothing is left to try, offer to escalate or have a human follow up."
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
