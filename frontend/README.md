# EchoAssist Dashboard 




## Prerequisites

- Node 20+ (developed on Node 25), npm.

## Quick start

```bash
cd frontend
npm install
cp .env.example .env        # optional; defaults are fine for the mock demo
npm run dev                 # http://localhost:5173
```

`npm run dev` runs against an **in-browser mock backend** (MSW) — no backend, Docker, or
API keys needed. Log in with any email/password or an SSO button (dev stub), then click
**Start screening call** to watch a live transcript stream in.

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
  hooks/      useCallEvents (live stream), useTheme
  components/ BrandMark, StatusBadge, ConsentBadge, EmptyState, ThemeToggle, ui/* (shadcn-style)
  mocks/      MSW handlers + db + scripted live-call transport (dev / offline)
  test/       Vitest setup + tests

  # demo host only (NOT shipped to ACTEEK):
  auth/       AuthProvider + dev SSO stub (session token → agent via getAuthToken)
  features/auth/  LoginPage
  components/ AppFrame (slim top bar), ReadinessIndicator
  App.tsx     login gate → AppFrame wrapping <EchoAssistAgent>
```

## Notes


- **Live transport**: `useCallEvents` uses a native `WebSocket` against the backend,
  or the in-browser scripted transport when mocks are on. The live-event fold
  (`src/lib/ws.ts`) is pure and unit-tested.
- **Out of scope (follow-ups)**: the reproducible benchmark report (latency
  p50/p95, WER, Recall@K / nDCG, note accuracy, summary faithfulness) — surfaced as a
  note on the Metrics tab;
```