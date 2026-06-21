"""Structured notes extraction (LLM function calling).

Produces a notes object matching ``config/schemas/{domain}.json`` from a completed
call. The five factual fields are captured as interview slots during the call
(Sprint 3) and are authoritative; the LLM adds recruiter-facing enrichment
(name, strengths, concerns, overall fit) from the transcript.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.agent.jsonutil import extract_json
from src.agent.state import ConversationState
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role, ToolSpec

log = logging.getLogger("echoassist.agent.notes")

_RECORD_TOOL_NAME = "record_screening_notes"

# Schema fields that come straight from the interview slots (authoritative).
_SLOT_FIELDS = (
    "years_experience",
    "primary_stack",
    "availability",
    "remote_setup",
    "salary_expectation",
)

_SYSTEM = (
    "You extract structured notes from a completed candidate phone-screening call. "
    "Use ONLY what the candidate actually said — never invent facts. Call the "
    f"{_RECORD_TOOL_NAME} tool with the fields. For fields already provided as SLOTS, "
    "copy the slot value. Infer strengths, concerns, and overall_fit only from the "
    "transcript; if there is no basis, use empty values or \"unknown\"."
)


def load_notes_schema(domain: str, config_dir: Path) -> dict:
    path = config_dir / "schemas" / f"{domain}.json"
    if not path.exists():
        raise FileNotFoundError(f"No notes schema for domain '{domain}': {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _render(state: ConversationState) -> str:
    slots = json.dumps(state.slots, ensure_ascii=False, indent=2)
    transcript = "\n".join(f"{t['role']}: {t['text']}" for t in state.transcript)
    return f"SLOTS:\n{slots}\n\nTRANSCRIPT:\n{transcript}"


class NotesExtractor:
    def __init__(self, llm: LLMProvider, schema: dict) -> None:
        self._llm = llm
        self._schema = schema
        self._tool = ToolSpec(
            name=_RECORD_TOOL_NAME,
            description="Record the structured screening notes for this candidate call.",
            parameters=schema,
        )

    async def extract(self, state: ConversationState) -> dict:
        messages = [Message(Role.SYSTEM, _SYSTEM), Message(Role.USER, _render(state))]
        response = await self._llm.chat(messages, tools=[self._tool])

        if response.tool_calls:
            notes = dict(response.tool_calls[0].arguments)
        else:  # model answered with text instead of calling the tool
            notes = extract_json(response.text) or {}

        # Slots are authoritative for the factual fields.
        for field in _SLOT_FIELDS:
            value = state.slots.get(field)
            if value:
                notes[field] = value
        log.info("notes extracted: %s", ", ".join(sorted(notes)))
        return notes
