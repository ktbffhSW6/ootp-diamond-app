# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read these first

The project keeps long-running engineering context in `docs/`. Always read at the start of a session:

- `docs/PROJECT_STATUS.md` — current phase, what works, what was last done, what's next.
- `docs/DECISIONS.md` — append-only log of architectural/scope decisions with rationale (D1–D28).
- `docs/DATA_NOTES.md` — empirical findings about the OOTP dump shape, codebooks, and IE display conventions.
- `docs/BACKLOG.md` — prioritized open work, grouped by phase (Schema/Ingest → Analysis → UI).
- `docs/UI_DESIGN.md` — UI build order + design conventions; committed five-tab IA + theme system live here.
- `docs/DEV.md` — two-process dev workflow (FastAPI + Next.js), `make` targets, troubleshooting.

These files are the source of truth for "why" — favor updating them over leaving knowledge in chat.

**Current phase: Phase 3 — UI implementation, mid-build.** Phase 2 closed 2026-05-05; analytical layer + real-history backfill closed 2026-05-06; UI scaffold + player Stats tab landed 2026-05-07; 2026-05-08 shipped the IA backbone (D17), theme system (D18), movement ledger, real landing page, and in-app Quit / dev.bat launcher; 2026-05-09 shipped the roster page + L3 SIERA + a Statcast cohort + full dump-CSV vs L0 audit. **2026-05-10 shipped three player-page slices in one day** — combined bWAR / pWAR (OOTP-canonical, IE-A-tier reconciled), per-position fielding view (Defensive Profile section), and service-time / arb clock (Service & Status card). 2026-05-11 shipped the standings page — first real content on the `/league` tab. **2026-05-12 shipped five situational-stack slices** plus an end-of-day maintenance fix: (1) batter situational splits on the player page; (2) **multi-year `f_pa_event`** — closes the prior-year coverage gap by reading L0 directly with cross-dump dedup keyed on (game_id, season_year); discovered **OOTP recycles `game_id` across seasons**, PK promoted to (year, game_id, batter_id, pa_in_game_seq). f_pa_event 877k → 5.1M rows, Statcast cohort tables 3,305/3,692 → 20,800/21,513; (3) pitcher situational splits with inverted color logic; (4) bases / platoon splits with side-aware labels and switch-hitter resolution; (5) counts (first pitch / two strikes / full count) + spray (pull / center / oppo) splits. **14 splits per (year, level)** total. Empirically verified along the way that `hit_xy` is **batter-relative** (mean hit_xy on HRs ≈71 for both LHB and RHB — same pull-side band for both hands), correcting earlier DATA_NOTES claim. Crochet 2027 RISP 2-out **.316 OPS allowed** (elite); Devers 2029 Pull 12 HR / Center 15 HR / Oppo 0 HR (27 total). Five-tab nav (Club / League / World / History / Explore); dark mode is the default. **End-of-day maintenance pass (D20)** — Lahman 1871-2019 + BREF 2020-2025 league aggregates UNIONed into `_lg_constants_advanced` so OOTP-imported pre-2026 player-seasons (Bonds, Mantle, Trout, Pedro, etc.) now resolve real wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR. f_player_season_advanced_batting 30k → **244,183 rows**; spot-checks Bonds 2001 OPS+ 257 (BBR 259), Pujols 2003 OPS+ 189 (BBR 189 — exact), Trout 2018 OPS+ 198 (real 198 — exact). **2026-05-12 (continued) — History tab fully drained + Pressure board shipped.** All five History stubs (Records + Awards + HoF + Streaks + Draft) plus the Pressure board (`/pressure`) — the GM-decision "who *should* move" companion to `/movements`. Records: `GET /api/records?scope=&discipline=&category=&era=` UNIONs save + Lahman + BREF + merged + Statcast leaderboards. Awards: `GET /api/awards?league_id=&award_id=&era=` returns career trophy-count holders (Ohtani / Bonds 7 MVPs, Maddux 18 GG). HoF: `GET /api/hof?view=` toggles between Inductees (285) and Candidates (top-25 non-inducted by career WAR — Bonds 146.6 / Clemens 142.6 / Pete Rose 123.0). Streaks: `GET /api/streaks?streak_id=&scope=` for 21 streak types × 2 scopes (Szykowny 56-game hit streak ties DiMaggio). Draft: `GET /api/draft?year=` returns the full ~600-pick class grouped by outcome bucket (MLB Regulars → Callups → Still Developing → Traded → Released → Retired); Sox 2026 spotlights Skelton 4.124 (3.6 WAR find) + Jackson Flora 1.12 LAA (4.4 WAR class leader). Color-coded chips, player-page deep-links, forgiving fallbacks across all five History pages. Pressure: `GET /api/pressure?year=&limit=` returns per-level promotion candidates (top OPS+/ERA+) + pressure cases (bottom) for the org tree. 2029 spotlights Caleb Durbin 183 OPS+ at AAA / 97 at MLB ("stop yo-yo'ing him") + Garcia/Rodriguez/White as AAA call-up candidates while Narvaez 75 / Anthony 94 / Langeliers 94 sit on the MLB pressure list. **2026-05-13 shipped five slices + an IA shuffle**: (1) **Custom leaderboards** at `/league/leaderboards` — TanStack Table with 32 stats across batting / pitching / Statcast, URL-driven picker, heat-scale on plus-stat / WAR columns; (2) **Spray + EV-LA charts inline on the player page** with `@observablehq/plot` + hand-rolled polar-fan SVG (D23 commits to Observable Plot for cohort viz, deferring Vega-Lite + WebGL until JSON-spec authoring or full-league cohort scale); (3) **Historical park factors (D22)** — pre-2020 MLB OPS+/ERA+ now use Lahman BPF/PPF via a `_park_factor_resolved` view + 30-row OOTP↔Lahman franchID crosswalk. Bonds 2001 OPS+ 257→267 (BBR 259), Pujols 2003 189→193 (BBR 189), Trout 2018 198→201 (BBR 198), Coors 1995 BPF 1.29; (4) **AI overlay (D14)** — `diamond/ai/` package with keyring-backed key storage + Anthropic + OpenAI adapters via httpx (no SDK deps), `/api/ai/settings` + `/api/ai/summarize`, settings page at `/settings/ai`, "Summarize career" button on player page; (5) **Setup wizard (D3 v2)** — `/api/saves` + `/api/saves/active` for save discovery + active-save switcher with persistence to `~/.diamond/active_save.toml`; UI at `/settings/save` with cards for each save under the OOTP saves root, "needs ingest" badge for saves without a warehouse. Settings landing at `/settings` now linked from header (⚙ icon). **End-of-day IA shuffle**: `/explore` is now JUST the **Chart Builder workshop** (pick X/Y/color from the 32-stat catalog, filter, render via Plot.dot scatter or Plot.rectY histogram; cross-table joins handled transparently). Per-player charts moved inline to the player page; league-wide tools (leaderboards + compare) moved to `/league/*`. Permanent 308 redirects keep old URLs working. Also added a `kill-stale.bat` recovery file at repo root + wired `dev.bat` to call it as a self-heal step (clears zombie processes on :3000 / :8000 from a crashed prior session). **2026-05-13 (continued, evening)**: per-save scope (D3 v2.1) — `~/.diamond/save_configs.toml` per-save audit_team_id + league_ids; static 30-team `mlb_teams.py` catalog; `diamond ingest --save NAME` flag; division-grouped picker UI on `/settings/save`; legacy-default bootstrap migration. Photo cache (D24) — flipped from `max-age=86400, immutable` to ETag + Last-Modified revalidation with `Cache-Control: no-cache`; new photos appear instantly when OOTP regenerates instead of after 24h browser cache. Auto-ingest at launch — `dev.bat` chains `diamond ingest --all` before uvicorn binds; `GET /api/admin/dump-status` + `POST /api/admin/ingest` + header `↻ Refresh` button (`RefreshButton.tsx`) for mid-session pickup, polls every 60s with badge when pending; `diamond status` CLI for terminal introspection. **LSEG-Workspace density refactor (D25)** — full-width layout (drops `max-w-6xl`); compact sticky header; `useElementWidth` hook drives responsive Plot charts (EvLaScatter + ChartBuilder fill containers, StadiumSprayChart caps at 720px); page-headers across 9 main pages collapsed from `text-3xl space-y-8` → `text-xl space-y-4` LSEG-uniform pattern. **Major architectural finding (D26)** — `<docs>/Out of the Park Developments/OOTP Baseball 27/` parent folder is a goldmine of reference data we'd been ignoring: `database/pt_ballparks.txt` (240 MLB+minors parks with 7-segment dimensions + LH/RH split park factors), `database/era_ballparks.txt` (3,105 rows × 155 years 1871-2025 historical park factors with handedness splits), `database/era_stats.txt` (82-col historical league averages per era), `stats/Master.csv` (24,747-row OOTP↔Lahman crosswalk including `lahmanID`/`BBrefMiLBid`/`retroID` — replaces our Chadwick crosswalk), `stats/MiLBMaster.csv` (29MB minor-league master), `database/db_structure_complete_ootp21_*.txt` (canonical schema docs), 1,829 logos in `logos/` (`.oi` files are PNGs — magic bytes confirmed) including per-era variants, 343 ballcaps, full uniform asset set. **D26 commits to an `L_REF` reference layer** sitting alongside L0-L3, ingesting from this parent folder once and joining into existing tables. **2026-05-13 evening also produced a meticulous deep-dive of the SAVE folder** (`<save>/<save_name>.lg/`) which surfaced `temp/text_data.sqlite3` (188MB SQLite, 4 years retained, contains `league_news` 16,718 / `team_news` 43,206 / `league_transactions` 149,769 / `team_transactions` 350,169 / `player_history` 314,678 / `league_injuries` 63,065 / draft logs / etc.) as a potential future augmentation source. Empirically determined that `news/html/box_scores/*.html` (18,982 files) and `replays/*.rpl` (6,481 files) are **EPHEMERAL — wiped each season as game_id resets**; do NOT depend on them. **D28 pins**: dumps remain primary; SQLite-backed `L_NEWS` layer is deferred until UX need pulls it in (would augment movements with OOTP's authoritative `transaction_type`, add player career bio timeline as new capability, add cockpit news ticker as new capability); ephemeral box-score-HTML and replay sources are deliberately ignored; `messages/` folder dropped per user preference. **2026-05-13 deep-dive expanded the L_REF scope (D27)** — `misc/` ships OOTP's canonical analytical lookup tables (`xwoba_table.txt`, `xba_table.txt`, `xslg_table.txt`, `re288_table.txt`, `wpa_table.txt`, `li_table.txt`, `xiso_table.txt`) which are the EXACT (LA, EV) → xwOBA / RE288 / WPA / LI tables OOTP itself uses at sim time; reading them directly guarantees our numbers match the in-game UI exactly. Also discovered `database/era_modifiers.txt` (per-year talent multipliers), `database/era_fielding.txt` (per-position FLD baselines), `database/total_modifiers.txt`, `database/financials.txt` (salary-bracket engine), `database/major_league_baseball.json` (authoritative league rules), `hof/index.json` + 8+ real HoF plaque PNGs, `colors/*.xml` (per-team brand palettes), `tables/*` (OOTP's saved column-layouts per view), `database/db_structure_ootp27_csv.txt` (version-current schema doc, replacing the ootp21 fallback we'd been using). **D27 pins L_REF as per-save, frozen at first ingest, opt-in refresh** (`diamond ingest --refresh-lref`) — mirrors OOTP's own engine convention of capturing reference data into the save at creation and ignoring subsequent install-folder edits. Slated as next major work — replaces `web/lib/stadiums.ts` with parsed `pt_ballparks.txt`, upgrades D22 park factors to era-aware LH/RH splits, swaps Chadwick crosswalk for Master.csv, swaps our hand-rolled xwOBA/RE/WPA math for OOTP's lookup tables, enables real-team-logo rendering everywhere. The reconciliation harness (`reconcile.py`) stays in the codebase as a permanent post-ingest regression check (Decision D8).

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

# Windows one-shot launcher — spawns both in their own windows + opens the browser
dev.bat

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
    app.py                  factory + CORS for localhost:3000 (GET + POST allowed)
    routes/                 one module per resource:
                              health, save, glossary, players, roster,
                              movements, standings, admin
    schemas/                Pydantic response models — single source of truth
    warehouse.py            per-process root DuckDB conn + cursor-per-request +
                            get_active_save() for save-level metadata
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
                            (sabermetric: woba/wraa/wrc/wrc+/ops+/owar/**bwar**;
                             fip/siera/era+/pwar/**p_war**/**p_ra9_war**)
                            + Statcast cohort tables (f_player_season_statcast_batting +
                            _pitching: bip/max_ev_p90/avg_ev/hh%/brl%/ss%, BIP ≥ 30)
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
    layout.tsx              top-nav (Club / League / World / History / Explore +
                            Glossary + ThemeSwitcher + Quit), no-flash theme init
    globals.css             theme tokens (light/dark/neutral/cb) under :root + [data-theme]
    page.tsx                **Cockpit dashboard** — save header + warehouse stats
                            + Sox division standings + top-3 MLB promotion/pressure
                            pairs + 6 spotlight cards with inline career-WAR sparklines
                            + auto-generated NLG insights + last 8 ledger rows.
                            Composed via /api/cockpit in one round-trip.
    (legacy)                — old tools-grid landing replaced 2026-05-12 by cockpit v2
    league/page.tsx         standings — sub-league × division × team
                            from `team_record_snapshot`, picker grouped
                            by level + year strip; org-row highlight.
                            Slim "Coming to League" stub strip below.
    world/page.tsx          TabStub
    history/page.tsx        TabStub (Records card linked to /history/records)
    history/records/page.tsx all-time leaderboards — scope × discipline ×
                            category × era pickers; UNIONs save + Lahman
                            + BREF + merged + Statcast records
    history/awards/page.tsx career trophy-case holders — league × award ×
                            era pickers; save (incl. OOTP-imported real
                            history) + cross-source merged real-life
                            (Lahman + MLB API)
    history/hof/page.tsx    Cooperstown — Inductees vs Candidates toggle
                            with count pills; inductees by year, candidates
                            top-N career WAR not yet inducted
    history/streaks/page.tsx 21 streak types × active|all_time scopes;
                            top-50 holders pre-cut at L3 build time;
                            "Live" badge on active streaks
    history/draft/page.tsx  per-year draft retrospectives — class
                            summary header + outcome-bucketed roster
                            (MLB Regular / Callup / Still Developing /
                            Traded / Released / Retired); year picker
                            defaults to oldest class with material
                            outcomes
    explore/page.tsx        TabStub
    glossary/page.tsx       D15 dictionary list
    glossary/[id]/page.tsx  single-stat detail with KaTeX-rendered formulas
    player/[id]/page.tsx    Bref-style player page (Stats tab — batting/pitching/fielding/advanced)
    roster/page.tsx         server page — fetches /api/roster, hands off to RosterClient
    movements/page.tsx      ledger — call-ups / send-downs / acquisitions / departures
    pressure/page.tsx       per-level promotion-candidates + pressure-cases
                            cards; org-scoped, OPS+/ERA+ as rate metric
                            with delta-vs-100 coloring
  components/
    PlayerStatsTab.tsx      client component — disclosure-row tables for the player Stats tab
                            + Defensive Profile section (per-position 20-80 cube)
    RosterClient.tsx        client component — three filter pills (Level/Role/Hand) + three-mode
                            stat toggle (Basic/Advanced/Contact); dense Bref-style tables
    FormulaBlock.tsx        KaTeX wrapper with parse-fail fallback
    ThemeSwitcher.tsx       client component — light/dark/neutral/cb dropdown, localStorage-persisted
    QuitButton.tsx          client component — POSTs /api/admin/shutdown
    TabStub.tsx             header + section grid for IA stubs (now used
                            by world/history/explore — League graduated
                            to a real page on 2026-05-11)
  lib/
    api.ts                  typed fetch helpers (one per endpoint; throw on non-2xx)
    types/api.ts            AUTO-GENERATED — do not hand-edit
  tailwind.config.ts        semantic-color extension (surface/content/border/accent/link)
                            + darkMode: ["class", '[data-theme="dark"]']
```

Every data-fetching page **must** `export const dynamic = "force-dynamic"`. Without it, Next's default static prerender at `next build` time calls the API while uvicorn isn't running and fails with `ECONNREFUSED`. See `docs/DEV.md` "Adding a new API route" for the canonical recipe.

**API surface today** (28 endpoints): `/api/health`, `/api/save`, `/api/cockpit`, `/api/glossary`, `/api/glossary/{id}`, `/api/players/{id}` (also returns per-position fielding cube + service-time/roster-status block + situational-batting splits + active contract block), `/api/players/{id}/batted_balls?year=&level_id=` (BIP events for spray + EV-LA), `/api/roster`, `/api/movements?year=YYYY[&include_pending=1]`, `/api/standings?league_id=&year=`, `/api/records?scope=&discipline=&category=&era=&limit=`, `/api/awards?league_id=&award_id=&era=&limit=`, `/api/hof?view=&limit=`, `/api/streaks?streak_id=&scope=&limit=`, `/api/draft?year=`, `/api/pressure?year=&limit=`, `/api/compare?ids=`, `/api/leaderboards/options`, `/api/leaderboards?stat=&year=&level_id=&league_id=&pa_min=&limit=`, `/api/chart-builder?x=&y=&color=&year=&level_id=&league_id=&qualifier_min=&limit=`, `/api/saves`, `POST /api/saves/active`, `GET/POST /api/saves/{name}/config` (per-save audit_team_id + scope persistence — D3 v2.1), `/api/ai/settings`, `POST /api/ai/settings`, `POST /api/ai/summarize`, `/api/photos/players/{id}.png` (revalidation-cached, D24), `GET /api/admin/dump-status`, `POST /api/admin/ingest` (auto-detects + ingests new dumps mid-session), `POST /api/admin/shutdown`.

### Warehouse layers

```
L0  raw     69 tables    one-to-one with dump CSVs (read_csv_auto, dynamic CTAS)
                         Note: 70 CSVs in dump, 69 in L0 — `players_pitching.csv` is
                         not ingested. All its rating cols are zeroed in this save
                         (scouting mode), so no actionable data lost. See DATA_NOTES.
L1  conformed
    machinery   _scoped_teams + _scoped_players (D13: org tier UNION ≥1 MLB appearance)
    reference   12 tables (teams, leagues, parks, ...)
    event       35 tables (collapsed dups; PK on natural key)
    snapshot    21 tables + 7 _current views
                (incl. `players_fielding_current` over `players_fielding_snapshot`,
                 added 2026-05-10 to back the Defensive Profile section on the
                 player page — surfaces `fielding_rating_pos1..9` + `_pot` +
                 `fielding_experience1..9`. Convention: zero values = "never
                 rated / never played there" — surfaced as null in the API so
                 the UI can render em-dashes unambiguously.)
L2  facts   8 tables (f_player_season_*, f_player_career, f_team_season,
                      f_league_season, f_pa_event, f_award_event)
                      — note: `f_pa_event` is multi-year as of 2026-05-12,
                      sourced from L0 directly with cross-dump dedup keyed
                      on (game_id, season_year). PK = (year, game_id,
                      batter_id, pa_in_game_seq) — `year` is in the key
                      because OOTP recycles `game_id` across seasons.
L3  derived 11 tables — trade_participant, player_movements, draft_class,
                       record_player, award_career_player, award_franchise,
                       player_streak, **f_player_season_advanced_batting +
                       _advanced_pitching** (sabermetric stack per player+year+
                       league+level: park-aware wOBA/wRAA/wRC/wRC+/OPS+/oWAR
                       + **bWAR** for batters [bWAR = OOTP's directly-supplied
                       combined WAR — offense + defense + position + base-running,
                       IE-A-tier reconciled]; FIP/SIERA/ERA+/pit_WAR + **pWAR**
                       + **RA9-WAR** for pitchers [pWAR = OOTP FIP-WAR with
                       leverage adjustment; RA9-WAR = runs-based parallel]),
                       **f_player_season_statcast_batting + _pitching** (Statcast
                       cohort: BIP / max_EV_P90 / avg_EV / hard_hit% /
                       sweet_spot% / barrel%; BIP ≥ 30 quality threshold;
                       materialized from f_pa_event)
History (one-time) lahman / bref / statcast / mlbapi / chadwick crosswalk
L_REF (planned, D26+D27) per-save reference data, frozen at first ingest
                  (write-once for save lifecycle; refresh via
                  `diamond ingest --refresh-lref`). Ingested from
                  `<docs>/Out of the Park Developments/OOTP Baseball 27/`:
                    misc/{xwoba,xba,xslg}_table.txt — OOTP's (LA, EV) → x-stat
                                                      lookup tables (replaces
                                                      our hand-rolled xwOBA math)
                    misc/re288_table.txt           — RE288 by (outs, bases, count)
                    misc/{li,wpa}_table.txt        — leverage + win prob tables
                    misc/xiso_table.txt            — Statcast 6-zone classifier
                    pt_ballparks (240 parks, 7-segment dimensions + LH/RH PFs)
                    era_ballparks (3,105 historical park-seasons 1871-2025)
                    era_stats / era_stats_minors (82-col league averages per era)
                    era_modifiers / era_fielding / total_modifiers (per-year
                                                                    multipliers)
                    financials.txt (OOTP salary-bracket engine)
                    Master / MiLBMaster (OOTP↔Lahman crosswalk; replaces Chadwick)
                    db_structure_ootp27_csv.txt (version-current schema doc)
                    major_league_baseball.json (authoritative league rules)
                    hof/index.json + plaque PNGs (real HoF photos)
                    colors/*.xml (per-team brand palettes)
                    logos/ + ballcaps/ + jerseys/ assets
```

The audit layer (Phase 1) is **scaffolding**. Advanced stats now run against the warehouse via `f_player_season_advanced_*`; the formulas in `src/diamond/advanced/` remain canonical for the audit harness + ad-hoc Polars/SQL paths.

### Configuration

- `src/diamond/config.py` defines `SaveConfig` (paths + scoped league IDs) and the singleton `BUILDING_THE_GREEN_MONSTER` for the active save (15 league IDs: MLB org tree + DSL + AFL).
- The OOTP saves root is hardcoded to `C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games`. Per save, the layout is `<save>/dump/dump_<YYYY>_<MM>/csv/*.csv` (monthly snapshots) and `<save>/import_export/*.csv` (the OOTP-generated reference roster CSVs we reconcile against). Per D2 the warehouse lives at `<save>/diamond/diamond.duckdb`.
- Per Decision D3, scope is hardcoded for v1 but a save-setup picker is a hard v2 requirement — keep the scoping mechanism in `SaveConfig`, not inline. **D3 v2.1 (2026-05-13)** lands per-save audit_team_id + league_ids in `~/.diamond/save_configs.toml`; `build_save_config(save_name)` constructs the live SaveConfig from persisted state, with bootstrap migration for the legacy `BUILDING_THE_GREEN_MONSTER` default.
- **OOTP parent-folder reference data (D26 + D27)** — `<docs>/Out of the Park Developments/OOTP Baseball 27/` contains ~500MB of static reference data spanning analytical lookup tables (`misc/xwoba_table.txt` + 6 sibling tables — OOTP's canonical (LA, EV)/RE288/WPA/LI math), historical baselines (`database/era_stats.txt` 82-col league avgs, `era_stats_minors.txt`, `era_modifiers.txt`, `era_fielding.txt`), authoritative park data (`pt_ballparks.txt` + `era_ballparks.txt` with handedness splits — beats hand-coded `web/lib/stadiums.ts` and Lahman BPF), crosswalks (`stats/Master.csv` — OOTP↔Lahman, replaces Chadwick), engine config (`major_league_baseball.json` — authoritative league rules; `financials.txt` — salary brackets), schema docs (`database/db_structure_ootp27_csv.txt` — version-current; we'd been working from ootp21), real HoF plaques (`hof/index.json` + 8+ PNGs), per-team brand colors (`colors/*.xml`), and 1,829 logos in `logos/` (`.oi` files are PNGs — magic bytes confirmed). v2 architecture introduces an **`L_REF` ingest layer** sitting alongside L0-L3. **Per D27, L_REF is per-save and frozen at first ingest** — `diamond ingest` snapshots reference data into `<save>/diamond/diamond.duckdb` once, then ignores subsequent install-folder edits unless the user explicitly opts into `diamond ingest --refresh-lref`. This mirrors OOTP's own engine convention (save reference data is captured at save creation; mid-version patches don't retroactively change running saves) and makes "why did Bonds 2001 OPS+ shift between yesterday and today?" a non-question. Treat the parent folder as **read-only canon**; never write into it.

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

### Information architecture (D17)

Top-nav structure committed 2026-05-08 — five tabs that everything else hangs off:

- **Club** (`/`) — your org. The landing is now the **cockpit dashboard** (2026-05-12) — save header + warehouse stats + Sox division standings strip + top-3 MLB promotion/pressure pairs + spotlight cards (career-WAR sparkline + NLG insight per card) + recent moves feed. Composed in one round-trip via `/api/cockpit`. Year is implicit (latest); historical snapshots stay on dedicated tabs.
- **League** (`/league`) — your scoped leagues. Stub today; standings + leaderboards + awards races + free agents land here.
- **World** (`/world`) — every league in the save. Stub; for users who follow international ball.
- **History** (`/history`) — past seasons. Stub; will absorb the existing CLI surfaces (`diamond records / awards / hof / streaks / draft <year>`).
- **Explore** (`/explore`) — sandbox. Stub; Compare / distributions / spray charts / EV-LA scatter / chart builder / cohorts.

Plus **Glossary** (cross-cutting reference), **Player pages** (`/player/[id]` — a *target*, not a peer view; reachable from Club roster, League leaderboards, History HoF list, etc.), **ThemeSwitcher**, and **Quit** in the header.

Build rule: **new top-level features land under one of the five prefixes** (or as cross-cutting like glossary). Don't create more `/some-tool` orphan routes. Existing flat routes (`/movements`, `/glossary`, `/player/[id]`) can be renested when their natural parent tab gets richer content.

### Visual primitives (2026-05-12)

Reusable building blocks for richer table + card rendering, all in
`web/`. Use these instead of one-off color logic / inline SVG when
adding new tables, leaderboards, hero cards, or player references.

- **`lib/heatscale.ts`** — `plusMinusClass(value)` for any 100-relative
  metric (OPS+ / wRC+ / ERA+ / FIP+) and `warSeasonClass(war)` for
  single-season WAR cells. Five-tier gradient per side with bg-fill
  at the extremes. Apply via Tailwind className concat:
  ``className={`px-2 py-1.5 ${plusMinusClass(row.ops_plus)}`}``.
  Wired into roster Advanced view, player Advanced section,
  pressure board metric column, cockpit pressure summary +
  spotlight headline numbers, compare card headline metric.
- **`components/Sparkline.tsx`** — tiny inline SVG trend chart. Pure
  polyline + dots, auto-trend coloring (emerald rising, rose falling,
  sky flat). Drop into any row that wants a "trajectory at a glance":
  `<Sparkline values={[3.1, 4.5, 6.2, 5.8]} width={120} height={32} />`.
  Used on cockpit spotlight cards + compare cards.
- **`components/CareerArc.tsx`** — full SVG line chart of career
  WAR by year, with dot fills picked from heat-scale, peak-tier
  reference band, year-axis ticks, and HTML tooltips per dot.
  Hard-rolled at ~250 LOC; chosen over a chart-library dependency
  for v1 since the shape is simple and bundle stays small. Sits
  between bio header and tab strip on `/player/[id]`. The Vega-Lite
  vs Plotly chart-stack decision (UI_DESIGN.md §3) is still pending
  and will land when we need spray charts / EV-LA scatters /
  distribution viz; until then, hand-rolled SVG is the convention
  for the simpler trend shapes.
- **`components/PlayerAvatar.tsx`** *(2026-05-12)* — circular
  headshot with initials fallback. Streams the OOTP-generated face
  PNG via `/api/photos/players/{id}.png`; on 404 renders a
  deterministic-color initials disc. Sizes: xs (20px) / sm (32px)
  / md (48px) / lg (80px). Wired into player page header,
  cockpit spotlight cards, roster name cells, compare cards.
- **`components/PlayerContractCard.tsx`** *(2026-05-12)* — salary-by-
  year bar viz with option badges, no-trade chip, and total /
  remaining USD totals. Renders the active contract from
  `PlayerContract` payload on the player page (between CareerArc
  and the tab strip). Skipped for players without an active
  contract row (amateurs / FAs / retirees).

### Theme system (D18)

Four themes via CSS variables on `<html data-theme="...">` — `light`, `dark` *(default)*, `neutral` (warm cream), `cb` (Wong-palette color-blind safe). Tailwind config exposes semantic tokens via `colors:` extension:

- Surface: `bg-surface-page` / `bg-surface-card` / `bg-surface-elevated`
- Text: `text-content-primary` / `text-content-secondary` / `text-content-muted`
- Border: `border-border` / `border-border-strong`
- Accent: `text-accent` / `bg-accent` / `text-link` / `hover:text-link-hover`

**Convention**: write semantic tokens, not raw `slate-*` / `white` / etc. The exception is verdict-color badges (emerald / amber / rose / indigo / sky for working / down / struggling / trade / FA) which keep the named-Tailwind palette but pair with `dark:` overrides per badge — `dark:bg-emerald-900/40 dark:text-emerald-300` etc. Tailwind config has `darkMode: ["class", '[data-theme="dark"]']` so the `dark:` prefix fires on the dark theme.

**No-flash init**: an inline `<script>` in `<head>` (in `app/layout.tsx`) reads `localStorage["diamond.theme"]` synchronously before body paints and stamps `data-theme`. Don't remove it; without it every reload flashes the default theme for ~50ms.

**v1 limitation**: CB mode is chrome-only — accent + link colors are Wong-safe blue/orange, but verdict glyphs and move-type badges still use the green/amber/rose convention. Full CB swap is a backlog item.

### Stat dictionary (D15)

`src/diamond/dictionary/STATS` is the **only** place stat metadata lives. Every column header, chart axis, glossary tooltip, and AI prompt reads from `STATS[id]` — never hand-coded. As of 2026-05-10 the dictionary covers 62 entries (slash + counting batting/pitching, fielding counting + FPCT + RF/9, the league-relative advanced stack including wOBA/wRC+/OPS+/FIP/ERA+/SIERA, custom oWAR + pit_WAR + the OOTP-supplied bWAR/pWAR/RA9_WAR triplet, and the Statcast EV/barrel cohort).

Strict rule: any new UI label MUST come from the dictionary. Adding a new stat = add an entry to `_stats.py`. The smoke test's Phase G validates required-fields-non-empty + categories valid + related-id resolution + id uniqueness.

### Adding a new API route (the canonical recipe)

Per `docs/DEV.md`:
1. Define the Pydantic response model in `src/diamond/api/schemas/<resource>.py`. Re-export from `schemas/__init__.py`.
2. Create `src/diamond/api/routes/<resource>.py` with a `router: APIRouter` and your handler functions.
3. Wire `app.include_router(<resource>.router, prefix="/api", tags=[...])` in `src/diamond/api/app.py`.
4. Run `make types` to regenerate `web/lib/types/api.ts`.
5. Add a typed fetch helper in `web/lib/api.ts`, then consume it from a server component under the appropriate IA tab (per D17: Club / League / World / History / Explore — don't create new top-level orphan routes).
6. **Mark the page dynamic** — `export const dynamic = "force-dynamic"` on every data-fetching page (otherwise `next build` fails with ECONNREFUSED).
7. **Use semantic theme tokens** (per D18) — `bg-surface-page`, `text-content-primary`, `border-border`, `text-link`, etc. Don't write raw slate / white classes; they break in dark/neutral/cb modes.

The glossary endpoint is the canonical reference implementation. The player endpoint is the canonical reference for warehouse-backed routes (depends on `get_cursor` from `api/warehouse.py`). The movements endpoint is the canonical reference for org-scoped routes (uses `get_active_save()` to read `audit_team_id`). The save endpoint is the canonical reference for save-metadata-only routes. The roster endpoint is the canonical reference for routes that return a single big JOIN payload for client-side filtering — when in doubt, ship the whole thing in one round-trip and let the client do the slicing.

### Stat-mode toggle pattern (roster page)

The roster page introduces a **three-position stat-mode toggle** (`Basic / Advanced / Contact`) for tables that need to expose multiple personalities of stats. Reuse the pattern wherever a dense table would otherwise need a basic/advanced toggle — three slots is the natural decomposition for this codebase given the warehouse coverage:

- **Basic** — counting + slash / counting + ERA-WHIP-K9-BB9.
- **Advanced** — sabermetric stack: wOBA / wRAA / wRC / wRC+ / OPS+ / **bWAR** + park (batters); FIP / SIERA / ERA+ / **pWAR** + park (pitchers). bWAR/pWAR are OOTP-canonical (IE-reconciled, A-tier); the offense-only oWAR + custom-FIP `pit_WAR` live in the player page Advanced sections + glossary as inspectable alternatives — gap reveals defensive component / leverage-replacement scaling.
- **Contact** — Statcast cohort: BIP / max EV (P90) / avg EV / HH% / Brl% / SS%. Pitcher rows interpret all percentages as *allowed-contact* (lower = better).

See `web/components/RosterClient.tsx` for the canonical implementation.

## Conventions and gotchas

- The `players_at_bat_batting_stats` log has `result` codes 1=K, 2=BB, 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR, 10=HBP, 11=CI. BIP excludes sacrifices (`sac > 0`).
- `import_export` files are named with the team-org prefix (`boston_red_sox_organization_-_roster_*.csv`). They were generated by OOTP and exist alongside `dump/` in the save folder.
- The November dump (`dump_YYYY_11`) is the end-of-season snapshot — it's the canonical source for season-stat reconciliation. Earlier monthly dumps roll over at season start (Feb-Mar).
- DSL teams: the Red Sox have one FCL + two DSL teams; org-level rollups must include all three.
- Park factors: **halved** for OPS+ / wRC+ (`1 + (avg-1)/2`), **80%** for ERA+ / pit_WAR (`1 + (avg-1)*0.8`). Audit-decoded; verified Crochet 2029 ERA+ 127 vs IE 127 (Fenway).
- **OOTP supplies WAR directly** as `players_career_*.war` / `.ra9war` (A-tier reconciled to IE since 2026-05-04). Aggregated into `f_player_season_*.war` + `.ra9war`, then SUMed into `f_player_season_advanced_batting.b_war` + `f_player_season_advanced_pitching.p_war` / `.p_ra9_war`. Surfaced on roster Advanced + player page Advanced. The custom `o_war` (offense-only, wRAA-based) + `pit_war` (FIP-only, flat-1.13-replacement) are NOT the canonical IE-reconciled values — they're inspectable alternatives kept for transparency. When users ask "what's player X's WAR?", the answer is `b_war` / `p_war`.
- League constants are per `(league_id, year, level_id)` — never roll up across levels. AAA wOBA uses AAA constants, not MLB's. (D11)
- League history coverage in this save is **2026-2029**. Pre-2026 MLB player rows (level_id=1, league_id=203) get baselines from the **D20 imported view** (Lahman 1871-2019 + BREF 2020-2025 UNIONed into `_lg_constants_advanced` via `_lg_constants_advanced_imported`), so advanced stats render real values for OOTP-imported real-history seasons. Pre-2026 *minor-league* rows still render `—` for advanced stats — Lahman has spotty minor-league coverage and the OOTP↔real league_id crosswalk for IL/PCL/etc. isn't bijective; deferred backlog item. Park factors for pre-2026 use the team's *current-day* `parks.avg` (modern-stadium proxy), so OPS+/ERA+ have small per-park bias but wOBA/wRC+/wRAA are unaffected.
- **Statcast EV scale runs ~5 mph below real Statcast.** OOTP league-avg EV ~83 mph vs real ~88-89; save's top-end avg-EV stars sit ~5-7 mph below their real counterparts. HARD_HIT_PCT scales proportionally lower (save Judge 34% vs real Judge ~65%). When `f_record_player` UNIONs save EV records with `history_statcast_*`, the source column distinguishes the two scales — don't compare them numerically without converting.
- **`max_ev` in `f_player_season_statcast_batting/_pitching` is the 90th-percentile EV**, not the absolute peak — Statcast convention; absolute peak is dominated by single-event noise.
- **`players_pitching.csv` is in the dump but not in L0.** All rating columns are zeroed in this save because scouting mode is enabled. Defensive ingest fix only; no actionable data lost. See DATA_NOTES.md "players_pitching.csv" section.
- `audit_output/` is gitignored. Reports are regenerable from CLI; commit the *generators*, not the outputs.
- `.env` exists locally and is gitignored — GitHub push protection has blocked it before. Don't `git add -A` blindly.
- `docs/screenshots/` is gitignored — user-local context, not part of the repo's permanent record.
