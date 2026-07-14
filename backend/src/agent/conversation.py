"""Conversational agent: the model holds the whole call and decides when to search.

Unlike :class:`~src.agent.grounding.GroundedResponder` (which retrieves on every turn from a
fabricated context string), the ``ConversationAgent`` gives the model the *real* conversation
history plus ONE tool — ``search_knowledge_base`` — and lets it decide, each turn, whether it
even needs the knowledge base:

- follow-ups / memory / chit-chat  -> answered directly from the conversation, no retrieval;
- a factual question or a procedure step -> the model calls the tool, we retrieve, it answers
  grounded and cited;
- off-topic or nothing-found        -> the model declines gracefully and stays on the issue,
  never a canned reset that drops the conversation.

This is the standard "agent + tool" pattern. It is **domain-agnostic** (the persona comes from
the domain system prompt; the rules here are generic, so screening / helpdesk / future domains
all benefit) and **provider-agnostic** (only ``LLMProvider.chat`` / ``chat_stream`` + the tool
interface are used).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from src.agent.grounding import SEARCH_TOOL, Citation, build_citations, strip_citations
from src.agent.guardrails import is_grounded, refusal_message
from src.agent.state import ConversationState
from src.observability import latency
from src.providers.llm.base import LLMProvider
from src.providers.types import Message, Role
from src.rag.retriever import Retriever
from src.rag.types import ScoredChunk

log = logging.getLogger("echoassist.agent.conversation")

# Generic conversation rules, appended to the domain persona. No domain-specific wording here.
_AGENT_BEHAVIOR = (
    "You are on a live voice call. Keep the WHOLE conversation in mind and stay on the caller's "
    "current issue.\n"
    "Decide EACH turn whether you need the knowledge base:\n"
    "- Call search_knowledge_base ONLY when you need a fact, step, policy, or procedure you do "
    "not already have from this conversation.\n"
    "- For a follow-up you can answer from what was already said (\"yes\", \"it worked\", "
    "\"guide me\", \"what's my problem?\", \"and then?\"), do NOT search — answer from the "
    "conversation.\n"
    "- For questions about YOU, the call, or this recording (\"are you an AI?\", \"are you "
    "recording this?\", \"can you hear me?\"), do NOT search: answer directly in one short "
    "sentence, then steer back to the current step.\n"
    "- If the caller asks something unrelated to what this call is about, do NOT search: say in "
    "one short sentence that you can only help with their issue, then steer back to the current "
    "step.\n"
    "- If you cannot understand the caller (garbled or unclear), do NOT search: briefly ask them "
    "to repeat.\n"
    "Diagnose before you fix: when the caller reports a NEW problem, do not launch into a generic "
    "checklist. First ask ONE targeted question to identify the specific failure mode (what "
    "exactly happens), unless they already described it — then follow the branch that matches "
    "their answer. One triage question, then act.\n"
    "Answering: reply in ONE short, natural spoken sentence — one next step or one question. No "
    "lists, no markdown. Never repeat a step you already gave. If the caller did not understand, "
    "re-explain the SAME step more simply as the first concrete action — do NOT switch to a "
    "different step or diagnostic. You cannot do anything on the caller's device — never claim "
    "you did it; ask them to do each step and report back. Act on what they just said; never ask "
    "them to confirm what they just told you. Never narrate your sources or say \"according to\", "
    "\"the guide\", or \"as I mentioned\".\n"
    "Grounding: base any fact or step ONLY on the tool results. Quote URLs, tool names, and exact "
    "values (like an address or a character limit) EXACTLY as they appear in the passages — never "
    "guess or complete a URL or value from memory. Cite the source as [filename] (it is removed "
    "before the caller hears it). If the tool returns nothing useful, or the exact detail is not "
    "in the passages, say you do not have that specific information and offer to escalate or have "
    "a human follow up — never invent. Never expose your inner workings to the caller: do not say "
    "\"knowledge base\", \"the passages\", \"the tool\", \"search\", or \"my documents\" — just "
    "speak naturally as a support agent would."
)


@dataclass(slots=True)
class AgentReply:
    """A completed (non-streaming) agent turn."""

    text: str                                          # spoken text (citations stripped)
    citations: list[str] = field(default_factory=list)
    used_rag: bool = False
    retrieved: list[ScoredChunk] = field(default_factory=list)
    details: list[Citation] = field(default_factory=list)  # per-source page/heading provenance


class ConversationAgent:
    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        *,
        system_prompt: str,
        min_confidence: float = 0.0,
        fallback_message: str | None = None,
        max_history: int = 20,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._system_prompt = f"{system_prompt}\n\n{_AGENT_BEHAVIOR}"
        self._min_confidence = min_confidence  # grounding gate on retrieved chunks
        self._fallback = (fallback_message or "").strip() or refusal_message()
        self._max_history = max_history

    # --- message assembly --------------------------------------------------
    def _messages(self, state: ConversationState, state_note: str) -> list[Message]:
        system = self._system_prompt
        if state_note:
            system = f"{system}\n\nMemory of this call:\n{state_note}"
        msgs = [Message(Role.SYSTEM, system)]
        for turn in state.transcript[-self._max_history :]:
            text = turn.get("text")
            if not text:
                continue
            role = Role.USER if turn.get("role") == "user" else Role.ASSISTANT
            msgs.append(Message(role, str(text)))
        return msgs

    @staticmethod
    def _format(chunks: list[ScoredChunk]) -> str:
        if not chunks:
            return "No relevant information was found in the knowledge base."
        return "\n\n".join(f"[{c.chunk.source}] {c.chunk.text}" for c in chunks)

    @staticmethod
    def _last_user(state: ConversationState) -> str:
        return next(
            (t["text"] for t in reversed(state.transcript) if t.get("role") == "user"), ""
        )

    async def _search(self, query: str) -> list[ScoredChunk]:
        chunks = await asyncio.to_thread(self._retriever.retrieve, query)
        confident = [c for c in chunks if is_grounded(c.score, self._min_confidence)]
        log.info(
            "agent search query=%r -> %d chunks (%d confident)",
            query, len(chunks), len(confident),
        )
        return confident

    async def _run_tools(self, messages: list[Message], response, last_user: str):
        """Append the model's tool call + the retrieved passages to ``messages`` in place."""
        messages.append(Message(Role.ASSISTANT, response.text, tool_calls=response.tool_calls))
        retrieved: list[ScoredChunk] = []
        for call in response.tool_calls:
            query = str(call.arguments.get("query") or last_user)
            confident = await self._search(query)
            retrieved.extend(confident)
            messages.append(
                Message(Role.TOOL, self._format(confident), tool_call_id=call.id, name=call.name)
            )
        latency.observe(confident_chunks_count=len(retrieved))
        return retrieved

    # --- public API --------------------------------------------------------
    async def respond(self, state: ConversationState, *, state_note: str = "") -> AgentReply:
        """One non-streaming turn: the model answers directly, or searches then answers."""
        messages = self._messages(state, state_note)
        last_user = self._last_user(state)
        with latency.span("llm_total_ms"):
            response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
        if not response.tool_calls:  # answered from the conversation — no retrieval
            return AgentReply(text=strip_citations(response.text) or self._fallback, used_rag=False)

        retrieved = await self._run_tools(messages, response, last_user)
        with latency.span("llm_total_ms"):
            final = await self._llm.chat(messages)
        details = build_citations(final.text, retrieved)
        return AgentReply(
            text=strip_citations(final.text) or self._fallback,
            citations=[c.source for c in details],
            used_rag=True,
            retrieved=retrieved,
            details=details,
        )

    async def begin_stream(
        self, state: ConversationState, *, state_note: str = ""
    ) -> tuple[bool, AsyncIterator[str]]:
        """Decide (with the tool available), then return ``(used_rag, raw-text stream)``.

        ``used_rag`` is known after the single decision call, so the live caller can cover a
        grounded turn with a filler. The stream yields raw deltas (with ``[source]`` markers);
        citation stripping happens downstream per sentence.
        """
        messages = self._messages(state, state_note)
        last_user = self._last_user(state)
        with latency.span("llm_total_ms"):
            response = await self._llm.chat(messages, tools=[SEARCH_TOOL])
        if not response.tool_calls:  # direct answer (follow-up / memory / off-topic / repair)
            return False, self._yield_text(response.text or self._fallback)

        await self._run_tools(messages, response, last_user)
        return True, self._stream_final(messages)

    async def _yield_text(self, text: str) -> AsyncIterator[str]:
        text = (text or "").strip()
        if text:
            yield text

    async def _stream_final(self, messages: list[Message]) -> AsyncIterator[str]:
        start = time.perf_counter()
        first = True
        async for delta in self._llm.chat_stream(messages):
            if first:
                latency.observe(llm_ttft_ms=(time.perf_counter() - start) * 1000.0)
                first = False
            yield delta
