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
        self.questions: list[str] = []          # the rich context the model reads
        self.search_queries: list[str | None] = []  # the clean query used for retrieval

    async def answer(self, question: str, *, search_query: str | None = None) -> GroundedAnswer:
        self.questions.append(question)
        self.search_queries.append(search_query)
        return self._answer

    async def answer_streaming(self, question: str, *, search_query: str | None = None):
        self.questions.append(question)
        self.search_queries.append(search_query)
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


# --------------------------------------------------------------------------- #
# Conversation continuity (domain-agnostic multi-turn coherence)              #
# --------------------------------------------------------------------------- #
from src.agent.continuity import (  # noqa: E402 — grouped with the tests that use it
    ContinuityTracker,
    indicates_failure,
    is_affirmation,
    is_continuation,
    is_followup_fragment,
    is_repair,
)


def test_repair_requests_are_recognized_but_real_questions_are_not() -> None:
    for repair in ("what?", "I didn't understand", "can you say that simply", "help me do that",
                   "walk me through it", "what prompts are you talking about?",
                   "which button?", "how do I do that?"):
        assert is_repair(repair), repair
    assert not is_repair("my vpn shows an authentication error")
    assert not is_repair("the salary range please")


def test_covered_steps_are_tracked_even_when_a_step_ends_with_a_question() -> None:
    """A grounded step is recorded as 'covered' even if phrased as a question, so the agent
    advances instead of circling back to it."""
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.active_topic = "slow laptop"
    step = "Can you check free space on your C: drive?"
    tracker.record_assistant(state, step, ["laptop_slow.md"])

    assert state.suggested_steps == [step]

    state.add_turn("user", "I did that, what's next?")
    context = tracker.build_context(
        state, "I did that, what's next?", TurnDecision(TurnIntent.ANSWER)
    )
    assert "ALREADY given" in context
    assert "check free space" in context
    assert "DIFFERENT next step" in context


def test_guidance_forbids_false_agency_and_redundant_confirmation() -> None:
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.active_topic = "slow laptop"
    state.add_turn("user", "opera uses the most resources")
    context = tracker.build_context(
        state, "opera uses the most resources", TurnDecision(TurnIntent.ANSWER),
    ).lower()
    assert "cannot" in context and "never claim you did" in context   # no false "I've done it"
    assert "off-topic" in context or "off topic" in context           # off-topic handling


def test_anaphoric_turn_does_not_overwrite_the_active_topic() -> None:
    """"How can I do that?" leans on a pronoun -> it points at the active topic, not a new one."""
    from src.agent.continuity import refers_back

    assert refers_back("how can I do that?")
    assert not refers_back("my vpn shows an authentication error and won't connect at all")

    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    tracker.note_user_turn(
        state, "I can't open my email",
        TurnDecision(TurnIntent.QUESTION, caller_question="I can't open my email"),
    )
    tracker.note_user_turn(
        state, "how can I do that?",
        TurnDecision(TurnIntent.QUESTION, caller_question="how to do that"),
    )
    assert state.active_topic == "I can't open my email"


def test_repair_context_tells_model_to_simplify_its_last_message() -> None:
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.active_topic = "reset password"
    state.add_turn("assistant", "Go to reset.acteek.local, choose Forgot password, then continue.")
    state.add_turn("user", "what prompts are you talking about?")

    context = tracker.build_context(
        state, "what prompts are you talking about?", TurnDecision(TurnIntent.ANSWER),
    )
    assert "far more simply" in context
    assert "Do NOT repeat it" in context


def test_repair_search_query_is_clean_not_polluted_with_vague_words() -> None:
    """"Help me doing that" must search the topic + the doc in play, not a pile of fragments."""
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.active_topic = "can't open my email"
    state.recent_sources = ["email_access.md", "password_reset.md"]
    for turn in ("I do how can I do that?", "Not working for me.", "Help me doing that."):
        state.add_turn("user", turn)

    query = tracker.build_search_query(
        state, "Help me doing that.", TurnDecision(TurnIntent.ANSWER),
    )
    assert "can't open my email" in query.lower()
    assert "password reset" in query.lower()          # the document already in play
    assert "help me" not in query.lower()             # vague words dropped
    assert "not working for me" not in query.lower()  # no accumulated pollution
    assert len(query) < 100


def test_continuation_phrases_are_recognized_but_resolutions_are_not() -> None:
    for cont in ("then what?", "what next", "and then?", "it didn't work", "same problem",
                 "next step please", "so what do I do now", "still not working",
                 "what to do then?", "don't have other solutions?"):
        assert is_continuation(cont), cont
    # A resolution or a brand-new question is not a "continue the thread" signal.
    assert not is_continuation("that worked, thanks")
    assert not is_continuation("what is the salary for this role?")


