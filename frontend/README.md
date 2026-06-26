# EchoAssist Dashboard (Sprint 7)

A thin, on-brand React dashboard for **EchoAssist** inside the **ACTEEK Agent
Marketplace**. A recruiter can run and inspect screening calls — live transcript,
structured notes, post-call summary, consent audit trail — wired to the FastAPI
backend over REST (TanStack Query) and the live WebSocket.

Built per `ARCHITECTURE.md` §8 / `ROADMAP.md` §7: React + Vite + TypeScript,
Tailwind CSS v4 mapped to the ACTEEK `--c-*` tokens, shadcn/ui-style primitives on
Radix, Space Grotesk + Manrope, **dark-mode first** with a light toggle.

## What's the deliverable vs. the demo

The **deliverable is the agent**, not a whole app. ACTEEK already owns the
marketplace, sidebar, theme, and SSO — they just **embed** your agent:

```tsx
import { EchoAssistAgent } from './embed' // src/embed/index.ts is the public surface

<EchoAssistAgent
  config={{
    apiBaseUrl: 'https://api.acteek.com/echoassist',
    getAuthToken: () => acteekSession.accessToken, // their SSO token
    domain: 'screening',
  }}
/>
```

`<EchoAssistAgent>` ([src/embed/](src/embed/EchoAssistAgent.tsx)) is self-contained:
its own TanStack Query client + tooltip host, list↔detail driven by **local state
(no router)** so it works under any host routing and never touches the host URL.
It renders **only** the agent workspace (calls, live transcript, notes, summary,
consent, metrics, domain config). It inherits the theme from the host's
`[data-theme]` via the shared `--c-*` tokens.

Running this project standalone (`npm run dev`) boots **straight into the agent** via a
thin dev harness (`src/App.tsx`) that mounts `<EchoAssistAgent>` and adds a theme toggle,
so you can present and validate it on its own. The marketplace, sidebar, login, and SSO
are **ACTEEK's** — intentionally *not* built here (ARCHITECTURE.md §2 — *don't rebuild
ACTEEK auth*); ACTEEK supplies the shell and passes the SSO token via `config.getAuthToken`.

## Prerequisites

- Node 20+ (developed on Node 25), npm.

## Quick start

```bash
cd frontend
npm install
cp .env.example .env        # optional; defaults are fine for the mock demo
npm run dev                 # http://localhost:5173
```

By default `npm run dev` opens the agent against an **in-browser mock backend** (MSW)
that mirrors the real DTOs and a scripted live call — so it's usable with no backend,
Docker, or API keys. Click **Start screening call** to watch a live transcript stream in.

## Run against the real backend

```bash
# 1) start the backend (repo root): python scripts/serve.py  (API on :8000)
# 2) point the dashboard at it and disable mocks:
VITE_USE_MOCKS=false VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

For real use, lock down the backend CORS: set `API_CORS_ORIGINS` to the dashboard
origin (it ships as `*`, dev-only).

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server (mocks on by default) |
| `npm run build` | Type-check (`tsc -b`) + production build |
| `npm run typecheck` | Types only |
| `npm run lint` | oxlint |
| `npm run test` | Vitest (unit + component) |
| `npm run format` | Prettier write |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend base URL (WS URL derived: http→ws) |
| `VITE_USE_MOCKS` | dev: `true`, build: `false` | Serve from the in-browser mock backend |

## Structure

```
src/
  embed/      ← THE DELIVERABLE: EchoAssistAgent (public surface) + config contract
  features/   agent · calls (list/detail/transcript/notes/summary/consent) · metrics · config
  lib/        env, runtimeConfig (host API + auth), types (mirror backend DTOs), api,
              query (TanStack), ws (live-event reducer + transport), format
  hooks/      useCallEvents (live stream), useTheme (dev harness)
  components/ StatusBadge, ConsentBadge, EmptyState, ThemeToggle, ui/* (shadcn-style)
  mocks/      MSW handlers + db + scripted live-call transport (dev / offline)
  test/       Vitest setup + tests
  App.tsx     thin dev harness: mounts <EchoAssistAgent> + theme toggle (NOT shipped to ACTEEK)
```

## Notes

- **Auth**: ARCHITECTURE.md §2 — *do not rebuild ACTEEK auth*. The agent never logs in;
  it just calls `config.getAuthToken()` (ACTEEK's SSO token) and sends it as
  `Authorization: Bearer` on REST + the `access_token` WS query param.
- **Live transport**: `useCallEvents` uses a native `WebSocket` against the backend,
  or the in-browser scripted transport when mocks are on. The live-event fold
  (`src/lib/ws.ts`) is pure and unit-tested.
- **Out of scope (Sprint 7 follow-ups)**: the reproducible benchmark report (latency
  p50/p95, WER, Recall@K / nDCG, note accuracy, summary faithfulness) — surfaced as a
  note on the Metrics tab; real ACTEEK OAuth; PDF/DOCX upload (md/txt by design).
```
