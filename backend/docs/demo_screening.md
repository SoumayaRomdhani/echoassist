# EchoAssist — Live Screening Demo (runbook)

A reproducible script for a **live, local** screening-interview demo: the agent
speaks the AI disclosure, captures spoken consent, runs the structured screening
(questions + slot-filling + RAG-grounded answers with citations), supports
**barge-in**, then persists structured **notes + a summary** to Postgres — with an
immutable **consent audit trail** (`disclosure_hash`).

> This is the **open-source self-host** profile (everything local, CPU). Turns take
> ~15–30 s (STT-dominated) — say so. The **hosted** profile (cloud STT/TTS) is
> sub-second and is a *config-only* provider swap (see "Honest caveats").

---

## 1. Prerequisites

- **Headphones** — there is no echo cancellation; required so the mic doesn't hear
  the agent (and for barge-in to work).
- Backend venv with deps installed.
- For `--interview`: **Qdrant + Redis + Postgres** up, and the domain **ingested**.
- `.env`: set **`WHISPER_LANGUAGE=en`** (pins the language so whisper doesn't
  mis-detect on short clips), and an LLM with quota left (`LLM_PROVIDER`).

## 2. Setup (once)

```powershell
cd C:\Users\souma\OneDrive\Bureau\echo\backend
.\.venv\Scripts\Activate.ps1
docker compose -f ..\docker-compose.yml up -d qdrant redis postgres
python scripts\ingest_docs.py          # index the screening KB (first run / after doc edits)
```

## 3. Run the demo

```powershell
python scripts\run_live.py --interview --lang en
```

(Plain transport check, no services: `python scripts\run_live.py`.
If the mic rejects 16 kHz: add `--rate 48000`. Pick a device: `--device "USB"`.)

## 4. The script — what to say

1. **Disclosure** — the agent gives the AI notice and asks to continue.
   → You: **"Yes, I agree."**
2. The agent greets and asks **Q1** (interest in the role). → Answer naturally.
3. Walk the questions: **experience → stack → availability → remote → salary.**
4. **Show RAG** — mid-interview, *ask the agent* a question:
   → **"Is the role remote?"** → it answers from the knowledge base and you'll see
   `sources: remote_work_policy.md` printed (citation), then it re-asks its question.
5. **Show barge-in** — while the agent is speaking a longer line, **talk over it** →
   it cuts off and prints `[barge-in]`, then listens.
6. **Close** — say **"No more questions, I'm done."** → the agent closes.
7. The script prints the **filled slots**, then the **persisted notes + summary**.

## 5. What to highlight (talking points)

- **Provider-agnostic** — switching STT/LLM/TTS is **one env var** (show `.env`).
- **Domains are config** — a new vertical = a new `config/interview_flows/*.yaml`,
  **no code**.
- **Compliance** — spoken disclosure + consent + **immutable audit log**
  (`disclosure_hash` proves which notice the caller heard).
- **Grounding** — the agent answers **only** from retrieved docs, and refuses when
  it has no confident source (no hallucinations).
- **Structured output** — notes + summary persisted to Postgres, queryable.

## 6. Show the compliance trail (optional)

```powershell
# newest consent audit row (decision + disclosure_hash) — psql on host port 5433:
docker exec -it <postgres_container> psql -U echoassist -d echoassist `
  -c "select call_id, decision, granted, disclosure_hash, created_at from consent_log order by created_at desc limit 1;"
```

## 7. Honest caveats (say them out loud)

- **Latency ~15–30 s/turn** on this CPU, STT-dominated. The production target
  (<800 ms) needs a **GPU or cloud STT/TTS** — a *config-only* swap (Deepgram /
  Cartesia behind the same provider interface). This demo is the **self-host**
  profile; the **hosted** profile is sub-second.
- The agent speaks **English**; multilingual answers transcribe less reliably with
  the small CPU model (pin `--lang`).

## 8. Fallback — backup recording

Record a screen capture of a **successful run beforehand** (Win+G / OBS). If the
live call hiccups (LLM quota, mic, network), play the recording instead. Keep
`WHISPER_LANGUAGE=en` and a rehearsed answer set so the live run is predictable.

## 9. Reset between runs

Each run uses a fresh `call_id`; consent + call rows **accumulate** (that *is* the
audit trail). To present a clean DB, optionally truncate the demo tables before the
session.
