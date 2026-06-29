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

---

## 10. Path B — the same demo on a real phone number (LiveKit + SIP)

The mic demo above proves the engine. **Path B carries the *same* session over a
LiveKit room instead of the local mic** — `scripts/run_livekit.py` swaps
`LocalAudioTransport` → `LiveKitTransport` and **nothing else changes** (same
disclosure→consent→interview→notes/summary, same `src.telephony.live_session`).
Roll it out in two steps; the agent script is identical for both.

> Needs accounts: **LiveKit** (Cloud or self-host) for step 10.1, **plus Twilio**
> for step 10.2. Put keys in `backend/.env` (never committed). For an interactive
> call also set the cloud providers — `STT_PROVIDER=deepgram`, `TTS_PROVIDER=cartesia`
> (+ their keys) — so turns are sub-second instead of the ~15–30 s CPU story.

### 10.1 SAFE FIRST — WebRTC loopback (a browser is the caller, no phone number)

1. **Get LiveKit credentials.** Cloud: create a project at
   <https://cloud.livekit.io> → copy the **Project URL** (`wss://<you>.livekit.cloud`)
   + an **API key/secret**. Self-host (no account, needs Docker):
   `docker run --rm -p 7880:7880 -e LIVEKIT_KEYS="devkey: secret" livekit/livekit-server --dev`
   → `LIVEKIT_URL=ws://localhost:7880`, key `devkey`, secret `secret`.
2. **`.env`:**
   ```
   LIVEKIT_URL=wss://<you>.livekit.cloud
   LIVEKIT_API_KEY=...
   LIVEKIT_API_SECRET=...
   LIVEKIT_ROOM=echoassist
   ```
3. **Install the extra (once):** `pip install -e ".[telephony-livekit]"`.
4. **Run the agent** (it connects, publishes its voice, and waits for a caller):
   ```powershell
   python scripts\run_livekit.py --interview --lang en
   ```
5. **Join as the caller:** the script prints a **meet.livekit.io URL** — open it in a
   browser, allow the mic, and you are on the call. WebRTC does echo cancellation, so
   **barge-in works without headphones**. The script flow is identical to §4.

### 10.2 PSTN — route a Twilio number into the room (no code change)

A phone caller is just another room participant, so `run_livekit.py` is **unchanged**;
you wire the carrier once. Using the LiveKit CLI (`lk`, authenticated to your project):

1. **LiveKit SIP inbound trunk** — accept calls for your number:
   ```bash
   lk sip inbound create --name echoassist-in --numbers "+1XXXXXXXXXX"
   ```
2. **LiveKit dispatch rule** — send every inbound SIP call to the fixed room the agent
   waits in (so the agent and the caller meet):
   ```bash
   lk sip dispatch create --name echoassist-dispatch \
     --trunks <trunk_id> --room echoassist --type direct
   ```
3. **Twilio** — buy a number, create an **Elastic SIP Trunk**, and point its
   **Origination URI** at your LiveKit SIP host (Cloud: `sip:<project>.sip.livekit.cloud`;
   self-host: your server's SIP URI), then route the number to that trunk. (Twilio
   `<Dial><Sip>` TwiML to the same URI also works.)
4. **Run the agent** (`python scripts\run_livekit.py --interview`) so it is in
   `echoassist`, then **dial the Twilio number** — the disclosure plays, consent is
   captured, and the screening runs over the phone. The compliance trail (§6) and
   notes/summary persist exactly as in the local demo.

### 10.3 Fallback

The §8 backup-recording advice applies to the live phone demo too — pre-record one
successful PSTN call; if the carrier/network hiccups on the day, play the recording.

> **Status:** Path B code is written and unit-tested (provider/transport seams, token
> grant, endpointing) but **not yet validated against live LiveKit/Twilio accounts** —
> the steps above are the validation procedure to run once keys exist.
