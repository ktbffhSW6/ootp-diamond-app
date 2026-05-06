# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-09 (in-game year 2029→2030) — **Phase 3: roster page shipped + advanced/Statcast surface expanded.** Roster page (`/roster`) closes the player-page navigation loop: every active org-tree player grouped by current level, dense Bref-style tables with three-way filters (Level / Role / Hand) and a **three-mode stat toggle (Basic / Advanced / Contact)**. Advanced view added the wRAA / wRC / park-factor columns that were sitting in `f_player_season_advanced_batting` but never surfaced. **SIERA materialized in L3** (`f_player_season_advanced_pitching.siera`, Fangraphs canonical regression — Crochet 2.25 vs IE-reconciled 2.27 ±0.02). **Two new L3 Statcast cohort tables** — `f_player_season_statcast_batting` (3,790 rows) + `_pitching` (3,880 rows) — materialized from `f_pa_event` (which had `exit_velo` + `launch_angle` populated 100% on BIP rows all along; ~574K BIP across the warehouse). Surfaced via the new Contact mode: BIP / Max EV (P90) / Avg EV / HH% / Brl% / SS%, with pitcher rows reading as "allowed contact." **Full dump-CSV audit ran 2026-05-09**: every dump CSV cross-checked against L0 + every L0 column scanned. Findings: `players_pitching.csv` not ingested (67 cols, **but all rating values zeroed in this save because scouting is enabled** — defensive ingest fix only, no actionable data); `l0_players_fielding` carries per-position fielding ratings (`fielding_rating_pos1..9`), per-position ceilings (`_pot`), and per-position experience (`fielding_experience0..9`) — fully populated in `players_fielding_snapshot` and **never read** by any L2/L3/UI surface. That's the highest-value find of the audit. **Next: combined bWAR/pWAR slice** (revised feasibility — `zr` + `framing` + `arm` already in fielding fact, half-day not multi-week) followed by per-position fielding view + service-time/contract surface.

---

## One-line summary

Phases 1-2 closed; analytical CLI surface complete; real MLB history through 2025 backfilled; Phase 3 UI live — five-tab IA (Club / League / World / History / Explore) wired into the layout; Club landing renders save metadata + tools grid; movement ledger covers all four direction buckets; **roster page shipped (2026-05-09) — full org tree grouped by level with Basic/Advanced/Contact stat-mode toggle, closes player-page navigation loop**; player page Stats tab full (batting / pitching / fielding / advanced); theme system supports light / dark / neutral / color-blind with dark as default; in-app Quit reliably kills both dev servers. **L3 Statcast cohort + SIERA materialized 2026-05-09**, surfacing the Statcast quintet (max_EV / avg_EV / HH% / Brl% / SS%) on the roster Contact mode. Combined bWAR/pWAR is the natural next slice (revised feasibility: half-day, not multi-week — `zr` + `framing` + `arm` already in fielding fact).

## What works today

- **Project skeleton**: Python 3.14 + DuckDB + Polars + Typer; package at
  `src/diamond/`; editable install via `pip install -e .[dev]`.
- **CLI**: `diamond decode`, `diamond decode-codes`, `diamond reconcile`,
  `diamond coverage`, `diamond advanced`, `diamond ingest`,
  `diamond draft`, `diamond records`, `diamond awards`, `diamond hof`,
  `diamond fetch-history` (Lahman + Statcast one-time backfill).
  All audit/report commands write markdown to `audit_output/` (gitignored).
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py))
  — per-column comparison of all 21 `import_export` Red Sox roster CSVs against
  derivations from monthly dump CSVs across the full 220-player Red Sox org tree
  (MLB + AAA + AA + A+ + A + Rookie + 2 DSL + FCL). 16 of 21 files at 100% A+B.
  See scorecard below. This stays in the codebase as a permanent regression
  check (Decision D8).