def test_affirmation_detects_acceptance_but_not_refusal() -> None:
    for yes in ("yes", "yes please", "please do that", "go ahead", "sure", "ok do it"):
        assert is_affirmation(yes), yes
    assert not is_affirmation("no thanks")
    assert not is_affirmation("not yet")


def test_continuation_never_overwrites_the_active_topic() -> None:
    """The live bug: "What to do then?" (mis-classified as a new question) wiped the issue."""
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    tracker.note_user_turn(
        state, "I can't open my email",
        TurnDecision(TurnIntent.QUESTION, caller_question="I can't open my email"),
    )
    assert state.active_topic == "I can't open my email"

    tracker.note_user_turn(
        state, "What to do then?",
        TurnDecision(TurnIntent.QUESTION, caller_question="What to do then?"),
    )
    assert state.active_topic == "I can't open my email"   # thread preserved


def test_thread_search_anchors_on_recent_source_not_the_agent_paragraph() -> None:
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.active_topic = "can't open my email"
    state.recent_sources = ["email_access.md", "password_reset.md"]
    state.add_turn("user", "Then what to do?")

    query = tracker.build_search_query(
        state, "Then what to do?", TurnDecision(TurnIntent.ANSWER),
    )
    assert "can't open my email" in query.lower()
    assert "password reset" in query.lower()      # the document the agent is working from
    assert "[" not in query and len(query) < 200  # clean, not a giant blob


def test_context_flags_caller_acceptance_so_the_agent_stops_re_offering() -> None:
    tracker = ContinuityTracker()
    state = ConversationState(call_id="c")
    state.add_turn("assistant", "I can raise a ticket. Would you like me to do that?")
    state.add_turn("user", "Yes, please do that.")

    context = tracker.build_context(
        state, "Yes, please do that.",
        TurnDecision(TurnIntent.ANSWER, answer_value="yes"),
    )
    assert "ACT on their answer" in context           # act, don't re-offer
    assert "do NOT repeat the question" in context


def test_followup_fragments_are_recognized_but_real_questions_are_not() -> None:
    for fragment in (
        "yes", "no", "nope", "I tried that", "it didn't work", "same problem",
        "only in video calls", "tell me more", "still not working",
    ):
        assert is_followup_fragment(fragment), fragment
    # A substantive new question must NOT be treated as a bare follow-up.
    assert not is_followup_fragment("what is the salary range for this role?")
    assert not is_followup_fragment("my vpn says authentication failed")


def test_indicates_failure_detects_a_step_that_did_not_work() -> None:
    assert indicates_failure("I tried that but it didn't work")
    assert indicates_failure("still not working")
    assert indicates_failure("same problem as before")
    assert not indicates_failure("yes that fixed it")


def _grounded_state() -> ConversationState:
    # Start on the grounded_qa state (index 2 in _domain()) so the caller leads.
    return ConversationState(call_id="c1", state_index=2)


@pytest.mark.asyncio
async def test_followup_answer_is_searched_with_previous_context_not_alone() -> None:
    """A terse clarifying answer must not be sent to RAG as an isolated query (req 2)."""
    responder = _responder("Let's narrow that down.")
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="vpn keeps disconnecting"),
            TurnDecision(TurnIntent.ANSWER, answer_value="only on wifi"),
        ],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("my vpn keeps disconnecting")
    await mgr.handle_turn("only on wifi")

    follow_up = responder.questions[-1]
    assert follow_up != "only on wifi"                       # not searched alone
    assert "Caller replied: only on wifi" in follow_up       # the fragment is kept as context
    assert "vpn keeps disconnecting" in follow_up            # anchored to the active topic

    # The CLEAN retrieval query is short and anchored on the topic — not the bare fragment,
    # and not the verbose context blob (which would dilute the embedding / reranker).
    search = responder.search_queries[-1]
    assert search is not None
    assert "vpn keeps disconnecting" in search.lower()
    assert "only on wifi" in search.lower()
    assert "Caller replied:" not in search                   # no context labels in the query
    assert "Stay on the caller's active issue" not in search  # no instructions in the query


@pytest.mark.asyncio
async def test_tried_that_didnt_work_continues_same_topic_and_records_failed_step() -> None:
    """"I tried that, it didn't work" keeps the issue and lists the failed step so the model
    continues to the NEXT documented step instead of inventing one (req 1, 2, 4)."""
    responder = _responder("Try restarting the device.", citations=["kb.md"])
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="printer is offline"),
            TurnDecision(TurnIntent.ANSWER, answer_value=""),
        ],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("my printer is offline")
    # The grounded reply was captured as a suggested step...
    assert mgr.state.suggested_steps == ["Try restarting the device."]
    assert mgr.state.active_topic == "printer is offline"

    await mgr.handle_turn("I tried that, it didn't work")

    # ...and reporting it failed retires it and anchors the next search on the same topic.
    assert mgr.state.failed_steps == ["Try restarting the device."]
    follow_up = responder.questions[-1]
    assert follow_up != "I tried that, it didn't work"
    assert "printer is offline" in follow_up
    assert "Steps already tried without success: Try restarting the device." in follow_up


