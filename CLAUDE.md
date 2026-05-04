# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read these first

The project keeps long-running engineering context in `docs/`. Always read at the start of a session:

- `docs/PROJECT_STATUS.md` — current phase, what works, what was last done, what's next.
- `docs/DECISIONS.md` — append-only log of architectural/scope decisions with rationale (D1–D16).
- `docs/DATA_NOTES.md` — empirical findings about the OOTP dump shape, codebooks, and IE display conventions.
- `docs/BACKLOG.md` — prioritized open work, grouped by phase (Schema/Ingest → Analysis → UI).
- `docs/UI_DESIGN.md` — UI build order + design conventions for the player/leaderboards/cockpit pages.
- `docs/DEV.md` — two-process dev workflow (FastAPI + Next.js), `make` targets, troubleshooting.

These files are the source of truth for "why" — favor updating them over leaving knowledge in chat.

**Current phase: Phase 3 — UI implementation.** Phase 2 (schema/ingest) closed 2026-05-05; analytical layer + real-history backfill closed 2026-05-06; UI scaffold + player page (Stats tab: batting / pitching / fielding / advanced) all live as of 2026-05-07. The reconciliation harness (`reconcile.py`) stays in the codebase as a permanent post-ingest regression check (Decision D8).

## Setup & commands

```bash
pip install -e ".[dev]"            # editable install + pytest/ruff
diamond --help                     # list CLI commands
```

### Two-process dev workflow (D16)

Diamond ships as **FastAPI on :8000 + Next.js on :3000**. You always want both running in separate terminals so you can read each one's logs.

```bash
# Terminal 1 — backend (FastAPI + uvicorn --reload)
make api          # or: api.bat            (Windows-friendly)

# Terminal 2 — frontend (Next.js dev server)
make web          # or: web.bat            (Windows-friendly)

# After Pydantic schema changes — regenerate web/lib/types/api.ts
make types

# End-to-end warehouse build + invariant check (~60s)
make smoke        # or: scripts/smoke_warehouse.py
```

`api.bat` and `web.bat` at the repo root are Windows shortcuts for users without `make` installed — they cd to the right directory and set `PYTHONIOENCODING=utf-8` for Rich output. Functionally identical to the `make` targets.

### CLI commands (audit + analytical surface)

```bash
diamond ingest                     # ingest the latest dump → L0…L3 warehouse build
diamond ingest --rebuild-only      # rebuild L1+L2+L3 from existing L0 (cheap; ~30s)
diamond reconcile                  # per-column compare IE roster CSVs vs warehouse derivations
diamond decode / decode-codes      # discover OOTP integer codebooks
diamond coverage                   # profile dump CSVs supporting each user-facing feature
diamond advanced                   # compute Tier 1-5 advanced stats (top-N report)
diamond records / awards / hof     # leaderboards + Cooperstown
diamond streaks                    # decoded streak history
diamond draft <year>               # per-class draft analyzer
diamond fetch-history              # one-time Lahman + Statcast + MLB API backfill
```

All audit/report commands write markdown to `audit_output/` (gitignored). Each takes `--dump <name>` (defaults to latest) and `--output <path>` overrides.

There is no test suite yet — `pyproject.toml` declares `pytest` but no `tests/` exists. When adding code, validate by running the relevant CLI command + reading its `audit_output/` report, or run `make smoke` for a full warehouse rebuild + invariant check.

### Windows / editable install gotcha

Hatchling's editable install can fail to register `src/` on Windows. If `import diamond` fails after `pip install -e .`, manually create `.venv/Lib/site-packages/diamond.pth` containing the absolute path to `src/`. The CLI also force-reconfigures stdout/stderr to UTF-8 on Windows (`src/diamond/cli.py`) so Rich box-drawing characters render — don't remove that block.

## Architecture

### Two halves: CLI/analytical and API/web

Per Decision D16, Diamond is a **two-process local-first app**:

- **Backend half** — `src/diamond/` Python package. Ingest pipeline + analytical CLI (audit / advanced / records / awards / hof / streaks / draft / glossary) + FastAPI app under `src/diamond/api/`.
- **Frontend half** — `web/` Next.js 15 (App Router) + Tailwind + KaTeX + react-katex. Reads `web/lib/types/api.ts`, which is **auto-generated from Pydantic schemas** by `scripts/generate_types.py` (`make types`). The frontend never duplicates response shapes.

The wire format is JSON; the Pydantic models in `src/diamond/api/schemas/` are the single source of truth for the contract. Adding a field there + running `make types` propagates it to the frontend. **Every type that crosses the wire MUST live in `schemas/`** — `pydantic-to-typescript` only scans that package, so types defined inline in routes won't make it across.

### Backend module map

