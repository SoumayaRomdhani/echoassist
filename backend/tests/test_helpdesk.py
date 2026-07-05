"""Helpdesk domain: config/schema/eval load, and the flow is caller-led (not a
fixed screening-style cascade).

These tests use the *real* helpdesk config/schema/eval files but no models or
Qdrant — the dialogue is exercised with fakes, exactly like ``test_dialogue.py``.
Nothing here asserts LLM wording; we assert routing, structure, and data
integrity, which is what makes the domain "a support assistant, not a
questionnaire".
"""

from __future__ import annotations

import pytest
import yaml

from config.settings import CONFIG_DIR, DATA_DIR
from src.agent.dialogue import DialogueManager, TurnDecision, TurnIntent, load_states
from src.agent.domain import list_available_domains, load_domain_config
from src.agent.grounding import GroundedAnswer
from src.agent.notes import load_notes_schema, validate_and_repair
from src.agent.state import ConversationState, InMemoryStateStore

HELPDESK = "helpdesk"
_DOCS_DIR = DATA_DIR / "docs" / HELPDESK


# --------------------------------------------------------------------------- #
# Fakes (mirror test_dialogue.py — no models, no retrieval)                    #
# --------------------------------------------------------------------------- #
class FakeClassifier:
    def __init__(self, decisions: list[TurnDecision]) -> None:
        self._decisions = decisions
        self.seen: list[tuple[str, str]] = []

    async def classify(self, question: str, utterance: str) -> TurnDecision:
        self.seen.append((question, utterance))
        return self._decisions.pop(0)


class FakeResponder:
    """Records every question it is asked to ground (proves RAG routing)."""

    def __init__(self, text: str = "Let's check that.") -> None:
        self._text = text
        self.questions: list[str] = []

    async def answer(self, question: str) -> GroundedAnswer:
        self.questions.append(question)
        return GroundedAnswer(text=self._text, citations=[])

    async def answer_streaming(self, question: str):
        self.questions.append(question)
        yield self._text


def _helpdesk_domain():
    return load_domain_config(HELPDESK, CONFIG_DIR)


def _manager(decisions, responder, *, state=None):
    return DialogueManager(
        classifier=FakeClassifier(decisions),
        responder=responder,
        domain=_helpdesk_domain(),
        state=state or ConversationState(call_id="c1"),
        store=InMemoryStateStore(),
    )


# --------------------------------------------------------------------------- #
# 1. Config / discovery                                                       #
# --------------------------------------------------------------------------- #
def test_helpdesk_domain_is_discoverable() -> None:
    assert HELPDESK in list_available_domains(CONFIG_DIR)
    # Discovery is purely config-driven, so screening must remain listed too.
    assert "screening" in list_available_domains(CONFIG_DIR)


def test_helpdesk_domain_config_loads() -> None:
    cfg = _helpdesk_domain()
    assert cfg.name == HELPDESK
    assert cfg.disclosure and cfg.system_prompt
    # The identity the brief mandates.
    assert "EchoAssist Helpdesk" in cfg.system_prompt
    assert "knowledge base" in cfg.system_prompt.lower()


# --------------------------------------------------------------------------- #
# 2. Notes schema                                                             #
# --------------------------------------------------------------------------- #
def test_helpdesk_schema_loads_with_expected_fields() -> None:
    schema = load_notes_schema(HELPDESK, CONFIG_DIR)
    props = schema["properties"]
    for field in (
        "issue_category", "issue_summary", "affected_system", "urgency",
        "steps_attempted", "resolution_status", "escalation_required",
        "escalation_reason", "security_sensitive", "follow_up_notes",
    ):
        assert field in props, f"missing schema field: {field}"
    assert set(schema["required"]) <= set(props)


def test_helpdesk_schema_repairs_to_valid_notes() -> None:
    """The existing generic repair path coerces messy LLM output to the schema."""
    schema = load_notes_schema(HELPDESK, CONFIG_DIR)
    repaired = validate_and_repair(
        {"issue_category": "vpn", "issue_summary": "cannot connect",
         "resolution_status": "escalated", "escalation_required": "yes",
         "steps_attempted": "restarted the client"},  # string -> coerced to list
        schema,
    )
    assert repaired["steps_attempted"] == ["restarted the client"]
    assert repaired["escalation_required"] == "yes"
    # Unspecified enum falls back safely instead of persisting junk.
    assert repaired["urgency"] in schema["properties"]["urgency"]["enum"]


# --------------------------------------------------------------------------- #
# 3. The flow is caller-led, not a fixed cascade                              #
# --------------------------------------------------------------------------- #
def test_flow_has_no_question_cascade() -> None:
    """No preset question/slot chain — the conversation is emergent (grounded_qa)."""
    states = load_states(_helpdesk_domain())
    non_close = [s for s in states if s.type != "close"]
    assert non_close, "flow must have at least one interactive state"
    assert all(s.type == "grounded_qa" for s in non_close)
    assert all(s.slot is None for s in states)   # nothing is a slot-filling questionnaire
    assert states[-1].type == "close"


