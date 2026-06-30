"""Setup doctor: verify the environment and each configured provider.

    python scripts/check_setup.py          # fast checks (deps importable, config valid)
    python scripts/check_setup.py --full   # also run a tiny TTS->STT->LLM smoke test

Exit code is non-zero if any required check fails, so it doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import shutil
import sys

from config.settings import (
    LLMProviderName,
    StateBackendName,
    STTProviderName,
    TTSProviderName,
    build_llm,
    build_stt,
    build_tts,
    get_settings,
)
from src.console import FAIL, OK, WARN, bold, dim, init_console

_failed = False


def report(status: str, label: str, detail: str = "") -> None:
    global _failed
    if status is FAIL:
        _failed = True
    print(f"  {status} {label}" + (f"  {dim(detail)}" if detail else ""))


def _installed(name: str) -> bool:
    # find_spec raises (not returns None) when a parent package is missing.
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def check_environment() -> None:
    print("\nEnvironment")
    py = sys.version_info
    ok = py >= (3, 11)
    report(OK if ok else FAIL, "Python", f"{py.major}.{py.minor}.{py.micro} (need >=3.11)")
    ffmpeg = shutil.which("ffmpeg")
    report(OK if ffmpeg else WARN, "ffmpeg", ffmpeg or "not found — needed by telephonize.py")


def check_config() -> None:
    s = get_settings()
    print("\nConfiguration")
    report(OK, "settings loaded", f"domain={s.domain}")
    report(OK, "STT provider", s.stt_provider.value)
    report(OK, "LLM provider", s.llm_provider.value)
    report(OK, "TTS provider", s.tts_provider.value)


def check_dependencies() -> None:
    s = get_settings()
    print("\nProvider dependencies")
    checks = [
        ("faster_whisper", s.stt_provider is STTProviderName.whisper_local),
        ("google.genai", s.llm_provider is LLMProviderName.gemini),
        ("ollama", s.llm_provider is LLMProviderName.ollama),
        ("groq", s.llm_provider is LLMProviderName.groq),
        ("kokoro", s.tts_provider is TTSProviderName.kokoro),
    ]
    for module, active in checks:
        installed = _installed(module)
        if active:
            report(OK if installed else FAIL, module, "installed" if installed else "MISSING")
        else:
            report(OK if installed else WARN, module, "installed" if installed else "inactive")

    if s.llm_provider is LLMProviderName.gemini and not s.gemini_api_key:
        report(FAIL, "GEMINI_API_KEY", "not set — add it to backend/.env")
    if s.llm_provider is LLMProviderName.groq and not s.groq_api_key:
        report(FAIL, "GROQ_API_KEY", "not set — add it to backend/.env")


def check_rag() -> None:
    s = get_settings()
    print("\nRAG (Sprint 2)")
    for module in ("fastembed", "qdrant_client"):
        installed = _installed(module)
        report(OK if installed else WARN, module, "installed" if installed else "not installed")

    if _installed("qdrant_client"):
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=s.qdrant_url, timeout=3, check_compatibility=False)
            collections = client.get_collections().collections
            report(OK, "Qdrant", f"{s.qdrant_url} ({len(collections)} collections)")
        except Exception:  # noqa: BLE001
            report(WARN, "Qdrant", "unreachable — run: docker compose up -d qdrant")


def check_state() -> None:
    s = get_settings()
    if s.state_backend is not StateBackendName.redis:
        return
    print("\nState (Sprint 3)")
    installed = _installed("redis")
    report(OK if installed else WARN, "redis", "installed" if installed else "not installed")
    if installed:
        try:
            import redis

            redis.from_url(s.redis_url, socket_connect_timeout=3).ping()
            report(OK, "Redis", s.redis_url)
        except Exception:  # noqa: BLE001
            report(WARN, "Redis", "unreachable — run: docker compose up -d redis")


def check_storage() -> None:
    s = get_settings()
    print("\nPersistence (Sprint 4)")
    for module in ("sqlalchemy", "psycopg"):
        installed = _installed(module)
        report(OK if installed else WARN, module, "installed" if installed else "not installed")
    if _installed("psycopg"):
        try:
            import psycopg

            dsn = s.database_url.replace("postgresql+psycopg://", "postgresql://")
            with psycopg.connect(dsn, connect_timeout=3):
                pass
            report(OK, "Postgres", s.database_url.rsplit("@", 1)[-1])
        except Exception:  # noqa: BLE001
            report(WARN, "Postgres", "unreachable — run: docker compose up -d postgres")


def check_api() -> None:
    s = get_settings()
    print("\nBackend API (Sprint 6)")
    for module, label in (("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
                          ("multipart", "python-multipart")):
        installed = _installed(module)
        report(OK if installed else WARN, label, "installed" if installed else "not installed")
    otel = _installed("opentelemetry")
    report(OK if otel else WARN, "opentelemetry",
           "installed" if otel else "not installed (tracing = no-op)")
    if s.llm_fallback_provider is not None:
        report(OK, "LLM failover",
               f"{s.llm_provider.value} -> {s.llm_fallback_provider.value}")


async def check_smoke() -> None:
    s = get_settings()
    print("\nSmoke test (loads models — first run downloads weights)")

    audio = None
    try:
        audio = await build_tts(s).synthesize("This is a setup test.")
        detail = f"{audio.duration_s:.1f}s @ {audio.fmt.sample_rate}Hz"
        report(OK if audio.data else FAIL, "TTS synthesize", detail)
    except Exception as exc:  # noqa: BLE001
        report(FAIL, "TTS synthesize", str(exc))

    if audio is not None:
        try:
            transcript = await build_stt(s).transcribe(audio)
            report(OK if transcript.text else WARN, "STT transcribe", f'"{transcript.text}"')
        except Exception as exc:  # noqa: BLE001
            report(FAIL, "STT transcribe", str(exc))

    try:
        from src.providers.types import Message, Role

        resp = await build_llm(s).chat([Message(Role.USER, "Reply with one word: ready")])
        report(OK if resp.text else FAIL, "LLM chat", f'"{resp.text}"')
    except Exception as exc:  # noqa: BLE001
        report(FAIL, "LLM chat", str(exc))


async def main() -> None:
    parser = argparse.ArgumentParser(description="EchoAssist setup doctor.")
    parser.add_argument("--full", action="store_true", help="Run a TTS->STT->LLM smoke test.")
    args = parser.parse_args()

    init_console()
    print(bold("EchoAssist — setup doctor"))
    check_environment()
    check_config()
    check_dependencies()
    check_rag()
    check_state()
    check_storage()
    check_api()
    if args.full:
        await check_smoke()

    print()
    if _failed:
        print(f"{FAIL} Some required checks failed. See above.")
        sys.exit(1)
    print(f"{OK} All required checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