```
src/diamond/
  api/                      FastAPI app (D16)
    app.py                  factory + CORS for localhost:3000
    routes/                 one module per resource (glossary, players, health)
    schemas/                Pydantic response models — single source of truth
    warehouse.py            per-process root DuckDB conn + cursor-per-request
  audit/                    discovery + per-column reconciliation harness (D8)
    reconcile.py            permanent regression check vs IE roster CSVs
    decode.py / decode_codes.py    empirical codebook discovery
    coverage.py             per-feature dump-CSV profiling
    advanced.py             top-N advanced-stats report driver
  advanced/                 pure stat-computation library (5 tiers)
    contact.py / situational.py / sabermetric.py / defensive.py / approach.py
    enriched.py             shared at-bat view (bip_flag, risp_flag, etc.)
    league_constants.py     advanced-lib-scoped (linear weights, woba_scale, fip_const)
  schema/                   warehouse build pipeline (L0 → L1 → L2 → L3)
    l0.py / l1_*.py / l2.py
    l3.py                   trade attribution / movements / draft / records / awards / streaks
    l3_advanced.py          per-(player, year, league, level) advanced-stats fact tables
    build.py                orchestrator + admin (_diamond_ingests, _diamond_settings)
  dictionary/               D15 stat dictionary (60 entries — single source of truth for labels)
    __init__.py             Stat dataclass + CATEGORIES tuple
    _stats.py               canonical entries grouped by category
  league_constants.py       top-level (warehouse-level) lg_constants_bat / _pit views (D11)
  constants.py              verified OOTP integer codebooks (IntEnums + POSITION_NAMES + LEVEL_NAMES)
  config.py                 SaveConfig + BUILDING_THE_GREEN_MONSTER singleton
  cli.py                    Typer entry-point + Windows UTF-8 reconfigure
```

Other top-level modules (`records.py`, `awards.py`, `hof.py`, `streaks.py`, `glossary.py`, `draft.py`, `history.py`) are CLI feature drivers — they read the warehouse and render Rich tables / markdown.

### Frontend module map

```
web/
  app/                      Next.js App Router (file-system-based routing)
    page.tsx                home with feature links
    glossary/page.tsx       D15 dictionary list
    glossary/[id]/page.tsx  single-stat detail with KaTeX-rendered formulas
    player/[id]/page.tsx    Bref-style player page (Stats tab — batting/pitching/fielding/advanced)
  components/
    PlayerStatsTab.tsx      client component — disclosure-row tables for the player Stats tab
    FormulaBlock.tsx        KaTeX wrapper with parse-fail fallback
  lib/
    api.ts                  typed fetch helpers (one per endpoint; throw on non-2xx)
    types/api.ts            AUTO-GENERATED — do not hand-edit
```

Every data-fetching page **must** `export const dynamic = "force-dynamic"`. Without it, Next's default static prerender at `next build` time calls the API while uvicorn isn't running and fails with `ECONNREFUSED`. See `docs/DEV.md` "Adding a new API route" for the canonical recipe.

### Warehouse layers

```
L0  raw     69 tables    one-to-one with dump CSVs (read_csv_auto, dynamic CTAS)
L1  conformed
    machinery   _scoped_teams + _scoped_players (D13: org tier UNION ≥1 MLB appearance)
    reference   12 tables (teams, leagues, parks, ...)
    event       35 tables (collapsed dups; PK on natural key)
    snapshot    21 tables + 6 _current views
L2  facts   8 tables (f_player_season_*, f_player_career, f_team_season,
                      f_league_season, f_pa_event, f_award_event)
L3  derived 8 tables — trade_participant, player_movements, draft_class,
                       record_player, award_career_player, award_franchise,
                       player_streak, **f_player_season_advanced_batting +
                       _advanced_pitching** (sabermetric stack per player+year+
                       league+level with park-aware OPS+/ERA+/FIP/wRC+/oWAR/pit_WAR)
History (one-time) lahman / bref / statcast / mlbapi / chadwick crosswalk
```

The audit layer (Phase 1) is **scaffolding**. Advanced stats now run against the warehouse via `f_player_season_advanced_*`; the formulas in `src/diamond/advanced/` remain canonical for the audit harness + ad-hoc Polars/SQL paths.

### Configuration

- `src/diamond/config.py` defines `SaveConfig` (paths + scoped league IDs) and the singleton `BUILDING_THE_GREEN_MONSTER` for the active save (15 league IDs: MLB org tree + DSL + AFL).
- The OOTP saves root is hardcoded to `C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games`. Per save, the layout is `<save>/dump/dump_<YYYY>_<MM>/csv/*.csv` (monthly snapshots) and `<save>/import_export/*.csv` (the OOTP-generated reference roster CSVs we reconcile against). Per D2 the warehouse lives at `<save>/diamond/diamond.duckdb`.
- Per Decision D3, scope is hardcoded for v1 but a save-setup picker is a hard v2 requirement — keep the scoping mechanism in `SaveConfig`, not inline.

### Reconciliation patterns (`audit/reconcile.py`)

When adding a new `FileSpec`:

