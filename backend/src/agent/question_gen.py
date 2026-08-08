"""Interview-question generation from a job description (LLM function calling).

A recruiter pastes a job description (fiche de poste); the LLM drafts a short set
of screening questions from it. The recruiter then reviews/edits/confirms them and
the enabled questions drive a tailored interview (see ``states_from_questions``)
instead of the static ``screening.yaml`` flow.

The output is normalized to the ``JobPosting.questions`` shape — an ordered list of
``{"id", "text", "slot", "enabled"}`` — with guardrails: the count is clamped, text
is length-bounded, and each ``slot`` is a unique machine-safe identifier derived
from the question. Provider-agnostic: any ``LLMProvider`` (Groq, Gemini, ...) works.
"""

from __future__ import annotations

import logging
import re

from src.agent.jsonutil import extract_json
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role, ToolSpec

log = logging.getLogger("echoassist.agent.question_gen")

_RECORD_TOOL_NAME = "record_questions"

# Guardrails — bound what we accept back from the model.
DEFAULT_MAX_QUESTIONS = 8
MAX_QUESTIONS_LIMIT = 20   # hard cap for a recruiter-curated set (manual edits)
MAX_QUESTION_LEN = 300
MAX_SLOT_LEN = 40

_SYSTEM = (
    "You are helping a recruiter build a phone-screening interview. From the job "
    "description, produce short, spoken screening questions a voice assistant will ask "
    "a candidate — one topic each, neutral and answerable by voice. Do NOT ask for "
    "protected characteristics (age, marital status, religion, health). Write the "
    "questions in the SAME language as the job description. Prefer role-specific "
    f"questions over generic ones. Return at most {DEFAULT_MAX_QUESTIONS} questions by "
    f"calling the {_RECORD_TOOL_NAME} tool."
)

_JSON_FALLBACK_SYSTEM = (
    "You are helping a recruiter build a phone-screening interview. From the job "
    "description, produce short spoken screening questions in the SAME language as the "
    'description. Return ONLY a JSON object {"questions": [{"text": ...}]} — no markdown, '
    "no prose."
)

_QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The question to ask, spoken."},
                    "slot": {
                        "type": "string",
                        "description": "Short snake_case name for the answer, e.g. years_python.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    "required": ["questions"],
}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:MAX_SLOT_LEN].strip("_")


def normalize_questions(raw: list, *, max_questions: int = DEFAULT_MAX_QUESTIONS) -> list[dict]:
    """Coerce raw model output into the JobPosting.questions shape, with guardrails.

    Accepts a list of ``{"text", "slot"?, "enabled"?}`` dicts (or bare strings). Drops
    empties, bounds text length, derives a machine-safe unique ``slot`` per question,
    assigns stable ``q{n}`` ids, preserves ``enabled`` (default True), and clamps the count.
    """
    questions: list[dict] = []
    used_slots: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        elif not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:MAX_QUESTION_LEN]
        if not text:
            continue

        slot = _slugify(str(item.get("slot") or "").strip()) or _slugify(text) or "question"
        base, n = slot, 2
        while slot in used_slots:  # keep slot names unique for downstream slot-filling
            slot = f"{base}_{n}"[:MAX_SLOT_LEN]
            n += 1
        used_slots.add(slot)

        questions.append({
            "id": f"q{len(questions) + 1}",
            "text": text,
            "slot": slot,
            "enabled": bool(item.get("enabled", True)),
        })
        if len(questions) >= max_questions:
            break
    return questions


class QuestionGenerator:
    """Drafts screening questions from a job description via an LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._tool = ToolSpec(
            name=_RECORD_TOOL_NAME,
            description="Record the screening questions drafted from the job description.",
            parameters=_QUESTIONS_SCHEMA,
        )

    async def generate(
        self, description: str, *, max_questions: int = DEFAULT_MAX_QUESTIONS
    ) -> list[dict]:
        """Return a normalized list of ``{id, text, slot, enabled}`` questions."""
        user = f"JOB DESCRIPTION:\n{description.strip()}"
        try:
            response = await self._llm.chat(
                [Message(Role.SYSTEM, _SYSTEM), Message(Role.USER, user)], tools=[self._tool]
            )
        except ProviderError as exc:
            # Some OpenAI-compatible models fail hard on function calling — fall back to JSON.
            log.warning("question tool call failed (%s); retrying as plain JSON", exc)
            response = await self._llm.chat(
                [Message(Role.SYSTEM, _JSON_FALLBACK_SYSTEM), Message(Role.USER, user)]
            )

        if response.tool_calls:
            payload = dict(response.tool_calls[0].arguments)
        else:  # model answered with text instead of calling the tool
            payload = extract_json(response.text) or {}

        raw = payload.get("questions", [])
        if not isinstance(raw, list):
            raw = []
        questions = normalize_questions(raw, max_questions=max_questions)
        log.info("generated %d screening question(s)", len(questions))
        return questions
