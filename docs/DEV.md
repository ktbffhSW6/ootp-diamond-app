# Dev workflow

> Per [Decision D16](DECISIONS.md#d16): Diamond is a two-process local-first
> app. FastAPI backend on `:8000`; Next.js frontend on `:3000`. Pydantic
> models are the single source of truth for the API contract; TypeScript
> interfaces auto-generate from them.

## First-time setup

### 1. Python backend

```bash
# Create venv (one-time)
python -m venv .venv

# Install deps including dev extras
.venv/Scripts/pip install -e ".[dev]"   # Windows
# or: .venv/bin/pip install -e ".[dev]"  # macOS/Linux
```

This pulls FastAPI, uvicorn, pydantic-to-typescript, plus the existing
DuckDB / Polars / pybaseball stack.

### 2. Node frontend

Diamond's frontend needs **Node 20+** and **pnpm**. If you don't have
them yet:

- **Node**: install via [nodejs.org](https://nodejs.org/) (LTS, ≥20).
- **pnpm**: `npm install -g pnpm` (or follow [pnpm.io](https://pnpm.io/installation)).

Then:

```bash
cd web
pnpm install
```

This installs Next.js, React, Tailwind, KaTeX, and the json2ts CLI
(transitive — needed by `make types`).

### 3. Configure API URL (optional)

The frontend reads `NEXT_PUBLIC_API_URL` to find the backend; defaults
to `http://localhost:8000`. To override:

```bash
cp web/.env.local.example web/.env.local
# edit web/.env.local
```

## Running the app

You'll always want two terminals open during dev — one per process —
so you can see each server's logs cleanly.

### Terminal 1 — backend

```bash
make api
# → uvicorn on http://localhost:8000
# → Swagger UI at http://localhost:8000/docs
```

Equivalent: `.venv/Scripts/python -m uvicorn diamond.api:app --reload --port 8000`

### Terminal 2 — frontend

```bash
make web
# → Next.js dev server at http://localhost:3000
```

Equivalent: `cd web && pnpm dev`

### One-shot dev launcher

`dev.bat` at the repo root is the one-shot convenience wrapper.
Double-click from Explorer or run from cmd. Sequence:

1. **Self-heal stale ports** — inline `netstat | findstr LISTENING |
   taskkill` loop clears anything left over on :3000 / :8000 from a
   crashed prior session. Required because if a prior `dev.bat` was
   force-closed (machine sleep, console kill, OS reboot) and left
   uvicorn or `next dev` orphaned, the next launch either fails to
   bind, OR — worse — Next.js silently connects to the stale uvicorn
   while you think you're running current code.
2. **`diamond ingest --all`** — picks up any new dumps OOTP wrote
   since last launch. No-op (~2-3s) when nothing's new; runs the
   L0/L1/L2/L3 pipeline for each pending dump otherwise. Has to run
   BEFORE uvicorn binds because uvicorn holds an RW lock on the
   DuckDB file. Skip with `set DIAMOND_SKIP_AUTO_INGEST=1` in the
   parent shell.
3. `start "Diamond API" cmd /k make api` — uvicorn :8000 in its own window
4. `start "Diamond Web" cmd /k make web` — Next.js :3000 in its own window
5. After a 6-second pause, opens the default browser to localhost:3000

If you only need to restart one side, run `make api` or `make web`
directly in a terminal. Those don't auto-ingest — quickest way to
skip the ingest check.

History (D34 cleanup, 2026-05-16): the prior dev launcher was four
files (`dev.bat` + `api.bat` + `web.bat` + `kill-stale.bat`).
Collapsed into the single `dev.bat` above, calling Makefile targets
directly. Saves 3 files at the repo root and ~85 LOC.

For production / single-window experience without the dev consoles,
use `Diamond.vbs` instead — see `docs/DESKTOP.md`.

### Keeping the warehouse fresh

OOTP writes a new dump roughly per in-game month. Two paths keep
Diamond in sync:

1. **Auto-ingest at launch** — `dev.bat` calls `diamond ingest --all`
   before starting uvicorn (see step 2 above). After OOTP writes a
   new dump, the next `dev.bat` run picks it up automatically.
2. **In-app `↻` button** — the header has a Refresh control next to
   the ⚙ and Quit buttons. It polls `GET /api/admin/dump-status`
   every 60 seconds and shows an amber badge with the pending count
   when new dumps are detected. Click to trigger a synchronous
   `POST /api/admin/ingest` — blocks the UI for the ingest duration
   (~30s-3min depending on pending count), then auto-refreshes the
   server-rendered pages so fresh data appears. Useful when you've
   been simming in OOTP with Diamond open in another window.

CLI introspection: `diamond status` prints the same gap the badge
shows (no work done — pure read of `_diamond_ingests`). Add
`--save NAME` to inspect a non-active save.

### Migrating dump_date convention (D36, one-time per save)

Pre-2026-05-16 ingests parked `dump_date` on the 1st of the month;
the convention is now end-of-month (per D36 — `dump_YYYY_MM` is
exported when OOTP advances *into* MM+1, so its data is stats
through the LAST day of MM, not the first). New ingests after
2026-05-16 land EOM directly. Existing warehouses need:

```bash
diamond migrate-dump-dates --save "<save_name>.lg"
```

Idempotent — re-running on an already-migrated warehouse is cheap
(a `_diamond_settings.dump_date_convention='end_of_month'` setting
marker short-circuits). On a small warehouse (~28 dumps) this
completes in under a minute. On a large one (45+ dumps with deep
snapshot history) it can take 10-15 minutes — the WHERE-filter
optimization (`WHERE dump_date <> LAST_DAY(dump_date)`) keeps
subsequent runs from re-doing finished work, but the first full
pass still rewrites every row of every dump_date-carrying base
table.

**Not auto-run** on warehouse open — stalling the API's first
request 10+ minutes would be unacceptable. Migrations are explicit
CLI steps, run on your schedule.
(save header + warehouse stats + Sox division standings + top-3 MLB
promotion/pressure pairs + 6 spotlight cards with sparkline + auto-
generated insight + last 8 movement-ledger rows). Three demo paths:

- **Glossary** — Next.js fetches `/api/glossary`, the FastAPI app
  converts the D15 dictionary's `STATS` dict to JSON, and the page
  renders all 60+ entries grouped by category. Click any entry for the
  KaTeX-rendered formula detail page.
- **Player page** (e.g. `/player/26166` for Gunnar Henderson) — avatar
  + bio header + Service & Status card + CareerArc SVG + Contract
  bar viz + Bref-shaped Stats tab (batting / pitching / fielding /
  advanced + Defensive Profile + Situational batting/pitching). Multi-
  stint years collapse to a clickable TOT row that expands to
  per-(level, team) sub-rows. Heat-scale coloring throughout.
- **Compare** — `/explore/compare?ids=3259,28963,36239` renders Bonds
  vs Trout vs Ohtani side-by-side with career stat blocks + WAR
  sparkline overlays. Empty state surfaces three demo deep-links.

## Type generation pipeline

```bash
make types
# → regenerates web/lib/types/api.ts from src/diamond/api/schemas/
```

What this does, end-to-end:

1. Imports every Pydantic model in `src/diamond/api/schemas/`.
2. Calls each model's `.model_json_schema()` to get JSON Schema.
3. Pipes JSON Schema through the `json2ts` CLI (Node-side, installed
   by `pnpm install` in `web/`).
4. Writes the result to `web/lib/types/api.ts` with a header marker.

Run `make types` after every Pydantic schema change. The frontend's
typed fetch helpers (`web/lib/api.ts`) and consuming pages will then
get the new types via TypeScript imports — no manual sync needed.

If `make types` fails with "json2ts CLI not found", run `pnpm install`
in `web/` and try again.

## Repo layout

```
ootp-diamond-app/
├─ src/diamond/                 Python package — warehouse + analytics + API
│  ├─ api/                      FastAPI app
│  │  ├─ app.py                 app factory + middleware
│  │  ├─ routes/                one module per resource
│  │  └─ schemas/               Pydantic response models (source of truth)
│  ├─ dictionary/               D15 stat dictionary
│  ├─ schema/                   warehouse build pipeline (L0→L3)
│  ├─ advanced/                 sabermetric stats library
│  └─ ...                       (records, awards, hof, streaks, glossary CLI)
├─ web/                         Next.js (App Router) frontend
│  ├─ app/                      routes (file-system based)
│  ├─ components/               shared React components
│  ├─ lib/api.ts                typed fetch helpers
│  ├─ lib/types/api.ts          AUTO-GENERATED from Pydantic
│  ├─ tailwind.config.ts
│  └─ package.json
├─ scripts/
│  ├─ generate_types.py         Pydantic → TS pipeline
│  └─ smoke_warehouse.py        end-to-end warehouse invariant check
├─ docs/                        Long-form context (read at session start)
└─ Makefile                     common dev tasks
```

## Adding a new API route

1. **Schema** — define the Pydantic response model in
   `src/diamond/api/schemas/<resource>.py`. Re-export from
   `src/diamond/api/schemas/__init__.py`. **Every type that crosses
   the wire must live in `schemas/`** — `pydantic-to-typescript` only
   scans that package, so types defined inline in `routes/` won't
   make it to the frontend.
2. **Route** — create `src/diamond/api/routes/<resource>.py` with a
   `router: APIRouter` and your handler functions.
3. **Wire** — add `app.include_router(<resource>.router, prefix="/api", tags=["..."])`
   to `src/diamond/api/app.py`.
4. **Types** — run `make types` to regenerate `web/lib/types/api.ts`.
5. **Frontend** — add a typed fetch helper in `web/lib/api.ts`, then
   consume it from a server component in `web/app/<resource>/page.tsx`.
6. **Mark the page dynamic** — add `export const dynamic = "force-dynamic"`
   to the page. Diamond is local-first; without this, Next.js's
   default static prerender at `next build` time will call the API
   while uvicorn isn't running and your build will fail with
   `ECONNREFUSED`. Every data-fetching page in Diamond gets this.

The glossary endpoint is the canonical reference implementation —
copy its shape when adding new resources.

## Troubleshooting

- **CORS errors in the browser**: verify the FastAPI process is
  running on port 8000 and `NEXT_PUBLIC_API_URL` matches. CORS is
  configured for `localhost:3000` only.
- **`make api` errors out on Windows with Unicode**: the existing
  Windows UTF-8 reconfigure happens in the CLI, not the API. If you
  see encoding errors in dev, try setting `PYTHONIOENCODING=utf-8`
  in your shell.
- **Frontend can't fetch**: hit `http://localhost:8000/api/health`
  in a browser to confirm the backend is reachable.
- **`make types` fails**: confirm `pnpm install` ran successfully in
  `web/` and `web/node_modules/.bin/json2ts` exists.
- **`uvicorn` fails to bind on :8000 / `next dev` fails on :3000**:
  a prior session left a stale process holding the port. Re-run
  `dev.bat` — its inline self-heal step clears stale processes on
  :3000 / :8000 before launch (D34). For a manual side-channel
  cleanup if you don't want to relaunch dev.bat:
  ```cmd
  for /f "tokens=5" %I in ('netstat -ano ^| findstr ":3000.*LISTENING"') do taskkill /F /PID %I
  for /f "tokens=5" %I in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %I
  ```
- **Code changes don't appear in the running app**: classic
  symptom of Next.js silently connecting to a stale uvicorn from a
  prior session. The browser hits the new Next, but Next's
  server-component fetches reach the OLD uvicorn (still on :8000).
  Quit + relaunch `dev.bat` (the self-heal step kills stale
  processes). To confirm: hit `http://localhost:8000/api/health` and
  check the response — the `version` field bumps with each new
  schema-affecting commit.

## What's not in scope (yet)

Per D16, these are deferred until later phases:

- Auth / multi-tenancy — Diamond is single-user local-first.
- Production hosting — when the web-share path opens (Phase 4+),
  hosting + deploy gets its own decision.
- Background workers — ingest stays a CLI operation.
- Database migrations — the warehouse is per-save and CTAS-rebuildable;
  no migration framework needed.