@pytest.mark.asyncio
async def test_continuation_followup_is_not_treated_as_small_talk_reset() -> None:
    """The live bug: "Then what to do?" was classified meta and the agent replied with its
    opening line. A continuation in a caller-led flow must ground the next step instead."""
    responder = _responder("Next, open the self-service portal.", citations=["kb.md"])
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="I can't reset my password"),
            TurnDecision(TurnIntent.META),   # classifier mislabels "then what?" as small talk
        ],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("I can't reset my password")
    turn = await mgr.handle_turn("Then what to do?")

    # It grounded the follow-up (2 RAG calls) instead of re-reading the opening prompt.
    assert len(responder.questions) == 2
    assert "Any questions for me?" not in turn.text          # did NOT reset to the state prompt
    assert turn.text == "Next, open the self-service portal."
    assert mgr.state.state_index == 2                          # stayed on the same state
    # The follow-up search kept the thread (topic + the caller's turn), not a bare fragment.
    assert responder.search_queries[-1] != "Then what to do?"
    assert "reset my password" in responder.search_queries[-1].lower()


@pytest.mark.asyncio
async def test_bare_yes_after_a_step_is_grounded_not_a_canned_of_course() -> None:
    """"Yes, exactly" mid-issue should make the agent ACT and advance, not reply
    "Of course. Of course. <repeat>"."""
    responder = _responder("Great — close Opera's extra tabs and check if it speeds up.", ["kb.md"])
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="slow laptop"),
            TurnDecision(TurnIntent.META),   # "yes, exactly" classified as meta
        ],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("my laptop is slow")
    turn = await mgr.handle_turn("yes, exactly")

    assert len(responder.questions) == 2                 # grounded and advanced
    assert not turn.text.lower().startswith("of course")


@pytest.mark.asyncio
async def test_generic_meta_does_not_stack_of_course_of_course() -> None:
    state = ConversationState(call_id="c1", state_index=2)  # grounded_qa, no active topic yet
    state.add_turn("assistant", "Of course, let's restart the laptop.")
    mgr = _manager([TurnDecision(TurnIntent.META)], _responder(), state=state)

    turn = await mgr.handle_turn("hmm ok")

    assert turn.text.lower().count("of course") == 1


@pytest.mark.asyncio
async def test_repair_request_is_grounded_and_simplified_not_a_canned_dump() -> None:
    """"What prompts?" / "help me do that" must get a simpler grounded re-explanation, not a
    verbatim re-dump of the last answer (the live loop)."""
    responder = _responder("First, open your browser and go to reset.acteek.local.", ["kb.md"])
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="reset password"),
            TurnDecision(TurnIntent.META),   # "what prompts?" mislabeled as small talk
        ],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("how do I reset my password?")
    turn = await mgr.handle_turn("what prompts are you talking about?")

    assert len(responder.questions) == 2                 # grounded (simplify), not canned
    assert "far more simply" in responder.questions[-1]  # context asked it to simplify
    assert "Any questions for me?" not in turn.text


@pytest.mark.asyncio
async def test_meta_repeat_rereads_last_answer_not_the_opening_line() -> None:
    """"Can you repeat?" mid-conversation repeats the agent's last line, not the greeting."""
    responder = _responder(
        "Go to reset.acteek.local and choose Forgot password.", citations=["kb.md"]
    )
    mgr = _manager(
        [TurnDecision(TurnIntent.QUESTION, caller_question="password reset")],
        responder,
        state=_grounded_state(),
    )

    await mgr.handle_turn("how do I reset my password?")
    turn = await mgr.handle_turn("sorry, can you repeat that?")

    assert turn.text == "Sure — Go to reset.acteek.local and choose Forgot password."
    assert "Any questions for me?" not in turn.text            # not the opening state prompt


@pytest.mark.asyncio
async def test_continuity_memory_survives_state_serialization() -> None:
    """The rolling continuity memory round-trips through the store like the rest of state."""
    from src.agent.state import InMemoryStateStore

    responder = _responder("Check disk space.", citations=["laptop_slow.md"])
    store = InMemoryStateStore()
    decisions = [TurnDecision(TurnIntent.QUESTION, caller_question="slow laptop")]
    mgr = DialogueManager(
        classifier=FakeClassifier(decisions),
        responder=responder,
        domain=_domain(),
        state=_grounded_state(),
        store=store,
    )
    await mgr.handle_turn("my laptop is slow")

    reloaded = await store.load("c1")
    assert reloaded is not None
    assert reloaded.active_topic == "slow laptop"
    assert reloaded.suggested_steps == ["Check disk space."]
    assert "laptop_slow.md" in reloaded.recent_sources