- **Don't filter by `team_id`.** IE roster files show each player's *full season* totals (including stints on prior orgs and short-season stops). The standard pattern is `WHERE year = 2029 AND split_id = 1` — no team filter.
- Fielding stats use `split_id = 0` (no platoon split for fielding).
- Player ratings (`scouted_ratings`) need `WHERE scouting_team_id = 4` to take the Red Sox's view of every player. Don't add a `league_id` filter — each player has exactly 1 row at team=4 across all leagues, and adding a league filter restricts the audit to MLB only (24 of 220 IE rows).
- Use `overall_rating` / `talent_rating` (already 20-80) — **never** the raw `overall` / `talent` fields (0-200 internal scale). Per Decision D6.
- IP convention: `FLOOR(outs/3) + (outs%3)*0.1` (e.g., 517 outs → 172.1, not 172.4).
- Tier each column: A=direct dump field, B=trivial calc, C=needs league constants, D=modeled (xstats), E=at-bat aggregation, F=cannot replicate (per D5 or string-formatted display), G=needs scale conversion or integer→string mapping.
- The matcher (`_is_match`) normalizes IE display formats: `"-"` → null, `"9.1%"` → `9.1`, `"$28 800 000"` → `28800000`, `"1 (auto.)"` → `1`. Don't fight these in derivation SQL — let the matcher handle them.
- Add new dump CSVs to `_connect()`; that's where every reconcile job picks up its views.

### Codebooks

`src/diamond/constants.py` is the canonical home for verified OOTP integer mappings — `IntEnum`s plus the position/level name dicts used across audit, draft, and the API layer:

- `GameType`, `SplitId`, `AtBatResult` (at-bat domain)
- `AwardId`, `LeaderCategory`, `StreakId`, `BodyPart`, `Popularity`, `ScoutingAccuracy`
- `POSITION_NAMES` (1=P, 2=C, 3=1B, ...), `LEVEL_NAMES` (1=MLB, 2=AAA, ...)

Don't introduce magic numbers in derivation SQL — reference the `IntEnum`. When `decode-codes` discovers a new mapping, add it with a docstring noting how it was verified (exact aggregate match, cross-ref against another file, etc.).

### Stat dictionary (D15)

`src/diamond/dictionary/STATS` is the **only** place stat metadata lives. Every column header, chart axis, glossary tooltip, and AI prompt reads from `STATS[id]` — never hand-coded. As of 2026-05-07 the dictionary covers 60 entries (slash + counting batting/pitching, fielding counting + FPCT + RF/9, the league-relative advanced stack including wOBA/wRC+/OPS+/FIP/ERA+/SIERA, custom WAR, and the Statcast EV/barrel cohort).

Strict rule: any new UI label MUST come from the dictionary. Adding a new stat = add an entry to `_stats.py`. The smoke test's Phase G validates required-fields-non-empty + categories valid + related-id resolution + id uniqueness.

### Adding a new API route (the canonical recipe)

Per `docs/DEV.md`:
1. Define the Pydantic response model in `src/diamond/api/schemas/<resource>.py`. Re-export from `schemas/__init__.py`.
2. Create `src/diamond/api/routes/<resource>.py` with a `router: APIRouter` and your handler functions.
3. Wire `app.include_router(<resource>.router, prefix="/api", tags=[...])` in `src/diamond/api/app.py`.
4. Run `make types` to regenerate `web/lib/types/api.ts`.
5. Add a typed fetch helper in `web/lib/api.ts`, then consume it from a server component at `web/app/<resource>/page.tsx`.
6. **Mark the page dynamic** — `export const dynamic = "force-dynamic"` on every data-fetching page (otherwise `next build` fails with ECONNREFUSED).

The glossary endpoint is the canonical reference implementation; the player endpoint is the canonical reference for warehouse-backed routes (depends on `get_cursor` from `api/warehouse.py`).

## Conventions and gotchas

- The `players_at_bat_batting_stats` log has `result` codes 1=K, 2=BB, 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR, 10=HBP, 11=CI. BIP excludes sacrifices (`sac > 0`).
- `import_export` files are named with the team-org prefix (`boston_red_sox_organization_-_roster_*.csv`). They were generated by OOTP and exist alongside `dump/` in the save folder.
- The November dump (`dump_YYYY_11`) is the end-of-season snapshot — it's the canonical source for season-stat reconciliation. Earlier monthly dumps roll over at season start (Feb-Mar).
- DSL teams: the Red Sox have one FCL + two DSL teams; org-level rollups must include all three.
- Park factors: **halved** for OPS+ / wRC+ (`1 + (avg-1)/2`), **80%** for ERA+ / pit_WAR (`1 + (avg-1)*0.8`). Audit-decoded; verified Crochet 2029 ERA+ 127 vs IE 127 (Fenway).
- League constants are per `(league_id, year, level_id)` — never roll up across levels. AAA wOBA uses AAA constants, not MLB's. (D11)
- League history coverage in this save is **2026-2029**. Pre-2026 player rows have counting stats (OOTP imports them from real history) but no league baselines, so advanced stats render as `—` for those years. Mapping to Lahman/BREF averages is a deferred backlog item.
- `audit_output/` is gitignored. Reports are regenerable from CLI; commit the *generators*, not the outputs.
- `.env` exists locally and is gitignored — GitHub push protection has blocked it before. Don't `git add -A` blindly.
- `docs/screenshots/` is gitignored — user-local context, not part of the repo's permanent record.
