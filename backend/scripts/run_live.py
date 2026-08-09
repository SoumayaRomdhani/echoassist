"""Talk to the EchoAssist agent live through your microphone (Sprint 8).

Two modes, both driven by a real microphone + speakers instead of replayed WAVs —
the file source/sink is swapped for :class:`LocalAudioTransport` and nothing in the
pipeline changes (ARCHITECTURE.md §2, §4):

    python scripts/run_live.py                 # free conversation (STT -> LLM -> TTS)
    python scripts/run_live.py --interview     # the full structured screening interview
    python scripts/run_live.py --job-posting-id 3   # tailored interview from a job posting (JD)
    python scripts/run_live.py --lang en       # pin the STT language (avoids mis-detection)
    python scripts/run_live.py --rate 48000    # if your mic rejects 16 kHz
    python scripts/run_live.py --device "USB"  # pick an input device by name/index

Speak after each "listening…" prompt; pause when you're done and the agent replies.
Talk over the agent to cut it off (barge-in). Press Ctrl-C to hang up.
Headphones REQUIRED — there is no echo cancellation, so on open speakers the mic
hears the agent and trips a false barge-in.

Modes:
  • default        — a plain conversational loop. Needs no Qdrant/Redis/Postgres;
                     good for validating the live transport quickly.
  • --interview    — the real screening flow (YAML states, slot filling, RAG-grounded
                     answers with citations, then notes + summary persisted to
                     Postgres). Needs Qdrant + Redis + Postgres up and the domain
                     ingested (docker compose up -d qdrant redis postgres; ingest_docs).

Compliance: both modes speak the AI disclosure, capture spoken consent, and persist
the immutable consent audit (disclosure_hash) before the interview proceeds.

The live-session body (disclosure→consent→conversation/interview) is the shared,
transport-agnostic ``src.telephony.live_session`` — the same code runs over a real
phone number in ``scripts/run_livekit.py``; only the Transport differs.

Honesty note: on CPU (this machine's default) a turn takes ~15-30 s, STT-dominated;
the goal here is the live chain, not latency. Sub-second turns need a GPU or cloud
STT/TTS (a config-only provider swap — STT_PROVIDER=deepgram / TTS_PROVIDER=cartesia).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from uuid import uuid4

from config.settings import get_settings
from src.console import FAIL, bold, dim, init_console
from src.log import setup_logging
from src.providers.errors import ProviderError
from src.runtime import use_selector_event_loop
from src.telephony.events import NULL_SINK, RedisCallEventSink, build_redis_event_sink
from src.telephony.live_session import run_live_session
from src.telephony.local_audio import LocalAudioTransport

log = logging.getLogger("echoassist.live")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Talk to the EchoAssist agent live via microphone."
    )
    parser.add_argument(
        "--interview", action="store_true",
        help="Run the full structured screening interview (needs Qdrant + Redis + Postgres).",
    )
    parser.add_argument(
        "--job-posting-id", type=int, default=None,
        help="Run a tailored interview from this CONFIRMED job posting id (implies --interview): "
             "the agent asks the questions generated from that job description. Create and "
             "confirm the posting in the dashboard's Interviews tab first.",
    )
    parser.add_argument(
        "--rate", type=int, default=16000,
        help="Microphone capture sample rate (try 48000 if 16000 is rejected).",
    )
    parser.add_argument(
        "--device", default=None,
        help="Input device index or name substring (default: system default).",
    )
    parser.add_argument(
        "--lang", default=None,
        help="Pin the STT language, e.g. 'en' or 'fr' (default: WHISPER_LANGUAGE / auto-detect). "
             "Pinning avoids whisper mis-detecting the language on short utterances.",
    )
    parser.add_argument(
        "--broadcast", action="store_true",
        help="Stream this call to the dashboard live (via Redis). Needs Redis + the API "
             "server up; the call appears under Calls and in the live banner. Terminal "
             "output is unchanged.",
    )
    parser.add_argument(
        "--remote-rag", action="store_true",
        help="Reuse a running API server's WARM RAG stack over HTTP instead of loading the "
             "embedder + reranker (~30 s) in this process. Removes the cold load — and the "
             "post-disclosure CPU contention that made the first 'yes' hard to hear — from the "
             "mic. Needs the API up (RAG_SERVICE_URL, default http://localhost:8000). "
             "Interview mode only (a free conversation uses no RAG).",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    if args.lang:  # pin the STT language for this run (overrides WHISPER_LANGUAGE)
        settings = settings.model_copy(update={"whisper_language": args.lang})
    init_console()
    setup_logging(settings.log_level)

    device: int | str | None = args.device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    transport = LocalAudioTransport(sample_rate=args.rate, input_device=device)
    try:
        await transport.start()
    except Exception as exc:  # noqa: BLE001 — no mic / unsupported rate is a clean exit, not a crash
        raise SystemExit(
            f"{FAIL} Could not open the microphone ({exc}).\n"
            "Check your input device, or pass --rate 48000 / --device <name>."
        ) from exc

    # --broadcast streams the call to the dashboard; otherwise the sink is a no-op and
    # this is exactly the terminal-only run it always was.
    call_id: str | None = None
    sink = NULL_SINK
    if args.broadcast:
        call_id = uuid4().hex
        sink = build_redis_event_sink(settings, call_id)
        print(bold("\nBroadcasting to the dashboard.") + dim(f"  call id={call_id}"))
        print(dim("Open EchoAssist → Calls: it appears live at the top (and in the banner)."))

    # A job posting only makes sense for the structured interview, so it implies --interview.
    interview = args.interview or args.job_posting_id is not None

    # --remote-rag: skip loading this process's own embedder + reranker and reuse the API's
    # warm, resident RAG stack over HTTP. The mic then starts instantly and the disclosure is
    # no longer followed by a ~30 s local model load contending with the first "yes".
    retriever = None
    if args.remote_rag and interview:
        from src.rag.remote import RemoteRetriever

        retriever = RemoteRetriever(settings.rag_service_url, settings.domain)
        print(bold("\nUsing the API's warm RAG stack.") + dim(f"  {settings.rag_service_url}"))

    try:
        await run_live_session(
            transport, settings, interview=interview, sink=sink, call_id=call_id,
            job_posting_id=args.job_posting_id, retriever=retriever,
        )
    finally:
        await transport.aclose()
        if isinstance(sink, RedisCallEventSink):
            await sink.aclose()


if __name__ == "__main__":
    use_selector_event_loop()  # Selector loop: psycopg async (consent log / finalize) on Windows
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + dim("Hung up."))
    except ValueError as exc:  # e.g. unknown / unconfirmed job posting id
        raise SystemExit(f"{FAIL} {exc}") from exc
    except ProviderError as exc:
        raise SystemExit(f"{FAIL} {exc}") from exc
