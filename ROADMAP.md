# EchoAssist -- Roadmap

Companion to `ARCHITECTURE.md`. The system is built provider-agnostic and
domain-config-driven from the start. Development runs on replayed audio; real
telephony is the final step. The voice engine is the core; the backend API and
frontend dashboard are deliberately kept thin so they never crowd out voice-engine
quality. Each milestone below ends with something demonstrable.

## Prerequisites

**Backend:** Python 3.11+ (`uv`/`venv`); Docker with `docker-compose.yml` for
Qdrant, Redis, and Postgres; Ollama with an open model (`ollama pull qwen3`), or
set `LLM_PROVIDER=gemini` (free tier) to skip local GPU early and switch to Ollama
later with no code change. Key deps: pipecat-ai, faster-whisper, ollama /
google-genai / anthropic, FlagEmbedding, qdrant-client, kokoro, redis,
psycopg[binary], pyyaml, fastapi, uvicorn, opentelemetry-sdk, ffmpeg (system), and
livekit + livekit-agents for telephony.

**Frontend:** Node 20+, pnpm; React + Vite + TypeScript, Tailwind, shadcn/ui,
@tanstack/react-query; Space Grotesk + Manrope fonts; tokens in
`frontend/src/styles/tokens.css`.

Create `backend/.env.example` with the provider and `DOMAIN` variables from
`ARCHITECTURE.md` section 5.

## Milestones

**Skeleton and speaking loop.** Scaffold the backend and the three provider
interfaces (whisper_local, ollama/gemini, kokoro) behind an env-driven factory.
Replay and telephonize scripts feed a minimal STT -> LLM -> TTS pipeline that opens
with a spoken AI disclosure. *Done when* a WAV goes in and a spoken reply comes out,
fully local.

**RAG core.** Per-domain Qdrant ingest (chunk, embed, index); hybrid retrieval with
RRF fusion and cross-encoder rerank; retrieval exposed as an LLM tool; Recall@K /
nDCG eval. *Done when* the agent answers a domain question by retrieving and citing
the correct document.

**Structured interview.** A domain-config state machine (`screening.yaml`) drives
greeting -> disclosure/consent -> slot-filling questions -> grounded Q&A -> close,
deciding each turn between ask-next and answer-via-RAG, with conversation state in
Redis. *Done when* a full interview runs end-to-end from replayed audio.

**Notes, summary, and persistence.** Field extraction via function calling against a
JSON schema; a grounded post-call summary; Postgres models and persistence for
campaigns, calls, transcripts, notes, and summaries; validation against ground
truth. *Done when* accurate notes and a faithful summary land in Postgres after a
call.

**Latency and quality hardening.** Per-stage p50/p95 latency eval and tuning; a
grounding gate with low-confidence refusal and PII redaction; WER on telephonized
audio. *Done when* the agent never answers outside retrieved context and per-stage
cost is measured.

**Backend API and observability.** REST for campaigns, domains, calls, notes,
summaries, and document upload; a WebSocket for live status and transcript;
OpenTelemetry tracing; provider failover; consent capture and logging; containers;
concurrency testing. *Done when* the API serves call data and live updates and
survives concurrent sessions.

**Frontend dashboard.** An on-brand ACTEEK dashboard (React/Vite/TS/Tailwind) with
an agent detail view: call list, call detail (transcript/notes/summary), metrics,
and domain config, wired to REST and the WebSocket, with ACTEEK SSO integrated
rather than rebuilt. *Done when* a recruiter can run and inspect a screening
campaign in the dashboard.

**Telephony and delivery.** LiveKit + SIP on a real number replacing the replay
harness; a polished live demo; provider handoff (no developer keys); ops docs and a
per-minute cost model. *Done when* a prospect could run a real pilot on their own
keys and infrastructure.

## Open follow-ups

- A reproducible **benchmark report**: latency percentiles, STT WER, retrieval
  Recall@K/nDCG, note accuracy, summary faithfulness, completion/containment, and
  A/B provider swaps on real measured calls.

## Scope guardrails

- Verticals are added as configuration, not code (screening and helpdesk exist;
  hr and credit_transfer are future config files).
- The frontend stays thin -- voice-engine quality comes first.
- Test audio is synthetic and telephonized; validating on real anonymized calls is
  future work.
- Ship each milestone's demonstrable slice before moving on.