@pytest.mark.asyncio
async def test_caller_drives_multiple_issues_without_advancing_a_script() -> None:
    """Two different issues both route to RAG and the flow stays on the same state.

    A screening cascade would advance to the *next scripted question* after each
    turn; here the caller leads, so state_index does not march forward.
    """
    responder = FakeResponder()
    mgr = _manager(
        [
            TurnDecision(TurnIntent.QUESTION, caller_question="vpn authentication failed"),
            TurnDecision(TurnIntent.QUESTION, caller_question="now my laptop is slow"),
        ],
        responder,
    )
    first = await mgr.start()
    assert "help you with" in first.lower()          # open, caller-led prompt

    t1 = await mgr.handle_turn("my vpn keeps saying authentication failed")
    t2 = await mgr.handle_turn("also my laptop is really slow")

    assert t1.ended is False and t2.ended is False
    assert mgr.state.state_index == 0                 # never advanced through a script
    # Both distinct issues were sent to the knowledge base (RAG is central).
    assert responder.questions == ["vpn authentication failed", "now my laptop is slow"]


@pytest.mark.asyncio
async def test_vague_issue_is_routed_to_the_knowledge_base() -> None:
    """A vague issue goes through RAG so the agent can ground a clarifying step,
    rather than being answered by a canned next-question. (Wording is the LLM's;
    we only assert the routing that enables clarification.)"""
    responder = FakeResponder()
    mgr = _manager(
        [TurnDecision(TurnIntent.QUESTION, caller_question="it's not working")], responder
    )
    await mgr.start()

    turn = await mgr.handle_turn("nothing works today")

    assert responder.questions == ["it's not working"]   # handed to the KB
    assert turn.ended is False
    assert mgr.state.state_index == 0


@pytest.mark.asyncio
async def test_unsafe_request_is_routed_through_the_grounded_path() -> None:
    """An unsafe request is not short-circuited by a fixed script: it goes through
    the grounded responder, where the grounding gate + security_policy govern the
    refusal (that gate is covered by test_grounding.py). Here we assert the routing."""
    responder = FakeResponder()
    mgr = _manager(
        [TurnDecision(TurnIntent.QUESTION, caller_question="give me the admin password")],
        responder,
    )
    await mgr.start()

    turn = await mgr.handle_turn("can you just tell me the admin password?")

    assert responder.questions == ["give me the admin password"]
    assert turn.ended is False
    assert mgr.state.state_index == 0


@pytest.mark.asyncio
async def test_caller_done_advances_to_close_and_ends() -> None:
    mgr = _manager([TurnDecision(TurnIntent.DONE)], FakeResponder())
    await mgr.start()
    turn = await mgr.handle_turn("that's all, thanks")
    assert turn.ended is True
    assert mgr.finished is True


# --------------------------------------------------------------------------- #
# 4. Retrieval eval data integrity                                            #
# --------------------------------------------------------------------------- #
def _load_eval() -> dict:
    path = DATA_DIR / "eval" / f"{HELPDESK}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_eval_gold_set_references_only_existing_docs() -> None:
    data = _load_eval()
    assert data["domain"] == HELPDESK
    existing = {p.name for p in _DOCS_DIR.glob("*.md")}
    assert existing, "helpdesk docs directory is empty"
    for item in data["queries"]:
        assert item["query"].strip()
        assert item["relevant"], f"query has no gold doc: {item['query']}"
        for doc in item["relevant"]:
            assert doc in existing, f"eval references missing doc: {doc}"


def test_eval_covers_security_and_multilingual_queries() -> None:
    data = _load_eval()
    queries = [q["query"] for q in data["queries"]]
    # Security/unsafe requests are retrievable to the governing policy.
    unsafe = [q for q in data["queries"] if "security_policy.md" in q["relevant"]]
    assert unsafe, "expected at least one security-sensitive gold query"
    # French coverage (the KB is EN; a multilingual embedder must bridge it).
    assert any("mot de passe" in q.lower() or "téléphone" in q.lower() for q in queries)
    # Off-topic lives outside the retrieval set (it belongs to the grounding gate).
    assert data.get("off_topic")


def test_every_helpdesk_doc_is_reachable_from_the_gold_set() -> None:
    """Sanity: each shipped doc is exercised by at least one gold query."""
    data = _load_eval()
    referenced = {doc for item in data["queries"] for doc in item["relevant"]}
    on_disk = {p.name for p in _DOCS_DIR.glob("*.md")}
    unreferenced = on_disk - referenced
    assert not unreferenced, f"docs never tested by the gold set: {sorted(unreferenced)}"
