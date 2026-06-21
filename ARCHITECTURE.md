# EchoAssist — Architecture & Tech Stack (build spec)

> Build specification for an AI coding agent. EchoAssist is an **autonomous voice agent** delivered as a **new agent inside the ACTEEK Agent Marketplace**. Build it **provider-agnostic** (STT/LLM/TTS swappable behind interfaces), **open-source by default**, and **multi-domain** (one engine, domains = config). Paid APIs are drop-in alternatives selected by configuration only.

## 1. What we are building

An autonomous voice agent that conducts structured, interview-style phone conversations, grounds its answers in documentation (RAG), captures structured notes, and produces post-call summaries. It is exposed as an agent card in ACTEEK's existing marketplace (alongside CRM Agent, Legal Agent, PDF Agent). Two surfaces:

- **Caller surface (no screen):** a real phone number. The agent answers, runs the interview, speaks back. This is the voice engine.
- **Supervisor surface (dashboard):** a React view inside the ACTEEK shell where a human (recruiter / ops) configures the agent and reads call results (transcript, notes, summary, metrics).

**Primary vertical for v1: talent acquisition / candidate screening.** It is bounded, structured, low hallucination risk.

## 2. Core principles (do not violate)

- **Provider-agnostic.** No vendor SDK is called from business logic. All STT/LLM/TTS access goes through `src/providers/*/base.py`. Switching provider = changing an env var.
- **Open-source default, paid swappable.** Ship open-source; paid providers are alternate implementations of the same interfaces.
- **Multi-domain engine.** The code is domain-agnostic. A "domain" = a set of knowledge-base documents + an interview flow file (`config/interview_flows/{domain}.yaml`). Adding HR / helpdesk / credit-transfer later = new config, not new code.
- **Dev uses replayed audio.** No live telephony until the final sprint. A replay harness streams audio files into the pipeline. Telephony (LiveKit + SIP) is integrated only at delivery.
- **Quality lives in the RAG**, not the model badge. Invest in chunking, retrieval, grounding.
- **Compliance is mandatory.** AI disclosure at call start, recording consent, logged interaction record.
- **Don't rebuild ACTEEK auth.** SSO (Microsoft/Google/GitHub) belongs to their platform; integrate, don't reimplement.

## 3. Multi-domain engine

One engine, many domains. Per domain you provide:
- documents in `data/docs/{domain}/` (indexed into a per-domain Qdrant collection),
- an interview flow in `config/interview_flows/{domain}.yaml` (ordered states, questions, slots),
- a notes schema in `config/schemas/{domain}.json` (structured fields to extract).

`DOMAIN=screening` selects the active domain. Future domains: `hr`, `helpdesk`, `credit_transfer`.

## 4. System architecture (three tiers)

```
TIER 1 — Voice engine (Python, Pipecat)
  Caller → Transport (SIP/WebRTC | replay harness in dev)
        → STT [provider] → Conversation state (Redis)
        → Dialogue manager (interview flow)
              ├─ RAG tool (hybrid retrieve + rerank) ← Qdrant (per-domain)
              └─ Notes extractor (structured output)  → Postgres
        → LLM [provider] → TTS [provider] → Transport → Caller
  End of call → Summary generator → Postgres

TIER 2 — Backend API (FastAPI)
  REST: campaigns, domains, calls, notes, summaries, doc upload (triggers RAG ingest)
  WebSocket: live call status / live transcript to the dashboard
  Persistence: Postgres; cache/state: Redis; vectors: Qdrant

TIER 3 — Frontend dashboard (React, inside ACTEEK Marketplace)
  Agent card → agent detail view: call list, call detail (transcript/notes/summary),
  metrics, config (upload docs, pick interview flow)
```

Offline pipeline (not in hot path): documents → chunk → embed (BGE-M3) → index (Qdrant). Batch script; never embed during a call.

## 5. Provider abstraction (the heart of the design)

```
src/providers/
  stt/  base.py  whisper_local.py(default)  deepgram.py(paid)
  llm/  base.py  ollama_local.py(default)   gemini.py(easy free dev)  claude.py(paid)
  tts/  base.py  kokoro_local.py(default)   cartesia.py(paid)  elevenlabs.py(paid)
```

Interfaces:
- `STTProvider.transcribe_stream(audio_chunks) -> AsyncIterator[Transcript]`
- `LLMProvider.chat(messages, tools=None) -> LLMResponse`  (text + tool_calls)
- `TTSProvider.synthesize_stream(text) -> AsyncIterator[AudioChunk]`

Factory in `config/settings.py` reads env and returns the chosen implementation:
```
STT_PROVIDER = whisper_local | deepgram          # default: whisper_local
LLM_PROVIDER = ollama | gemini | claude          # default: ollama (gemini for easiest dev start)
TTS_PROVIDER = kokoro | cartesia | elevenlabs    # default: kokoro
DOMAIN       = screening | hr | helpdesk | credit_transfer   # default: screening
```

