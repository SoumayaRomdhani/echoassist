"""Conversation state + its store.

Holds the rolling transcript, filled slots, the interview position, and the
caller's question history for one call (ARCHITECTURE.md §4 — state in Redis).
The store is swappable: Redis by default, in-memory for tests / no-Redis dev.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

log = logging.getLogger("echoassist.agent.state")


@dataclass
class ConversationState:
    """Mutable state for a single call."""

    call_id: str
    state_index: int = 0
    consent_granted: bool = False
    slots: dict[str, str] = field(default_factory=dict)
    transcript: list[dict] = field(default_factory=list)   # {"role": ..., "text": ...}
    query_history: list[str] = field(default_factory=list)

    def add_turn(self, role: str, text: str) -> None:
        self.transcript.append({"role": role, "text": text})

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> ConversationState:
        return cls(**json.loads(raw))


class StateStore(ABC):
    @abstractmethod
    async def load(self, call_id: str) -> ConversationState | None: ...

    @abstractmethod
    async def save(self, state: ConversationState) -> None: ...

    async def aclose(self) -> None:  # noqa: B027 — optional override hook, default no-op
        """Release any held resources. Override if needed."""


class InMemoryStateStore(StateStore):
    """Process-local store (tests, single-process dev)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def load(self, call_id: str) -> ConversationState | None:
        raw = self._store.get(call_id)
        return ConversationState.from_json(raw) if raw else None

    async def save(self, state: ConversationState) -> None:
        self._store[state.call_id] = state.to_json()


class RedisStateStore(StateStore):
    """Redis-backed store. State is one JSON value per call under a key prefix."""

    def __init__(
        self, *, url: str = "redis://localhost:6379", key_prefix: str = "echoassist:call:"
    ) -> None:
        from redis import asyncio as redis_asyncio

        self._redis = redis_asyncio.from_url(url, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, call_id: str) -> str:
        return f"{self._prefix}{call_id}"

    async def load(self, call_id: str) -> ConversationState | None:
        raw = await self._redis.get(self._key(call_id))
        return ConversationState.from_json(raw) if raw else None

    async def save(self, state: ConversationState) -> None:
        await self._redis.set(self._key(state.call_id), state.to_json())

    async def aclose(self) -> None:
        await self._redis.aclose()
