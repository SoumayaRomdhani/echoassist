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

### Sprint 5 ✅ Latency & quality hardening
- `agent/guardrails.py`: **grounding gate** (low reranker confidence → the agent
  refuses instead of answering outside the knowledge base) + **PII redaction**
  (emails/phones masked before persistence; names kept).
- `eval/latency_eval.py`: per-stage **p50/p95** (STT / retrieval / TTS / LLM).
- `eval/transcription_eval.py`: **WER** on clean vs telephonized audio.
  > On this CPU a turn is ~30 s (STT dominates); the < 800 ms target needs a GPU +
  > streaming (Sprint 8). The harness makes the per-stage cost measurable.

### Sprint 4 ✅ Structured notes & summary + Postgres
- `agent/notes.py`: structured notes via **function calling** (schema in
  `config/schemas/screening.json`; the 5 factual fields mirror the interview slots,
  the LLM enriches with strengths / concerns / overall fit).
- `agent/summary.py`: grounded post-call recruiter summary (no invention).
- `storage/`: Postgres models + async persistence (campaigns, calls, transcripts,
  notes, summaries). After a call, notes + summary are written to Postgres.

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
- **Multilingual (FR/EN) embeddings**; the spoken answer is natural prose and the
  source citation is kept in metadata (for the dashboard), not read aloud.
  > Eval on a bilingual KB (18 EN+FR queries): **Recall@1 = nDCG@1 = 1.0** — each
  > query retrieves its correct same-language document. Cross-lingual ranking
  > (a French query against English-only docs) is softer on a small KB; a stronger
  > multilingual model (e.g. BGE-M3) is an env swap if that becomes important.
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

## Notes, summary & persistence (Sprint 4)

```bash
pip install -e ".[storage]"                              # sqlalchemy + psycopg
docker compose -f ../docker-compose.yml up -d postgres   # host port 5433
python scripts/gen_test_dialogues.py                     # synthetic transcripts + ground truth
python scripts/finalize_call.py                          # extract notes + summary -> Postgres
python -m src.eval.notes_eval                            # notes field accuracy vs ground truth
```

`run_interview.py` also finalizes at the end of a real call: it extracts the
structured notes, writes the grounded summary, and persists campaign / call /
transcript / notes / summary to Postgres.

## Latency & quality evals (Sprint 5)

```bash
python -m src.eval.transcription_eval     # WER, clean vs telephonized (local, no API)
python -m src.eval.latency_eval --iters 5 # per-stage p50/p95 (local stages)
```

The grounding gate is enforced in `ask.py` / the interview: an off-topic question
(reranker confidence below `GROUNDING_MIN_CONFIDENCE`) is refused rather than
answered. PII (emails/phones) is redacted before anything is written to Postgres.

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
