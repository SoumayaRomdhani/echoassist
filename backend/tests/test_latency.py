"""Optional per-turn latency recorder: a no-op when off, JSONL + fields when on."""

from __future__ import annotations

import json

from src.observability import latency


def test_disabled_by_default_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LATENCY_LOGGING", raising=False)
    monkeypatch.setattr(latency, "_run_path", None)

    with latency.record_turn(tmp_path, turn_id=1) as rec:
        assert rec is None                       # nothing to record
        with latency.span("stt_ms"):             # no current recorder -> no-op
            pass
        latency.event("stt_done")
        latency.observe(intent="answer")
        assert latency.current() is None

    assert not (tmp_path / "latency_runs").exists()   # no file written when off


def test_enabled_records_spans_events_and_writes_one_jsonl_row(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LATENCY_LOGGING", "true")
    monkeypatch.setattr(latency, "_run_path", None)

    with latency.record_turn(tmp_path, turn_id=1, reranker_provider="voyage") as rec:
        assert rec is not None
        with latency.span("stt_ms"):
            pass
        latency.event("stt_done")
        latency.observe(intent="question", is_rag=True, retrieved_chunks_count=6)
        with latency.span("stt_ms"):             # a second span accumulates into the same field
            pass
        latency.event("first_audio")

    files = list((tmp_path / "latency_runs").glob("*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1

    row = rows[0]
    assert row["turn_id"] == 1
    assert row["reranker_provider"] == "voyage"
    assert row["intent"] == "question" and row["is_rag"] is True
    assert row["retrieved_chunks_count"] == 6
    assert isinstance(row["stt_ms"], (int, float)) and row["stt_ms"] >= 0.0
    assert "total_turn_ms" in row
    assert "ttfa_ms" in row                        # derived from stt_done + first_audio events


def test_context_var_is_cleared_after_the_turn(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LATENCY_LOGGING", "true")
    monkeypatch.setattr(latency, "_run_path", None)

    with latency.record_turn(tmp_path, turn_id=1):
        assert latency.current() is not None
    assert latency.current() is None
