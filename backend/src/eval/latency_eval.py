"""Per-stage latency eval (p50 / p95).

    python -m src.eval.latency_eval [--iters 5] [--with-llm]

Times each pipeline stage that runs locally — STT, retrieval (embed + hybrid
search + rerank), TTS — over N iterations and reports p50/p95/mean. The LLM
stage is optional (it costs Gemini quota). Models are warmed up once before
timing so load time is excluded.

Target is < 800 ms/turn (ARCHITECTURE.md §9) — realistic only with a GPU and
streaming. On CPU the STT stage dominates; this harness makes that measurable.
Requires Qdrant running + the domain ingested.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time

from config.settings import build_llm, build_retriever, build_stt, build_tts, get_settings
from src.audio.io import chunk_from_float, read_wav, resample
from src.console import bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.providers.types import AudioChunk, Message, Role


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..100)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _report(stage: str, samples: list[float]) -> float:
    p50, p95 = percentile(samples, 50), percentile(samples, 95)
    mean = sum(samples) / len(samples)
    print(f"  {stage:<10} p50={p50:7.0f}ms  p95={p95:7.0f}ms  mean={mean:7.0f}ms")
    return p50


async def _time(coro_factory, iters: int) -> list[float]:
    await coro_factory()  # warm-up (load model), excluded
    samples = []
    for _ in range(iters):
        start = time.perf_counter()
        await coro_factory()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def main() -> None:
    parser = argparse.ArgumentParser(description="Per-stage latency eval (p50/p95).")
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--with-llm", action="store_true", help="Also time the LLM (uses quota).")
    args = parser.parse_args()

    settings = get_settings()
    init_console()
    setup_logging(settings.log_level)

    audio_path = settings.data_dir / "test_audio" / "sample_consent.wav"
    if not audio_path.exists():
        raise SystemExit("Missing sample audio — run: python scripts/gen_sample_audio.py")
    samples, sr = read_wav(audio_path)
    chunk: AudioChunk = chunk_from_float(resample(samples, sr, 16000), 16000)

    stt, retriever, tts = build_stt(settings), build_retriever(settings), build_tts(settings)
    query = "What is the salary range for the backend role?"
    reply = "The base salary range is 65,000 to 85,000 euros per year, depending on experience."

    print(bold(f"\nLatency eval — {args.iters} iterations (after warm-up)\n"))
    p50s = {}
    p50s["stt"] = _report("STT", await _time(lambda: stt.transcribe(chunk), args.iters))
    p50s["retrieval"] = _report(
        "retrieval", await _time(lambda: asyncio.to_thread(retriever.retrieve, query), args.iters)
    )
    p50s["tts"] = _report("TTS", await _time(lambda: tts.synthesize(reply), args.iters))
    if args.with_llm:
        llm = build_llm(settings)
        p50s["llm"] = _report(
            "LLM", await _time(lambda: llm.chat([Message(Role.USER, query)]), args.iters)
        )

    total = sum(p50s.values())
    print(bold(f"\n  sum of p50s = {total:.0f} ms/turn"))
    print(dim("  (target < 800 ms/turn — realistic with a GPU + streaming, ARCHITECTURE.md §9)"))
    if total > 800:
        print(dim("  On CPU the STT stage dominates; GPU + streaming (Sprint 8) closes the gap.\n"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ProviderError as exc:
        from src.console import FAIL

        raise SystemExit(f"{FAIL} {exc}") from exc
