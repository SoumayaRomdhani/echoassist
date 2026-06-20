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

## Status

### Sprint 3 ✅ Interview flow — full structured screening interview
- Domain-config **state machine** (`agent/dialogue.py`) reading the YAML flow:
  ordered questions with **slot filling** → grounded Q&A → close.
- Each turn is classified (answer / question / done); the agent answers the
  caller's own questions via RAG mid-interview, then resumes.
- **Redis** conversation state (`agent/state.py`): transcript, slots, query history
  (in-memory backend for tests / no-Redis dev).

### Sprint 2 ✅ RAG core — grounded answers with citations
- Hybrid retrieval: dense + BM25 sparse (FastEmbed) → **RRF fusion (k=60)** →
  cross-encoder rerank → top-k, all provider-agnostic (BGE-M3 is an env swap).
- Per-domain **Qdrant** collection; offline ingest pipeline (chunk → embed → index).
- Retrieval exposed as an **LLM tool** (function calling, Gemini + Ollama); the
  agent answers domain questions and **cites the source document**.
- `eval/retrieval_eval.py`: Recall@K and nDCG@K over a gold set.

### Sprint 1 ✅ Skeleton & speaking loop
- Provider abstraction (STT / LLM / TTS): faster-whisper, Ollama (default) +
  Gemini, Kokoro; env-driven factory (`config/settings.py`).
- Replay harness + telephonize (8 kHz band-pass µ-law) scripts.
- Speaking loop with a spoken **AI disclosure** + explicit **consent gate** at call start.

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

## RAG — grounded answers (Sprint 2)

```bash
cd backend
pip install -e ".[rag]"                                  # fastembed + qdrant-client
docker compose -f ../docker-compose.yml up -d qdrant     # start the vector DB

python scripts/ingest_docs.py                            # index data/docs/screening/
python scripts/ask.py "What is the salary range for the backend role?"
python -m src.eval.retrieval_eval                        # Recall@K, nDCG@K
```

`ask.py` prints a grounded answer with its source citation, e.g.
*"The range is 65,000–85,000 euros [compensation_and_benefits.md]."*

## Full interview (Sprint 3)

```bash
pip install -e ".[state]"                                # redis client
docker compose -f ../docker-compose.yml up -d qdrant redis
python scripts/ingest_docs.py
python scripts/gen_sample_audio.py
python scripts/run_interview.py                          # disclosure -> consent -> interview -> close
```

The agent leads the structured interview from replayed audio, fills slots,
answers the candidate's own questions from the knowledge base, and closes —
printing the filled slots and persisting state to Redis.

## Infrastructure

```bash
docker compose up -d        # Qdrant + Redis + Postgres (Redis/Postgres used from Sprint 3+)
```

## Repository layout

```
backend/   FastAPI + voice engine (Python)         # the core
frontend/  React dashboard (ACTEEK)                # sprint 7
docker-compose.yml                                 # Qdrant + Redis + Postgres
```
