"""PII is masked before ANY persistence — Redis (state store) and Postgres."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from config.settings import get_settings
from src.agent.dialogue import DialogueManager, TurnDecision, TurnIntent
from src.agent.domain import DomainConfig
from src.agent.finalize import finalize_call
from src.agent.grounding import GroundedAnswer
from src.agent.state import ConversationState, InMemoryStateStore
from src.providers.llm.base import LLMProvider
from src.providers.types import LLMResponse, ToolCall
from src.storage.db import init_db, make_sessionmaker
from src.storage.models import Note, Summary, TranscriptTurn

_PII = "My email is test@example.com and my phone is +216 12 345 678."
_EMAIL = "test@example.com"
_PHONE = "+216 12 345 678"

_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_name": {"type": "string"},
        "overall_fit": {"type": "string", "enum": ["strong", "moderate", "weak", "unknown"]},
    },
    "required": ["overall_fit"],
}


class _FakeClassifier:
    async def classify(self, question: str, utterance: str) -> TurnDecision:
        return TurnDecision(TurnIntent.ANSWER, answer_value="")


class _FakeResponder:
    async def answer(self, question: str, *, search_query: str | None = None) -> GroundedAnswer:
        return GroundedAnswer(text="ok", citations=[])


class _FinalizeLLM(LLMProvider):
    async def chat(self, messages, tools=None) -> LLMResponse:
        if tools:  # notes extraction
            args = {"overall_fit": "strong", "candidate_name": f"reach me at {_EMAIL}"}
            return LLMResponse(text="", tool_calls=[ToolCall("n", "record_screening_notes", args)])
        return LLMResponse(text=f"Candidate reachable at {_EMAIL} or {_PHONE}.")  # summary w/ PII


def _domain() -> DomainConfig:
    flow = {"states": [{"id": "q", "type": "question", "slot": "answer", "prompt": "Tell me."}]}
    return DomainConfig(
        name="screening", language="en", disclosure="d", greeting="g",
        system_prompt="s", consent_reprompt="r", consent_decline="x", flow=flow,
    )


@pytest.mark.asyncio
async def test_pii_is_redacted_before_the_state_store_redis() -> None:
    store = InMemoryStateStore()  # stands in for Redis
    state = ConversationState(call_id="c1")
    mgr = DialogueManager(
        classifier=_FakeClassifier(), responder=_FakeResponder(),
        domain=_domain(), state=state, store=store, redact=True,
    )
    await mgr.start()
    await mgr.handle_turn(_PII)

    saved = store._store["c1"]  # the exact JSON persisted to the store
    assert _EMAIL not in saved and _PHONE not in saved
    assert "[redacted-email]" in saved and "[redacted-phone]" in saved
    assert _EMAIL not in str(state.slots) and _PHONE not in str(state.slots)


@pytest.mark.asyncio
async def test_pii_is_redacted_before_postgres() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    await init_db(engine)
    state = ConversationState(
        call_id="c2", consent_granted=True,
        transcript=[{"role": "user", "text": _PII}],
    )
    async with make_sessionmaker(engine)() as session:
        result = await finalize_call(
            session, state, llm=_FinalizeLLM(), schema=_SCHEMA,
            campaign_name="Camp", domain="screening", redact=True,
        )

    blob = f"{result.notes} || {result.summary}"
    assert _EMAIL not in blob and _PHONE not in blob
    async with make_sessionmaker(engine)() as session:
        note = await session.scalar(select(Note))
        summary = await session.scalar(select(Summary))
        turns = (await session.scalars(select(TranscriptTurn))).all()
        for text in (str(note.data), summary.text, *[t.text for t in turns]):
            assert _EMAIL not in text and _PHONE not in text
        assert any("[redacted-email]" in t.text for t in turns)
    await engine.dispose()


@pytest.mark.asyncio
async def test_pii_redacted_in_real_redis_server() -> None:
    """Integration test against the real Redis server (skips if it isn't running).

    The in-memory tests above cover the same serialization; this verifies the
    actual Redis backend stores no raw PII.
    """
    redis = pytest.importorskip("redis")
    from src.agent.state import RedisStateStore

    settings = get_settings()
    try:
        redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
    except Exception:  # noqa: BLE001
        pytest.skip("Redis server not reachable (docker compose up -d redis)")

    store = RedisStateStore(url=settings.redis_url, key_prefix="echoassist:pii-test:")
    call_id = "pii-" + uuid.uuid4().hex[:8]
    mgr = DialogueManager(
        classifier=_FakeClassifier(), responder=_FakeResponder(),
        domain=_domain(), state=ConversationState(call_id=call_id), store=store, redact=True,
    )
    try:
        await mgr.start()
        await mgr.handle_turn(_PII)
        loaded = await store.load(call_id)
        raw = loaded.to_json()
        assert _EMAIL not in raw and _PHONE not in raw
        assert "[redacted-email]" in raw and "[redacted-phone]" in raw
    finally:
        await store._redis.delete(f"echoassist:pii-test:{call_id}")
        await store.aclose()
