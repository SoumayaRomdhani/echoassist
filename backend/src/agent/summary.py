"""Grounded post-call summary.

A short, factual recruiter-facing summary grounded in the transcript — no
invention and no hiring verdict (the subjective assessment lives in the
structured notes' ``overall_fit``). Guards against empty/truncated output and
retries once before giving up.
"""

from __future__ import annotations

import logging

from src.agent.state import ConversationState
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role

log = logging.getLogger("echoassist.agent.summary")

_SYSTEM = (
    "You write a concise, factual post-call summary of a candidate phone screening "
    "for a recruiter. Use ONLY what was said in the transcript — do not invent facts. "
    "Write 3 to 4 plain sentences covering experience, tech stack, availability, "
    "remote/location, and salary expectation. Do NOT give a hiring verdict or a fit "
    "judgement. No bullet points, no markdown."
)

_FALLBACK = "No summary available: the call has no transcript."
_INCOMPLETE = "No reliable summary could be generated for this call."
_MIN_LENGTH = 40


def _looks_incomplete(text: str) -> bool:
    text = text.strip()
    return not text or len(text) < _MIN_LENGTH or text[-1] not in ".!?"


class SummaryGenerator:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def _generate(self, transcript: str) -> str:
        response = await self._llm.chat(
            [Message(Role.SYSTEM, _SYSTEM), Message(Role.USER, transcript)]
        )
        return response.text.strip()

    async def summarize(self, state: ConversationState) -> str:
        if not state.transcript:
            return _FALLBACK
        transcript = "\n".join(f"{t['role']}: {t['text']}" for t in state.transcript)

        try:
            summary = await self._generate(transcript)
        except ProviderError as exc:
            log.warning("summary generation failed (%s); using fallback summary", exc)
            return _INCOMPLETE
        if _looks_incomplete(summary):
            log.info("summary looked incomplete (%r); retrying once", summary[:40])
            try:
                summary = await self._generate(transcript)
            except ProviderError as exc:
                log.warning("summary retry failed (%s); using fallback summary", exc)
                return _INCOMPLETE

        # Never persist an empty or truncated summary.
        return summary if not _looks_incomplete(summary) else _INCOMPLETE
