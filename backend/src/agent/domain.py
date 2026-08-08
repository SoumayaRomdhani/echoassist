"""Domain configuration loader.

A "domain" is config, not code (ARCHITECTURE.md §3): an interview flow file
plus (later) a notes schema and a document collection. Sprint 1 reads the
disclosure, greeting, and system prompt; the full ``flow`` dict is retained for
the Sprint 3 state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

_DEFAULT_CONSENT_REPROMPT = (
    "Sorry, I didn't catch a clear yes or no. Do you consent to continue with this "
    "recorded call? Please say yes or no."
)
_DEFAULT_CONSENT_DECLINE = (
    "That's completely fine. I won't continue without your consent. "
    "Thank you for your time, and goodbye."
)


@dataclass(frozen=True, slots=True)
class DomainConfig:
    name: str
    language: str
    disclosure: str
    greeting: str
    system_prompt: str
    consent_reprompt: str
    consent_decline: str
    flow: dict = field(default_factory=dict)
    # Optional conversation-quality tuning (all domain-agnostic; blank => engine defaults):
    #   fallback_prompt    -> deterministic reply when nothing confident is retrieved
    #                         (never mentions the knowledge base to the caller).
    #   escalation_wording -> phrase the agent offers when a procedure is exhausted.
    #   continuity_prompt  -> extra guidance folded into the context-anchored RAG query.
    # The mechanisms live in the generic dialogue/grounding/continuity layer; these only
    # tune wording, so existing and future domains benefit without engine changes.
    fallback_prompt: str = ""
    escalation_wording: str = ""
    continuity_prompt: str = ""


def list_available_domains(config_dir: Path) -> list[str]:
    """Return the domains that have an interview flow under ``config/interview_flows``.

    A domain is config, not code (ARCHITECTURE.md §3): its presence is the
    existence of ``{domain}.yaml``, so adding a domain needs no code change.
    """
    flows_dir = config_dir / "interview_flows"
    if not flows_dir.exists():
        return []
    return sorted(path.stem for path in flows_dir.glob("*.yaml"))


def states_from_questions(questions: list[dict], base: DomainConfig) -> list[dict]:
    """Build interview ``states`` from confirmed job-posting questions.

    Each enabled question becomes a ``type: question`` state (id / slot / prompt);
    the base domain's non-question states — the ``grounded_qa`` invite and the
    ``close`` line — are appended so a tailored interview still invites the
    candidate's own questions and closes exactly like the static flow.
    """
    question_states = [
        {
            "id": q["id"],
            "type": "question",
            "slot": q.get("slot") or q["id"],
            "prompt": str(q["text"]).strip(),
        }
        for q in questions
        if q.get("enabled", True) and str(q.get("text", "")).strip()
    ]
    tail = [s for s in base.flow.get("states", []) if s.get("type") != "question"]
    return question_states + tail


def with_question_flow(base: DomainConfig, questions: list[dict]) -> DomainConfig:
    """Return a copy of ``base`` whose interview questions come from ``questions``.

    Everything else (disclosure, greeting, consent wording, system prompt,
    grounded_qa/close, acknowledgements) is inherited from ``base``. Raises
    ``ValueError`` when no question is enabled — a tailored interview needs at
    least one question to open with.
    """
    states = states_from_questions(questions, base)
    if not any(s["type"] == "question" for s in states):
        raise ValueError("no enabled questions to build a tailored interview")
    return replace(base, flow={**base.flow, "states": states})


def load_domain_config(domain: str, config_dir: Path) -> DomainConfig:
    """Load ``config/interview_flows/{domain}.yaml`` into a :class:`DomainConfig`."""
    path = config_dir / "interview_flows" / f"{domain}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No interview flow for domain '{domain}': {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for required in ("disclosure", "system_prompt"):
        if not data.get(required):
            raise ValueError(f"Interview flow '{path}' is missing required field '{required}'.")

    return DomainConfig(
        name=data.get("domain", domain),
        language=data.get("language", "en"),
        disclosure=str(data["disclosure"]).strip(),
        greeting=str(data.get("greeting", "")).strip(),
        system_prompt=str(data["system_prompt"]).strip(),
        consent_reprompt=str(data.get("consent_reprompt", _DEFAULT_CONSENT_REPROMPT)).strip(),
        consent_decline=str(data.get("consent_decline", _DEFAULT_CONSENT_DECLINE)).strip(),
        flow=data,
        fallback_prompt=str(data.get("fallback_prompt", "")).strip(),
        escalation_wording=str(data.get("escalation_wording", "")).strip(),
        continuity_prompt=str(data.get("continuity_prompt", "")).strip(),
    )
