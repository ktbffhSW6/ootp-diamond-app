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

### Windows without `make`

If you don't have `make` installed (it's not part of base Windows),
use the batch shortcuts at the repo root instead:

```cmd
api.bat        :: same as `make api`
web.bat        :: same as `make web`
dev.bat        :: spawn both + open the browser at :3000 (one-shot launcher)
```

Both `api.bat` and `web.bat` `cd` to the right directory, set
`PYTHONIOENCODING=utf-8` (needed for Rich box-drawing on the API
side), and pause on error so the message is readable. Double-clicking
either file from Explorer also works.

`dev.bat` is the one-shot convenience wrapper — it `start`s each of
the other two batch files in its own console window (so the logs stay
visible and either can be Ctrl+C'd independently) and then opens the
default browser to `http://localhost:3000` after a 6-second pause to
let Next.js's first compile finish. If you only need to restart one
side, use `api.bat` / `web.bat` directly.

Open http://localhost:3000 — you'll land on the **cockpit dashboard**
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

## What's not in scope (yet)

Per D16, these are deferred until later phases:

- Auth / multi-tenancy — Diamond is single-user local-first.
- Production hosting — when the web-share path opens (Phase 4+),
  hosting + deploy gets its own decision.
- Background workers — ingest stays a CLI operation.
- Database migrations — the warehouse is per-save and CTAS-rebuildable;
  no migration framework needed.
