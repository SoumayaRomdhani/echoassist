# EchoAssist

Provider-agnostic, multi-domain **autonomous voice agent** for the ACTEEK Agent
Marketplace. It runs structured, interview-style phone conversations, grounds
answers in documentation (RAG), captures structured notes, and produces
post-call summaries.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`ROADMAP.md`](ROADMAP.md) for the full spec.

> **Core principle:** no vendor SDK is called from business logic. All STT/LLM/TTS
> access goes through `backend/src/providers/*/base.py`. Switching a provider is a
> one-line change in `backend/.env`.

---

## Status — Sprint 1 ✅ Skeleton & speaking loop

An audio file goes in, a spoken reply comes out, fully local-capable, zero cost.

- Provider abstraction (STT / LLM / TTS): faster-whisper, Ollama (default) +
  Gemini, Kokoro.
- Env-driven provider + domain factory (`config/settings.py`).
- Replay harness + telephonize (8 kHz band-pass µ-law) scripts.
- Speaking loop with a spoken **AI disclosure** at call start.

## Quick start (Sprint 1)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[sprint1]"                              # whisper + ollama + gemini + kokoro

cp .env.example .env
# Default LLM is Ollama (open-source). Two options:
#   - Ollama:  install the Ollama app, then `ollama pull qwen3`
#   - Easiest (no GPU): set LLM_PROVIDER=gemini and add a free key from
#     https://aistudio.google.com/apikey

python scripts/check_setup.py --full                     # verify everything is wired
python scripts/gen_sample_audio.py                       # make the test audio clips
python scripts/replay_audio.py                           # disclosure -> consent -> interview turn
```

**Definition of Done:** `replay_audio.py` → the agent speaks its AI disclosure,
gates on the caller's spoken **consent**, then (if granted) transcribes the
candidate's answer, responds, and **speaks** the reply on your machine.

### Switch providers (no code change)

```ini
# backend/.env
LLM_PROVIDER=ollama        # gemini | ollama | claude
TTS_PROVIDER=kokoro        # kokoro | cartesia | elevenlabs
STT_PROVIDER=whisper_local # whisper_local | deepgram
DOMAIN=screening           # screening | hr | helpdesk | credit_transfer
```

### Telephonize test audio (optional, realistic call quality)

```bash
python scripts/telephonize.py data/test_audio/sample.wav data/test_audio/sample_tel.wav
python scripts/replay_audio.py data/test_audio/sample_tel.wav
```

## Infrastructure (Sprint 2+)

```bash
docker compose up -d        # Qdrant + Redis + Postgres
```

## Repository layout

```
backend/   FastAPI + voice engine (Python)         # the core
frontend/  React dashboard (ACTEEK)                # sprint 7
docker-compose.yml                                 # Qdrant + Redis + Postgres
```
