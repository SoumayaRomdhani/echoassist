"""Conversation state + in-memory store."""

from __future__ import annotations

import pytest

from src.agent.state import ConversationState, InMemoryStateStore


def test_state_json_roundtrip() -> None:
    state = ConversationState(call_id="abc", state_index=2)
    state.slots["years_experience"] = "6"
    state.add_turn("assistant", "Hi")
    state.add_turn("user", "Hello")
    state.query_history.append("is it remote?")

    restored = ConversationState.from_json(state.to_json())
    assert restored == state
    assert restored.slots == {"years_experience": "6"}
    assert restored.transcript[-1] == {"role": "user", "text": "Hello"}


@pytest.mark.asyncio
async def test_in_memory_store_load_save() -> None:
    store = InMemoryStateStore()
    assert await store.load("missing") is None

    state = ConversationState(call_id="c1", state_index=3)
    await store.save(state)
    loaded = await store.load("c1")
    assert loaded is not None
    assert loaded.state_index == 3
    assert loaded is not state  # round-tripped through serialization
