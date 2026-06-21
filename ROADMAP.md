# EchoAssist — Roadmap (8 sprints, build plan)

> Companion to `ARCHITECTURE.md`. Each sprint = 1 week, ends with a demonstrable Definition of Done (DoD). Build provider-agnostic and domain-config-driven from sprint 1. Use replayed audio in development; integrate real telephony only in sprint 8. The voice engine is the core (sprints 1–5); backend API and frontend dashboard are timeboxed to sprints 6–7; never let the dashboard eat voice-engine time.

## Prerequisites & setup

Backend:
- Python 3.11+, `uv`/`venv`.
- Docker + `docker-compose.yml`: Qdrant, Redis, Postgres.
- Ollama with an open model: `ollama pull qwen3` (or `mistral-small`). Easiest start: set `LLM_PROVIDER=gemini` (free tier) to skip local GPU early, switch to `ollama` later with no code change.
- Deps: pipecat-ai, faster-whisper, ollama (or google-genai / anthropic), FlagEmbedding, qdrant-client, kokoro, redis, psycopg[binary], pyyaml, fastapi, uvicorn, opentelemetry-sdk; ffmpeg (system); livekit + livekit-agents (sprint 8).

Frontend (sprint 7):
- Node 20+, pnpm.
- React + Vite + TypeScript, Tailwind, shadcn/ui, @tanstack/react-query.
- Fonts: Space Grotesk + Manrope (Google Fonts). Tokens: `frontend/src/styles/tokens.css` (provided).

Create `backend/.env.example` with the provider + DOMAIN vars from `ARCHITECTURE.md` §5.

---

## Sprint 1 — Skeleton & speaking loop
Goal: an audio file goes in, a spoken reply comes out, fully local, zero cost.
- Scaffold `backend/` per `ARCHITECTURE.md` §7.
- Implement the three provider interfaces + one impl each: whisper_local, ollama (or gemini), kokoro.
- `config/settings.py` provider+domain factory (env-driven).
- `scripts/replay_audio.py` (stream a WAV as if live) and `scripts/telephonize.py` (ffmpeg: 8 kHz, band-pass 300–3400 Hz, µ-law).
- Minimal Pipecat pipeline `agent/orchestrator.py`: STT → LLM → TTS, with a spoken AI-disclosure line at start.
DoD: `replay_audio.py sample.wav` → agent transcribes, responds, and **speaks** the reply on your machine.

## Sprint 2 — RAG core
Goal: grounded answers with citations.
- `rag/embeddings.py` (BGE-M3 dense+sparse); `rag/ingest.py` (load `data/docs/{domain}/`, chunk, embed, index per-domain Qdrant collection).
- `rag/retriever.py`: hybrid search + RRF (k=60) + rerank (bge-reranker-v2-m3) → top 5–8.
- Expose retrieval as an LLM tool (function calling).
- `eval/retrieval_eval.py`: Recall@K, nDCG.
DoD: the agent answers a domain question by retrieving and citing the correct document.

## Sprint 3 — Interview flow (screening, domain-config-driven)
Goal: the agent leads a complete structured interview.
- `config/interview_flows/screening.yaml`: states (greeting → disclosure/consent → structured questions w/ slots → grounded Q&A → close).
- `agent/dialogue.py`: state machine reading the YAML; per turn decides ask-next vs answer-via-RAG; slot filling.
- `agent/state.py`: Redis state (rolling transcript, slots, intent, query history).
- Turn-taking / barge-in via Pipecat.
DoD: a full screening interview runs end-to-end from replayed audio; agent stays on track.

## Sprint 4 — Structured notes & summary + data layer
Goal: reliable structured output, persisted.
- `config/schemas/screening.json`; `agent/notes.py` extracts fields during the call (function calling).
- `agent/summary.py`: grounded post-call summary.
- `storage/db.py` + `models.py`: Postgres models (campaigns, calls, transcripts, notes, summaries); persist.
- Validate against ground truth from `gen_test_dialogues.py`.
DoD: after a call, accurate notes + faithful summary exist in Postgres.

## Sprint 5 — Latency & quality hardening
Goal: natural turns under threshold, no hallucinations.
- `eval/latency_eval.py`: p50/p95 per stage; optimize toward < 800 ms/turn (streaming, parallel retrieval, connection reuse).
- Tune endpointing/interruption.
- `agent/guardrails.py`: grounding check + low-confidence refusal + PII redaction.
- `eval/transcription_eval.py`: WER on telephonized audio.
DoD: turn latency meets target; agent never answers outside retrieved context.

## Sprint 6 — Backend API + observability
Goal: deployable, observable, API-exposed.
- `api/app.py` + `routes/`: REST for campaigns, domains, calls, notes, summaries, doc upload (triggers RAG ingest).
- `api/ws.py`: WebSocket for live call status + live transcript.
- `observability/tracing.py`: OpenTelemetry spans per stage → Grafana/Tempo.
- Graceful degradation (provider failover); consent capture + logging; containerize; concurrency test.
DoD: API serves call data and live updates; system is traced, compliant, survives N concurrent sessions.

## Sprint 7 — Frontend dashboard (ACTEEK) + benchmark
Goal: a thin, on-brand dashboard + a quantified benchmark.
- Frontend: React+Vite+TS+Tailwind+shadcn/ui, tokens.css + Space Grotesk/Manrope, dark-mode first.
- EchoAssist as a marketplace agent card → agent detail view: `CallList`, `CallDetail` (transcript/notes/summary), `Metrics`, `DomainConfig` (upload docs, pick flow). Wire to REST (TanStack Query) + WebSocket (live).
- Integrate ACTEEK SSO (do not rebuild auth).
- Benchmark: record latency percentiles, STT WER, retrieval Recall@K/nDCG, note accuracy, summary faithfulness, completion/containment; A/B provider swaps; recalibrate cost-model assumptions on real measured calls.
DoD: a recruiter can run/inspect a screening campaign in the ACTEEK-styled dashboard; a reproducible benchmark report exists.

## Sprint 8 — Telephony, delivery & provider handoff
Goal: live demo + cost-safe delivery.
- `telephony/livekit_transport.py`: LiveKit + SIP (Twilio) on a real number; replace the replay harness with live transport.
- Polish a live screening demo (script + backup recording).
- Provider handoff: remove all developer keys; document self-host vs hosted run modes (same env vars).
- Package: ops docs, per-minute cost model on client volume, open-vs-hosted break-even, path to scale (new domains as `interview_flows/*.yaml`).
DoD: a prospect could run a real pilot on their own keys/infra, nothing billing to developer accounts.

---

## Scope guardrails
- One vertical only (screening). Others (hr, helpdesk, credit_transfer) are future config files, not code.
- Frontend is thin and timeboxed to sprint 7 — voice engine quality comes first.
- Test audio is synthetic + telephonized; validating on real anonymized calls is future work.
- If a sprint overruns, ship its DoD slice before moving on — every sprint leaves something demonstrable.
- How to drive Claude Code: feed it ARCHITECTURE.md + ROADMAP.md, then implement one sprint at a time ("implement Sprint 1 per the specs"), validating each DoD before the next.