- **Verified codebooks** ([src/diamond/constants.py](src/diamond/constants.py))
  — `GameType`, `SplitId`, `AtBatResult` (at-bat domain); `AwardId` (13 codes
  cross-ref'd with league_history), `LeaderCategory` (47 of 60), `StreakId`
  (21 profiled), `BodyPart` (12 profiled); `Popularity`, `ScoutingAccuracy`,
  personality bucket helper.
- **Advanced stats library** ([src/diamond/advanced/](src/diamond/advanced/))
  — 5 tiers of modern advanced stats from at-bat data (~25 metrics). Per-tier
  modules: `contact.py`, `situational.py`, `sabermetric.py`, `defensive.py`,
  `approach.py`. Shared at-bat view in `enriched.py`; advanced-lib-scoped
  per-league-year linear weights / FIP const / lgERA in
  `advanced/league_constants.py` (kept for now — produces wOBA-scale calibration
  the audit derivation doesn't need; consolidation is a post-warehouse task).
- **League-constants module** ([src/diamond/league_constants.py](src/diamond/league_constants.py))
  — top-level module that registers two DuckDB views (`lg_constants_bat`,
  `lg_constants_pit`) sourced from `league_history_*` and keyed by
  `(league_id, year, level_id)` per Decision D11. Replaces the inline CTEs
  formerly in `reconcile.py`. Verified byte-identical reconcile output post-refactor.
- **5-layer warehouse DDL** ([src/diamond/schema/](src/diamond/schema/))
  — full `build_l0` / `build_l1_machinery` / `build_l1_reference` /
  `build_l1_event` / `build_l1_snapshot` / `build_l2` pipeline. Each
  module holds its layer's specs and builders. `scripts/smoke_warehouse.py`
  exercises the full pipeline end-to-end against the latest dump in <60s,
  asserting layer invariants (PK enforcement, scope filters, dim flatten,
  D12 scouted-rating filter, idempotency). Layer counts:
  - L0: **69 raw tables** (5.76M rows from one dump)
  - L1: 12 reference + 35 event + 21 state-snapshot + 6 `_current` views + 2 machinery (`_scoped_*`) + 1 admin (`_diamond_ingests`)
  - L2: 8 facts (`f_player_season_batting/pitching/fielding`, `f_player_career`,
    `f_team_season`, `f_league_season`, `f_pa_event`, `f_award_event`)
  - L3: 10 derived (`f_trade_participant`, `player_movements` w/ `trade_id`,
    `f_draft_class`, `f_record_player`, `f_award_career_player`,
    `f_award_franchise`, `f_player_streak`,
    `f_player_season_advanced_batting` + `_advanced_pitching` [the
    sabermetric stack — wOBA/wRAA/wRC/wRC+/OPS+/oWAR for batters; FIP
    + **SIERA** + ERA+/pit_WAR for pitchers; park_avg on both],
    **`f_player_season_statcast_batting` + `_pitching`** [BIP / max_EV
    P90 / avg_EV / hard_hit% / sweet_spot% / barrel% per (player, year,
    league, level), 30-BIP minimum, materialized from `f_pa_event`])
  - History backfill (one-time): 8 `history_lahman_*` tables +
    2 `history_statcast_*` tables + 2 `history_bref_*` tables +
    2 `history_mlbapi_*` tables (awards + HOF gap-fill 2018+) +
    `history_player_id_map` (Chadwick Register). f_record_player
    UNIONs five sources ('save' / 'lahman' / 'bref' / 'statcast' /
    'merged') with `--era` CLI filter. Career rows dedup across
    sources via bbref_id crosswalk: save wins for active players;
    Lahman + BREF + Statcast merge into 'merged' source for
    pre-save retirees (Pujols Lahman 656 + BREF 30 = merged 686 HR).
    Statcast adds EV/barrel/hard-hit categories.
    f_award_career_player UNIONs save + lahman + mlbapi (with
    same dedup-on-bbref_id-in-save filter for the gap-fill rows).
    `diamond hof --era lahman` shows real Cooperstown through 2026.
- **Empirical scripts retained** in `scripts/` — `xstats_eda.py` and
  `xstats_3d.py` are the evidence behind the structural-limit D-tier verdict
  on xBA/xSLG/xwOBA. Rerun rather than re-investigate.

## Phase 1 — Audit, closed 2026-05-04

Headline reconciliation: of ~360 IE columns,
- **~270 reconcile cleanly (A/B)**
- **0 C-tier**, **0 G-tier** — all formula puzzles and int→string mappings decoded
- ~50 F-tier by design (Decision D5: plate-discipline columns; string-formatted display)
- ~7 D-tier (xBA/xSLG/xwOBA/xERA — confirmed structurally non-derivable; see DATA_NOTES)
- ~25 E-tier partial (multi-level slash-line gaps, hit_xy spray boundary — research items)

Major decodes shipped during audit (full formulas in [DATA_NOTES.md](DATA_NOTES.md)):
- DEF rating, popularity, personality buckets, scouting accuracy, VELO band, G/F bucket
- OPS+, ERA+, FIP, RC, RC/27, wOBA via `league_history_*` + halved/non-halved park factors
- SIERA via Fangraphs canonical formula (quadratic + interaction terms)
- pLi (cumulative, not average), RA (g-gs), RSG (rs/gs)
- EV buckets (75/95), Barrel (flat threshold not Statcast cone), regular-season filter, PCB-derived BIP
- Contract data via `players_contract_extension` + `players_roster_status`; current_year is 0-indexed

## Reconciliation status (frozen at audit close)

| File | Reconciled | Outstanding |
|---|---|---|
| `batting_stats_1` | **24/24** | — |
| `batting_stats_2` | **18/18** | — |
| `pitching_stats_1` | **25/25** | — |
| `pitching_stats_2` | **26/26** | — |
| `fielding_stats` | **12/12** | — |
| `batting_ratings` | **18/18** | — |
| `batting_potential` | **11/11** | — |
| `pitching_ratings` | **12/12** | — |
| `pitching_potential` | **10/10** | — |
| `fielding_ratings` | **9/9** | — |
| `individual_pitch_ratings` | **15/15** | — (Sprague PIT 1/220 edge case — see BACKLOG) |
| `individual_pitch_potential` | **15/15** | — |
| `position_ratings` | **10/10** | — |
| `popularity_info` | **6/6** | — |
| `personality___morale` | **6/6** | — (4 fresh-acquisition Unknowns expected) |
| `financial_info` | **12/12** | — |
| `batting_superstats_1` | partial 22/25 | xBA/xSLG/xwOBA D-tier closed; spray E-tier |
| `pitching_superstats_1` | partial 13/17 | xBA/xSLG/xwOBA/xERA D-tier closed |
| `batting_superstats_2` | **3/20** | 17 plate-discipline F-tier per D5 |
| `pitching_superstats_2` | **3/19** | 16 plate-discipline F-tier per D5 |
| `default` | 3/6 | 3 string-formatted display fields F-tier |

Latest reports (regenerable, gitignored): `audit_output/{decoder,codes_decoder,reconciliation,coverage,advanced_stats}_report.md`.

## Phase 2 + analytical layer — closed 2026-05-06

Phase 2 (schema + ingest) closed 2026-05-05; the analytical layer + real-MLB
history backfill closed same-day 2026-05-06. Major shipped artifacts:

**L3 derived tables** (7):
- `f_trade_participant` — 1,275 rows; 1 per (trade × player)
- `player_movements` — 95,643 rows; refined `movement_type` (promotion / demotion /
  intra_org_lateral / waiver_or_other / trade) + `trade_id` attribution
- `f_draft_class` — 2,320 rows; outcome buckets (mlb_star/mlb_regular/mlb_callup/
  in_draft_org/traded_away/released/retired)
- `f_record_player` — 4,700 rows; UNIONs save + lahman + bref + statcast + merged
  with `--era` CLI filter; bbref_id career dedup. New `direction` column drives
  ASC vs DESC ranking (pitching contact-allowed rate stats sort ASC, "Fewest" wins).
  Save-side EV (MAX_EV/AVG_EV/HARD_HIT_PCT) computed off `f_pa_event` with
  50-BBE qualifier; calibration ~5 mph below Statcast scale (documented in
  DATA_NOTES.md).
- `f_award_career_player` — 9,953 rows; UNIONs save + merged (Lahman+mlbapi
  collapsed via bbref_id; merged filtered to non-save bbref_ids to avoid
  active-player double-count via OOTP historical-seed import).
- `f_award_franchise` — 1,856 rows
- `f_player_streak` — 2,098 rows; top-50 per (streak_id × scope), where
  scope ∈ {active, all_time}. `streak_label` from `StreakId` IntEnum.

**Real MLB history backfill** (one-time, capped at save_start_year - 1 = 2025):
- Lahman 1871-2019 (8 tables via cdalzell mirror)
- BREF 2020-2025 (2 tables via pybaseball — fills the Lahman cap)
- Statcast 2015-2025 (2 tables via Savant — EV / barrel / hard-hit)
- MLB Stats API 2018+ awards + 2019+ HOF (2 tables — fills Lahman award/HOF cap)
- Chadwick Register (1 table — bbref ↔ MLBAM crosswalk for cross-source linkage)

**CLI surface**:
- Audit: `decode`, `decode-codes`, `reconcile`, `coverage`, `advanced`
- Ingest: `ingest [<dump>] [--all] [--rebuild-only] [--force] [--no-rebuild]`
- Analytics: `draft <year> [--team]`, `records [--era] [--scope] [--category]`,
  `awards [--era] [--player] [--bbref-id] [--team] [--award]`,
  `hof [--era] [--candidates]`,
  `streaks [--all-time] [--category]`
- Setup: `fetch-history` (one-time real-history backfill, idempotent)

## What's next — Phase 3 (UI implementation)

Per [UI_DESIGN.md](UI_DESIGN.md). Build order:

1. ✅ **D13 reference scope expansion** — done 2026-05-07.
2. ✅ **D15 stat dictionary** thin v1 — done 2026-05-07. 39 entries.
3. ✅ **D16 tech stack pick** — done 2026-05-07. FastAPI + Next.js
   (App Router) with Pydantic-derived TS types.
4. ✅ **API + web scaffold** — done 2026-05-07, **verified live**:
   - Backend (`src/diamond/api/`) — FastAPI app + glossary + health
     routes + Pydantic schemas. `/api/health`, `/api/glossary`,
     `/api/glossary/{id}`, 404 path all live.
   - Frontend (`web/`) — Next.js 15 App Router + Tailwind + KaTeX
     + react-katex. Glossary list + detail pages render server-side
     against the live API; `pnpm build` succeeds clean.
   - Type-gen (`scripts/generate_types.py`) — Pydantic → TS pipeline
     working; `make types` overwrites `web/lib/types/api.ts` with
     auto-generated content carrying Pydantic docstrings as JSDoc.
   - Dev workflow (`Makefile` + `docs/DEV.md`) — `make api`, `make
     web`, `make types`, `make smoke` documented. Two-terminal flow.
   - Frontend dev deps installed on this machine: Node 24, pnpm 10,
     web/node_modules complete.
5. ✅ **Player page Stats tab — batting + pitching + fielding** — done 2026-05-07.
   - `GET /api/players/{player_id}` returns bio + per-(year, level,
     team) batting + pitching stints with synthesized per-season
     "TOT" rows + per-(year, position, team) fielding rows + career
     rollups (batting/pitching cross-year, fielding per-position).
     One big payload, one fetch. Pydantic schemas in
     `src/diamond/api/schemas/player.py`; route in
     `src/diamond/api/routes/players.py`; warehouse connection
     pool in `src/diamond/api/warehouse.py`.
   - `/player/[id]` page (URL uses internal `player_id`). Server
     component fetches player + glossary in parallel. Bio header,
     tab strip (Stats active; others placeholder), and three
     stacked stat sections.
   - `web/components/PlayerStatsTab.tsx` (client component):
     - **Batting / Pitching**: Bref-shaped disclosure-row tables.
       One row per year (TOT if multi-stint, single stint otherwise);
       chevron expands multi-stint years to indented per-(level,
       team) sub-rows. Career-totals row pinned at bottom.
     - **Fielding**: flat per-(year, position, team) rows — fielding
       isn't summable across positions in a meaningful way, so no
       TOT-style disclosure. Per-position career rollup rows pinned
       at bottom; explainer line below the table when a player has
       multi-position career rows ("cross-position totals omitted on
       purpose").
   - Column headers + tooltips read from `STATS[id]` (D15 contract):
     dictionary now 60 entries (+13 batting/pitching counting; +8
     fielding). Header overrides for K/9, BB/9, IP, INN where the
     display label diverges from the dictionary's `short_label`;
     tooltip still inherits from the parent entry.
   - Advanced cohort (wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR /
     Statcast EV + barrel) still **deferred**. Advanced stats live
     as functions in `diamond.advanced.*`; surfacing them on the
     player page needs either per-season L3 materialization (the
     `f_player_season_advanced_*` work listed in `l3.py` docstring)
     or threading the on-demand computation through the request
     handler.
6. ✅ **Advanced stats column block** — done 2026-05-07.
   - New L3 module `src/diamond/schema/l3_advanced.py` materializes
     `f_player_season_advanced_batting` (244k rows) +
     `f_player_season_advanced_pitching` (151k rows) per
     (player, year, league_id, level_id). Linear weights computed
     inline via SQL (woba_scale calibrates against league OBP),
     park factor pulled from the dominant team's park (most PA /
     most outs), filters mirror the audit (PA > 0; outs >= 30 / 10
     IP for pitching).
   - `_lg_constants_advanced` view aggregates league_history at
     (league_id, year, level_id), exposing every constant the
     formulas need (linear weights, woba_scale, fip_constant,
     runs_per_pa, lg_obp/slg/era).
   - Player API extended with `advanced_batting` +
     `advanced_pitching` arrays. UI renders two new sections —
     "Advanced Batting" (PA / wOBA / wRAA / wRC / wRC+ / OPS+ /
     oWAR) and "Advanced Pitching" (IP / FIP / ERA+ / pit_WAR) —
     per-(year, level) flat rows with explainer footnotes.
   - Math verified: Crochet 2029 ERA+=127 (matches audit IE-recon
     127), Skubal 2029 FIP=2.65 (matches docs), Gunnar Henderson
     2029 oWAR=8.7 (matches docs). Top OPS+ leaders 2029 MLB:
     Kurtz 164, Henderson 164, Judge 159, Rooker 159, Santiago 155.
   - Limitation: league_history covers only 2026-2029 in this save,
     so pre-2026 player rows show `—` for advanced stats. Mapping
     OOTP's pre-save imported player history to historical Lahman/
     BREF league averages is deferred (separate scope).
7. ✅ **Movement ledger** — done 2026-05-08.
   - New L0/L1/L2 paths weren't needed; entire feature consumes the
     existing `player_movements` (L3) joined to
     `f_player_season_advanced_*`. Single endpoint
     `GET /api/movements?year=YYYY` returns four direction buckets:
     internal (promotion/demotion), incoming (trade/signed/
     waiver_or_other from outside), outgoing (released/trade/waiver
     to outside). Verdict logic in Python: level-aware thresholds
     (MLB ≥100 = working, ≥120 = thriving; lower levels ≥90/130);
     inverted for departures (player mashing elsewhere = 🔴 we let
     someone good go).
   - Frontend `/movements` page sections all four buckets with
     Bref-style flat tables, per-row verdict glyphs (🟢🟡🔴⚪),
     pending-rows toggle (`?include_pending=1` reveals the
     too-small-sample rows hidden by default — EOS roster swarms
     are noisy), year picker, links to player pages.
   - Real signal surfaced 2029 Red Sox: six 🔴 departures
     (Brayan Bello released → 163 ERA+ elsewhere; Yoeilin Cespedes
     released → 146 OPS+ in 453 PA; Austin Ehrlicher released →
     142 ERA+; Isael Fis released → 186 ERA+; Franklin Primera
     waivered → 151 OPS+; Anderber Urbina waivered → 141 OPS+).
8. ✅ **Real landing page (Club view v0)** — done 2026-05-08.
   - `GET /api/save` returns active-save identity (save_name,
     org_team, latest_dump_date, dump_count, scope counts, season
     range). Pydantic schema in `src/diamond/api/schemas/save.py`,
     route at `routes/save.py`.
   - `/` page renders save header (BOS Red Sox · 2029 season) +
     warehouse-status grid (45 dumps, last sync 2029-11-01, 35,261
     players in scope across 264 teams, seasons 1871–2029) + Tools
     grid with `Live` / `Soon` status pills (Movement ledger,
     Glossary, Player page live; Roster, Pressure board, Charts
     tab queued).
9. ✅ **IA backbone (D17)** — done 2026-05-08.
   - Top nav: **Club** (`/`) · **League** (`/league`) ·
     **World** (`/world`) · **History** (`/history`) ·
     **Explore** (`/explore`) · Glossary · ThemeSwitcher · Quit
   - Four `TabStub` pages (League / World / History / Explore) —
     each renders a section grid showing planned content with
     status pills. Future features land in the right tab from
     day one rather than as orphan top-level routes.
10. ✅ **Theme system (D18)** — done 2026-05-08.
    - Four themes: light / dark / neutral (warm cream) / cb
      (Wong-palette color-blind safe). CSS variables under
      `:root` and `[data-theme="..."]` selectors in
      `web/app/globals.css`. Tailwind config exposes semantic
      tokens (`bg-surface-page`, `text-content-primary`,
      `border-border`, `text-link`, etc.) so components are
      theme-agnostic.
    - **Dark is the default.** No-flash inline `<script>` in
      `<head>` reads `localStorage["diamond.theme"]` and stamps
      `data-theme` before body paints.
    - `<ThemeSwitcher />` dropdown in the layout header. CB mode
      is "chrome only" in v1 — accent + link colors swap to
      Wong-safe blue/orange, but verdict glyphs and move-type
      badges still use the green/amber/rose palette. Full CB
      verdict swap is a backlog item.
    - Migrated to tokens: layout, landing, movements page (all
      four sections), glossary list + detail, FormulaBlock,
      player bio header, PlayerStatsTab (batting / pitching /
      fielding / advanced).
11. ✅ **In-app Quit button + dev.bat one-shot launcher** — done
    2026-05-08.
    - `POST /api/admin/shutdown` — kills both servers + their cmd
      windows. Five-stage kill: web nodes (pnpm + next CLI +
      start-server.js worker, all three needed because pnpm spawns
      them in detached process groups) → port 3000 → web cmd → API
      uvicorn → API cmd → port 8000. Subprocess fully detached via
      `cmd /c start /B` so taskkill cascade can't reach it. End-to-
      end verified: real `pnpm dev` + uvicorn → click Quit → both
      cmd windows close, both ports free.
    - `dev.bat` at repo root — spawns `api.bat` + `web.bat` in
      named consoles, then opens the browser at :3000 after a
      6-second compile pause. Documented in DEV.md.
12. ✅ **Roster page** — done 2026-05-09. `/roster` lists every active
    org-tree player grouped by current level (MLB / AAA / AA / A+ /
    A / Rk / DSL), separating position players + pitchers within each
    level. Filter pills: Level (single-select; All + every level
    present in the data), Role (All / Position / Pitchers), Hand
    (All / R / L / S). **Three-mode stat toggle: Basic ⇄ Advanced
    ⇄ Contact.** Server returns full ~200-player payload in one
    round-trip (~95 KB); all filter / sort / mode interactions are
    client-side. Names link to `/player/[id]` — closes the
    navigation loop. Wired into Club landing's Tools grid.
    - Backend: `src/diamond/api/routes/roster.py`,
      `src/diamond/api/schemas/roster.py`. Single SQL JOIN pulls
      every (player + current team + season stats + advanced +
      Statcast cohort) tuple, then Python folds into level groups.
    - Frontend: server component at `web/app/roster/page.tsx`
      delegates state to `web/components/RosterClient.tsx`
      (the client component holds filters + mode).
13. ✅ **Advanced + Statcast surface expansion** — done 2026-05-09.
    - **wRAA / wRC / park_avg surfaced** on the roster Advanced
      view. Were already in `f_player_season_advanced_batting` —
      pure UI work. Park factor renders as a small subscript per
      row.
    - **SIERA materialized** in `f_player_season_advanced_pitching`
      using the Fangraphs canonical quadratic regression.
      Inputs (K/BB/BF/GB/FB) all present in `f_player_season_pitching`.
      Crochet 2.25 SIERA matches IE-reconciled 2.27 to ±0.02. Now
      surfaced on the roster Advanced view.
    - **Statcast cohort L3 build** — Two new fact tables
      (`f_player_season_statcast_batting` 3,790 rows;
      `_pitching` 3,880 rows). Per-(player, year, league_id,
      level_id), BIP ≥ 30 quality threshold. max_EV is the 90th-
      percentile EV per Statcast convention (not absolute peak).
      Barrel uses Statcast's expanding-window definition. All
      formulas mirror `diamond.advanced.contact.*`. Surfaced via
      the Contact mode toggle on the roster — pitcher rows show
      allowed-contact (lower = better), batter rows show
      generated-contact (higher = better).
    - **Earlier (incorrect) claim corrected**: I had said in an
      audit-inventory pass that Statcast inputs might not exist in
      OOTP's per-PA log. They do — verified `f_pa_event.exit_velo`
      + `launch_angle` populated 100% on BIP rows (573,958 rows,
      EV range 0–126.4 mph, LA range -75°–88°, all realistic).
14. ✅ **Full dump-CSV audit pass** — done 2026-05-09 (no UI
    output; informs the next-up list).
    - Cross-checked every CSV in latest dump against L0 (70 vs 69):
      one ingest gap — `players_pitching.csv` (67 cols of objective
      pitching ratings: stuff, movement, control × overall/vsR/vsL/
      talent + 12-pitch arsenal cube + velocity/arm_slot/stamina/
      ground_fly/hold). **All rating columns are zeroed across all
      148,513 rows × all 45 dumps in this save** — OOTP only
      populates the `players_*.csv` objective files when scouting
      is disabled. Same data IS available via `l0_players_scouted_ratings`
      (Sox-scouted, populated). Net: no usable data; defensive
      ingest fix only, queued.
    - Cross-checked every L0 column against L1+ usage: highest-
      value find is **per-position fielding cube in
      `players_fielding_snapshot`** — `fielding_rating_pos1..9`
      (current 20-80 per position), `fielding_rating_pos1..9_pot`
      (ceiling per position), `fielding_experience0..9` (plays per
      position). Fully populated, never read by any L2/L3/UI
      surface. Sample (Justin Gonzales): pos3=50 (1B current),
      pos7=65 (better in LF!), pos8=50 (capable CF), pos9=60
      (high-ceiling RF), with experience 200/197/200/184 backing
      it up. This is the "where should this guy actually play"
      data — answers it definitively per player per dump.
    - Combined-WAR feasibility revised from "multi-week build"
      down to "half-day slice" — `zr` (Zone Rating, runs-style),
      `framing`, `arm`, plus 6 difficulty-bucketed `opps_made_X /
      opps_X` cols already in `f_player_season_fielding`. Adds
      defensive component to oWAR for combined bWAR.
15. **Combined bWAR / pWAR** *(next slice)* — half-day. Add
    defensive runs from `zr` + `framing` + `arm` (already in fact)
    plus a positional adjustment (informed by the per-position
    fielding cube above). Reconcile against IE WAR for scaling.
    Closes the user's original "where's WAR?" ask.
16. Then **per-position fielding view** (player page sidebar:
    table of position × current rating × ceiling × experience,
    sorted by experience), **service-time / arbitration clock**
    (`roster_status_current.mlb_service_years` etc.), **standings
    page** (League tab content), **clutch / RISP splits** on
    player page, then **records / awards / hof / streaks → History
    tab**, and the rest of the UI_DESIGN.md ladder.

**Open audit carry-forwards** (non-blocking, picked up opportunistically):
multi-level OPS+/ERA+ park weighting, hit_loc-based spray, LeaderCategory codes
44 + 49, trade_history `<entity:type#id>` summary parsing, personality
archetype "Type", All-Star teams 2020-2025 (Lahman caps at 2019, MLB API
doesn't expose annual rosters cleanly). All in BACKLOG.md.

**Smaller follow-ons in the analytical layer** — closed 2026-05-07:
- ✅ Pitching Statcast records — UNION'd via `direction='asc'` for rate stats.
- ✅ Save-side EV records — joined via `f_pa_event`, calibration documented.
- ✅ Awards UNION dedup — Lahman+mlbapi collapsed into `merged` via bbref_id.

All-Star teams 2020-2025 gap remains noted in BACKLOG.md (Lahman caps at
2019; MLB Stats API doesn't expose annual rosters cleanly — separate research
item if surfacing real-life All-Star streaks ever becomes important).