## 6. Tech stack

### Voice / AI core
| Layer | Open-source default | Paid swap | Role |
|---|---|---|---|
| Orchestration | Pipecat | — | Voice pipeline, turn-taking, interruption |
| Transport / telephony | LiveKit (self-host) + SIP (Twilio) | Twilio Media Streams | PSTN ↔ pipeline (sprint 8) |
| STT | faster-whisper (large-v3) | Deepgram Nova-3 | Speech→text, FR/EN |
| LLM | Ollama + Qwen3 / Mistral Small | Gemini / Claude / GPT | Dialogue + tool calling |
| Embeddings | BGE-M3 (dense+sparse) | Cohere / Voyage | Hybrid retrieval, multilingual |
| Vector DB | Qdrant | Pinecone | Per-domain chunk search |
| Reranker | bge-reranker-v2-m3 | Cohere Rerank | Reorder candidates |
| TTS | Kokoro | Cartesia / ElevenLabs | Text→speech, streaming |

### Backend
| Item | Choice |
|---|---|
| API framework | FastAPI (REST + WebSocket) |
| Async runtime | asyncio / uvicorn |
| State | Redis |
| Persistence | Postgres (SQLAlchemy / psycopg) |
| Structured output | LLM function calling / JSON schema |
| Observability | OpenTelemetry + Grafana/Tempo |

### Frontend (must match ACTEEK design system)
| Item | Choice |
|---|---|
| Framework | React + Vite + TypeScript |
| Styling | Tailwind CSS mapped to ACTEEK `--c-*` tokens |
| Components | shadcn/ui (Radix + Tailwind) |
| Data | TanStack Query (REST) + native WebSocket (live) |
| Fonts | Space Grotesk (headings/UI), Manrope (body) |
| Theme | dark-mode first, light optional (toggle) |
| Auth | integrate ACTEEK SSO — do not rebuild |

License note: delivery uses Apache-2.0 / MIT components only. Avoid non-commercial models (e.g. XTTS-v2). Qwen3, Mistral, BGE-M3, Qdrant, Kokoro, Pipecat, LiveKit are commercial-safe; verify per component.

## 7. Repository structure (monorepo)

```
echoassist/
  docker-compose.yml            # Qdrant + Redis + Postgres
  backend/
    pyproject.toml
    .env.example
    config/
      settings.py               # env loading + provider factory
      interview_flows/{domain}.yaml
      schemas/{domain}.json
    src/
      providers/                # STT / LLM / TTS interfaces + impls
      rag/        ingest.py  embeddings.py  retriever.py
      agent/      orchestrator.py  dialogue.py  state.py  notes.py  summary.py  guardrails.py
      telephony/  livekit_transport.py        # sprint 8
      api/        app.py  routes/  ws.py       # FastAPI
      storage/    db.py  models.py
      observability/ tracing.py
      eval/       retrieval_eval.py  latency_eval.py  transcription_eval.py
    scripts/      replay_audio.py  telephonize.py  gen_test_dialogues.py
    data/         docs/{domain}/  test_audio/
  frontend/
    package.json  vite.config.ts  tailwind.config.ts
    src/
      styles/tokens.css         # ACTEEK design tokens (provided)
      lib/api.ts  lib/ws.ts
      pages/  AgentCard.tsx  AgentDashboard.tsx
      components/ CallList.tsx  CallDetail.tsx  Metrics.tsx  DomainConfig.tsx
```

## 8. Design system (ACTEEK)

- Tokens: use `frontend/src/styles/tokens.css` (provided) — light + dark `--c-*` variables.
- Fonts: Space Grotesk (headings/UI), Manrope (body) — load from Google Fonts.
- Theme: dark-mode first; neon cyan + purple accents on deep dark surfaces.
- Imagery rule: no bright generic stock; use dark dashboards, data viz, audio waveforms, tech/network motifs.
- Tone: "pragmatic visionary" — direct, results-oriented microcopy.

## 9. Turn lifecycle (target < 800 ms/turn)

STT final (~200–300 ms) → state update (sub-ms) → dialogue decision → optional RAG (retrieve ~30–100 ms ∥ rerank ~50–200 ms) → LLM streamed first token (~200–500 ms) → TTS first audio (~150 ms). Notes extraction runs off the response path. Measure p50/p95 per stage; parallelize retrieval; never block on notes.

## 10. Compliance & production

AI disclosure spoken at call start; recording consent captured + logged before storage; interaction record persisted; PII redaction before persistence; provider failover (never silent); grounding guardrail (refuse when retrieval confidence low).

## 11. Delivery handoff (before client delivery)

No developer keys/credits remain. Provide two run modes via the same env vars: self-host (open-source on client GPU) or hosted (client's own API keys). Ship a per-minute cost model on the client's volume + open-vs-hosted break-even, and "path to scale" (multi-tenant, new domains as config).
