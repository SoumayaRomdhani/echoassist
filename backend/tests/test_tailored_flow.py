"""Building a tailored interview flow from job-posting questions (pure, no I/O)."""

from __future__ import annotations

import pytest

from src.agent.domain import DomainConfig, states_from_questions, with_question_flow


def _base() -> DomainConfig:
    return DomainConfig(
        name="screening", language="en", disclosure="disc", greeting="hi",
        system_prompt="sys", consent_reprompt="reprompt", consent_decline="decline",
        flow={
            "states": [
                {"id": "experience", "type": "question", "slot": "years", "prompt": "old q"},
                {"id": "candidate_questions", "type": "grounded_qa", "prompt": "Any questions?"},
                {"id": "close", "type": "close", "prompt": "Goodbye."},
            ],
            "transition_ack": ["Thanks."],
        },
    )


def test_states_replace_questions_and_keep_the_base_tail() -> None:
    questions = [
        {"id": "q1", "text": "Years with Go?", "slot": "years_go", "enabled": True},
        {"id": "q2", "text": "On-call ok?", "slot": "on_call", "enabled": False},  # dropped
    ]
    states = states_from_questions(questions, _base())

    assert [s["type"] for s in states] == ["question", "grounded_qa", "close"]
    assert states[0] == {
        "id": "q1", "type": "question", "slot": "years_go", "prompt": "Years with Go?"
    }
    # The base flow's non-question tail (invite + close) is inherited verbatim.
    assert states[1]["id"] == "candidate_questions"
    assert states[2]["id"] == "close"


def test_slot_defaults_to_id_when_missing() -> None:
    states = states_from_questions([{"id": "q1", "text": "Q?", "enabled": True}], _base())
    assert states[0]["slot"] == "q1"


def test_with_question_flow_inherits_everything_else_and_is_immutable() -> None:
    base = _base()
    tailored = with_question_flow(
        base, [{"id": "q1", "text": "Years with Go?", "slot": "years_go", "enabled": True}]
    )

    assert tailored.disclosure == base.disclosure            # non-flow fields inherited
    assert tailored.flow["transition_ack"] == ["Thanks."]    # rest of the flow inherited
    question_prompts = [s["prompt"] for s in tailored.flow["states"] if s["type"] == "question"]
    assert question_prompts == ["Years with Go?"]
    assert base.flow["states"][0]["prompt"] == "old q"       # base left untouched


def test_with_question_flow_requires_at_least_one_enabled_question() -> None:
    with pytest.raises(ValueError, match="no enabled questions"):
        with_question_flow(_base(), [{"id": "q1", "text": "x", "slot": "x", "enabled": False}])
