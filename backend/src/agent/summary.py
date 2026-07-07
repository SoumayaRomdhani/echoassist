"""Grounded post-call summary.

A short, factual summary grounded in the transcript — no invention and no
verdict/judgement (any subjective assessment lives in the structured notes).
The prompt is domain-agnostic (a screening call and a helpdesk call both get a
correct summary); a domain may override the wording via ``summary_prompt`` in its
YAML. Guards against empty/truncated output and retries once before giving up.
"""

from __future__ import annotations

import logging

from src.agent.state import ConversationState
from src.providers.errors import ProviderError
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role

log = logging.getLogger("echoassist.agent.summary")

# Domain-agnostic default: works for any vertical because it summarises the transcript itself
# (what the caller needed, what happened, the outcome) rather than naming domain-specific fields.
_SYSTEM = (
    "You write a concise, factual post-call summary from the transcript. Use ONLY what was "
    "actually said — do not invent anything. In 3 to 4 plain sentences, cover what the caller "
    "needed or reported, what was done or discussed, and the outcome or next step. Do NOT give "
    "a verdict or judgement. No bullet points, no markdown."
)

_FALLBACK = "No summary available: the call has no transcript."
_INCOMPLETE = "No reliable summary could be generated for this call."
_MIN_LENGTH = 40


def _looks_incomplete(text: str) -> bool:
    text = text.strip()
    return not text or len(text) < _MIN_LENGTH or text[-1] not in ".!?"


class SummaryGenerator:
    def __init__(self, llm: LLMProvider, *, system_prompt: str | None = None) -> None:
        self._llm = llm
        # Domain YAML may override the wording (DomainConfig.summary_prompt); default is generic.
        self._system = (system_prompt or "").strip() or _SYSTEM

    async def _generate(self, transcript: str) -> str:
        response = await self._llm.chat(
            [Message(Role.SYSTEM, self._system), Message(Role.USER, transcript)]
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
