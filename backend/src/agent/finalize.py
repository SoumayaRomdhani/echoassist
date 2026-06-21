"""End-of-call finalization: extract notes, write the summary, persist everything.

Shared by the live interview (`scripts/run_interview.py`) and the offline
persistence demo (`scripts/finalize_call.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.notes import NotesExtractor
from src.agent.state import ConversationState
from src.agent.summary import SummaryGenerator
from src.providers.llm.base import LLMProvider
from src.storage.db import persist_call
from src.storage.models import Call

log = logging.getLogger("echoassist.agent.finalize")


@dataclass(slots=True)
class FinalizedCall:
    notes: dict
    summary: str
    call: Call


async def finalize_call(
    session: AsyncSession,
    state: ConversationState,
    *,
    llm: LLMProvider,
    schema: dict,
    campaign_name: str,
    domain: str,
    status: str = "completed",
) -> FinalizedCall:
    notes = await NotesExtractor(llm, schema).extract(state)
    summary = await SummaryGenerator(llm).summarize(state)
    call = await persist_call(
        session,
        campaign_name=campaign_name,
        domain=domain,
        state=state,
        notes=notes,
        summary=summary,
        status=status,
    )
    return FinalizedCall(notes=notes, summary=summary, call=call)
