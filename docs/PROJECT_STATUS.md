# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-12 (in-game year 2029→2030) — **Phase 3: pre-save MLB league baselines maintenance pass closed.** Earlier today shipped the situational-splits stack (5 slices, 14 splits per year/level); end-of-day shipped the maintenance fix that drains the `—` from advanced stats on every imported real-history player-season.

Maintenance slice — **D20 pre-save MLB baselines** (just closed): The `_lg_constants_advanced` view is now a UNION of `_native` (OOTP `league_history_*` — save years only) and `_imported` (Lahman 1871-2019 + BREF 2020-2025, summed across AL/NL into MLB league_id=203, level_id=1). `f_player_season_advanced_batting` jumped from 30k → **244,183 rows** — every imported MLB player-season pre-2026 now resolves wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR. Headline spot-checks: Bonds 2001 wOBA .550 / OPS+ 257 / b_WAR 12.5 (vs BBR 259 / 12.5); Pujols 2003 OPS+ 189 (BBR 189 — exact); Trout 2018 OPS+ 198 (real 198 — exact); Pedro 2000 ERA+ 285 (BBR 291); Mantle 1956 OPS+ 220 (BBR 210, modern Yankee Stadium PF gap). Soft-skip on missing history tables means smoke / fresh warehouses still build cleanly. Park factors for pre-2026 use the team's *current-day* park (deferred follow-on); minor-league pre-save baselines stay null (Lahman doesn't carry them). Reconcile harness clean — no save-side regression.

Earlier-today slices (situational stack) in order:
1. **Batter situational splits** — first version of the section: All / RISP / RISP 2-out / Late & Close per (year, level), OPS color-coded vs the All baseline (≥25 pts emerald, ≤-25 rose). Single-season at first (limited by `f_pa_event` shape).
2. **Multi-year `f_pa_event`** (architectural — D19) — the "OOTP replaces at_bats_event.csv on rollover" caveat was build-side, not storage-side. L0 retains every ingested dump's rows by `dump_date`, so we rebuilt `f_pa_event` to read L0 directly with cross-dump dedup keyed on (game_id, season_year). Discovered along the way that **OOTP recycles `game_id` across seasons**, so PK was promoted to (year, game_id, batter_id, pa_in_game_seq). Row counts: `f_pa_event` 877k → 5.1M; `f_player_season_statcast_*` 3,305 / 3,692 → 20,800 / 21,513; `f_record_player` 1,840 → 4,550.
3. **Pitcher situational splits** — same SQL template keyed on `pitcher_id` instead of `batter_id`. Slash columns reflect what the pitcher allowed; UI color logic inverts (emerald when OPS-allowed BELOW baseline = clutch). Crochet 2027 RISP 2-out **.316 OPS allowed**; 2029 .839 (regressed).
4. **Bases + platoon splits** — added `bases_empty` / `bases_loaded` (off `base1/2/3`) and `vs_left` / `vs_right` (LEFT JOIN to `players_current` for handedness; switch-hitters resolve to opposite of pitcher's hand). Side-aware labels: batter card "vs LHP/RHP", pitcher card "vs LHB/RHB". Sanity invariant: `vs_left + vs_right = all` ✓.
5. **Counts + spray splits** — added `first_pitch` / `two_strike` / `full_count` (count BEFORE the resolving pitch) and `pull` / `center` / `oppo` (BIP-only spray; UI skips color coding since denominators differ). Empirically verified `hit_xy` is **batter-relative**, not field-absolute (mean hit_xy on HRs ≈71 for both LHB and RHB — same pull-side band), corrected DATA_NOTES.

**Next**: port a CLI history surface (records / awards / hof / streaks) to the `/history` tab.

---

## One-line summary

Phases 1-2 closed; analytical CLI surface complete; real MLB history through 2025 backfilled; Phase 3 UI live — five-tab IA (Club / League / World / History / Explore) wired into the layout; Club landing renders save metadata + tools grid; movement ledger covers all four direction buckets; roster page — full org tree grouped by level with Basic/Advanced/Contact stat-mode toggle; standings page on `/league` (sub-league × division × team from `team_record_snapshot`); player page Stats tab full (batting / pitching / fielding / advanced + **Defensive Profile** per-position cube + **Service & Status** card + **Situational batting / pitching** with 14 splits across leverage / bases / platoon / counts / spray); theme system supports light / dark / neutral / color-blind with dark as default; in-app Quit reliably kills both dev servers. L3 Statcast cohort + SIERA materialized; `f_pa_event` is now **multi-year** via L0 cross-dump dedup (D19) — 4 years of at-bat history queryable. Combined bWAR / pWAR via OOTP-supplied WAR (Mayer 3.2 = IE 3.2 etc.); per-position fielding cube sourced from `players_fielding_current` view over the snapshot. **Pre-save MLB league baselines** UNIONed in from Lahman 1871-2019 + BREF 2020-2025 (D20) — every imported real-history player-season now resolves wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR on the player page (244k batting rows, vs 30k pre-fix).

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
  - L1: 12 reference + 35 event + 21 state-snapshot + 7 `_current` views + 2 machinery (`_scoped_*`) + 1 admin (`_diamond_ingests`)
  - L2: 8 facts (`f_player_season_batting/pitching/fielding`, `f_player_career`,
    `f_team_season`, `f_league_season`, `f_pa_event` *— multi-year as of
    2026-05-12 per D19; sourced from L0 with cross-dump dedup, PK includes
    `year` since OOTP recycles `game_id` across seasons*, `f_award_event`)
  - L3: 11 derived (`f_trade_participant`, `player_movements` w/ `trade_id`,
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
   - **D20 (2026-05-12)** closes this for MLB pre-save seasons:
     `_lg_constants_advanced` now UNIONs OOTP's native
     `league_history_*` rows with an `_imported` view sourced from
     Lahman 1871-2019 + BREF 2020-2025 (summed across AL/NL into
     league_id=203, level_id=1). f_player_season_advanced_batting
     30k → 244,183 rows; spot-checks Bonds 2001 OPS+ 257 (BBR 259),
     Pujols 2003 OPS+ 189 (BBR 189 — exact), Trout 2018 OPS+ 198
     (real 198 — exact). Minor-league pre-save baselines remain null
     (Lahman has spotty MiLB coverage; OOTP↔real league_id crosswalk
     non-bijective). Park factors for pre-2026 fall back to the
     team's *current-day* park — small bias on OPS+/ERA+, none on
     wOBA / wRC+ / wRAA. Documented in DECISIONS D20 + DATA_NOTES.
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
15. ✅ **Combined bWAR / pWAR** — done 2026-05-10. Reframed mid-slice
    after a one-line audit query: OOTP **directly supplies** combined
    WAR via `players_career_batting.war` (bWAR — offense + defense
    + position + base-running) and `players_career_pitching.war` /
    `.ra9war` (FIP-WAR + RA9-WAR — both with leverage adjustment for
    relievers). Already aggregated into `f_player_season_*.war` and
    reconciled to IE WAR as A-tier (audit `reconcile.py` line 211
    + 393, audit dating to 2026-05-04). The slice was therefore
    plumbing-only:
    - **L3 column add** — `f_player_season_advanced_batting.b_war`,
      `f_player_season_advanced_pitching.p_war` + `.p_ra9_war`. SUMs
      across stints into the (player, year, league, level) grain.
    - **Verified** Mayer 3.2 = IE 3.2 (exact), Anthony 0.9 = IE 0.9
      (exact), Crochet 5.5 = IE 5.5 (exact), Whitlock 0.4 = IE 0.4
      (exact). The custom `o_war` / `pit_war` formulas (offense-only
      / flat 1.13 replacement) run ~1.5-2 wins different on top
      seasons since OOTP includes leverage + defense + position.
    - **Schema + types** — `RosterBattingLine.b_war`,
      `RosterPitchingLine.p_war` + `p_ra9_war`,
      `PlayerAdvancedBattingRow.b_war`,
      `PlayerAdvancedPitchingRow.p_war` + `p_ra9_war`. TS regenerated.
    - **UI** — Roster Advanced view: `oWAR` → `bWAR`, `pWAR` (custom
      pit_war) → `pWAR` (OOTP-canonical). Tooltips reference the
      glossary for the custom alternatives. Player page Advanced
      sections: kept oWAR + pit_WAR alongside bWAR / pWAR / RA9-WAR
      so users can see the gap (offense-only vs combined; FIP-WAR
      vs RA9-WAR signals defense / sequencing).
    - **Dictionary** — added `bWAR`, `pWAR`, `RA9_WAR`; deprecated
      the ambiguous `WAR` entry in favor of the role-specific pair.
      62 dictionary entries total.
16. ✅ **Per-position fielding view** — done 2026-05-10. New
    "Defensive Profile" section on the player page surfaces the
    9-position scouted-rating cube (current × ceiling × experience).
    Sorted by experience descending so the spots the player has
    actually logged innings at appear first; sub-meaningful rows
    (no rating + no experience) are hidden. Real signal verified:
    - Justin Gonzales (POS=1B): 1B current 50 / LF 65 / RF 60 /
      CF 50 — 197 LF plays, 200 CF plays, 184 RF plays.
    - Marcelo Mayer (POS=2B): 2B current 65 (200 plays) / 3B 45
      (124 plays) / SS 30 (58 plays); ceilings 65 / 65 / 60.
    - Crochet (POS=P): P current 45 only; everything else null.

    Implementation:
    - **L1**: new `players_fielding_current` view (filters
      `players_fielding_snapshot` to latest dump_date) added to
      `_CURRENT_VIEWS` in `l1_snapshot.py`.
    - **API**: new `PlayerPositionFielding` schema
      (position / position_name / rating_current / rating_potential
      / experience), `position_fielding: list[PlayerPositionFielding]`
      added to `PlayerResponse`. Route handler unpivots the 9
      `_pos1..9` columns into a 9-row block, normalizing zero ratings
      / experience to `null` so the UI renders em-dashes (OOTP encodes
      "never rated / never played there" as 0).
    - **UI**: `DefensiveProfileTable` in `PlayerStatsTab.tsx` —
      Pos / Current / Ceiling / Plays columns, color-coded by 20-80
      rating (≥70 emerald-bold, 60+ emerald, 50 default, 40s amber,
      <40 rose). Footer note explains the 20-80 scale + sort
      convention.
17. ✅ **Service-time / arbitration clock** — done 2026-05-10. New
    "Service & Status" card on the player page (between bio header
    and tab strip). Shows:
    - **MLB service**: "Xy Yd" with Y = days into current year
      (Bref / MLBPA convention; 172 service days = 1 year).
    - **Service class**: Pre-arb / Arb (Y1/Y2/Y3) / FA-eligible —
      computed from total service days (3.000y / 6.000y boundaries).
      Color-coded chip: emerald (FA), sky (arb), neutral (pre-arb).
    - **Days to FA**: max(0, 1032 - mlb_service_days). Hidden when
      already FA-eligible.
    - **Options**: "n/3 used" + "+m this season" delta when nonzero.
    - **Status flags**: Active / 40-man / 10-day IL / 60-day IL /
      DFA / Waivers. Color-coded; only renders flags that are true,
      so the November snapshot reads clean (Active + 40-man only).
      Mid-season ingests will surface DL / DFA / waivers.

    Verified: Mayer 4y 128d Arb(Y2) FA-216d / Anthony 4y 95d Arb(Y2) /
    Casas 7y 21d FA-eligible / Devers 12y 70d FA-eligible / Crochet
    9y 28d FA-eligible / Gonzales 1y 94d Pre-arb FA-766d.

    Implementation:
    - **API**: new `PlayerRosterStatus` Pydantic schema + fetcher;
      `_service_class()` + `_service_display()` helpers in
      `routes/players.py`. Constants `_DAYS_PER_SERVICE_YEAR=172` +
      `_DAYS_TO_FREE_AGENCY=1032`.
    - **UI**: inline JSX in `web/app/player/[id]/page.tsx` — a small
      card under the bio header. Tooltips explain Pre-arb / Arb /
      FA boundaries + options semantics.
    - Fields not surfaced (semantics unclear): `years_protected_from_rule_5`
      + `has_received_arbitration`. Add when needed.
    - Super-Two qualifiers (early-arb edge case for high-service-day
      pre-arb players) are NOT modeled — OOTP handles internally
      and exposes no public flag.
18. ✅ **Standings page** — done 2026-05-11. Fills the `/league` tab
    stub with real content. New endpoint
    `GET /api/standings?league_id=&year=` returns sub-league × division
    × team rows from `team_record_snapshot` at the MAX(dump_date)
    snapshot within the chosen year. Defaults: MLB (203) / latest year
    with data. Routing falls back to first-available rather than 404
    on bad query strings (deep-link forgiving).

    Implementation:
    - **Schemas**: `StandingsResponse` (league + year + dump_date +
      pickers + sub_leagues), `StandingsSubLeague`, `StandingsDivision`,
      `StandingsTeamRow`, `StandingsLeagueRef` in
      `src/diamond/api/schemas/standings.py`. Magic-number sentinels
      (`-1` clinched, `1000` not-applicable) collapse into
      `magic_number: int | None` + `clinched: bool`. Streak surfaced
      as signed int.
    - **Route**: `src/diamond/api/routes/standings.py`. Three queries
      per request — available-leagues (15 scoped, JOIN to `leagues`),
      available-years for the chosen league, the standings query
      itself. Filter `g > 0` drops the All-Star teams (they slot into
      `allstar_team_id0/1` but don't play a real schedule).
    - **Frontend**: `web/app/league/page.tsx` rebuilt as a real server
      component (was a `TabStub`). League picker grouped by level
      header (MLB / AAA / AA / A+ A / Rk DSL); year picker as a year
      strip. Sub-leagues stacked vertically (AL/NL on MLB); divisions
      laid out 2-up on lg+ breakpoints, 1-up on smaller. User's org
      row uses `border-l-2 border-l-accent` + a "You" pill so it's
      findable at a glance. Streak color-coded (emerald W / rose L /
      muted —). Clinched division leaders get an emerald "Clinched"
      pill. Below the standings: slim "Coming to League" stubs for
      Leaderboards / Awards races / FA pool so the IA stays scannable.

    Verified end-to-end: 2029 BOS Red Sox 93-69 in AL East (clinched
    with -1 streak); CHC 96-66 NL Central +9 streak (clinched); TEX
    AL West clinched -4 streak; full sub-league × division × team
    partition for MLB (30 + 100+ minor-league teams). AAA (1 sub-
    league with null name + 2 divisions) and AFL (absent from
    `leagues` reference table — niche limitation noted) handled.

    Known v1 limitations:
    - **AFL not in picker** — league_id=70 has team rows but no
      `leagues` reference row, so the JOIN drops it from
      `available_leagues`. AFL is a 30-game niche fall league;
      surfacing it requires a different query path.
    - **No Pythagorean / run differential** — `team_record_snapshot`
      carries W-L-Pct only; RS / RA would need a separate per-team-
      season aggregate.
    - **No team-page deep links** — abbr is shown but not yet
      clickable. Lands when team page ships.

19. ✅ **Clutch / RISP splits** on player page — done 2026-05-12.
    New "Situational batting" section on the player page Stats tab.
    Four splits per (year, level): All / RISP / RISP 2-out / Late & Close.
    Each row carries PA / AB / H / 2B / 3B / HR / BB / K + AVG/OBP/SLG/OPS.
    OPS beating the "All" baseline by ≥25 pts colors emerald (clutch);
    lagging by ≥25 colors rose (choke); inside ±25 stays neutral
    (sample-size noise on single-season cuts).

    Implementation:
    - **Schema** (`PlayerSituationalRow`) — per-(year, level, split)
      with all counting cols + server-computed slash. Empty array for
      pitchers + pre-2029 imports.
    - **SQL** (`_fetch_situational_batting`) — JOIN `f_pa_event` to
      `games_event` filtered to game_type=0 (= REGULAR_SEASON in
      `GameType`, NOT 1; verified). UNION ALL four splits within the
      base CTE for a clean tabular result. AB excludes sacrifices
      (`sac=0`); SF = (`sac=1 AND result=5`).
    - **UI** (`SituationalBattingTable`) — one per (year, level)
      tuple, but in this save the warehouse only holds 2029 splits
      (`f_pa_event` is single-season), so most players show one block.
      The "All" row is shaded as the baseline so the eye anchors there.
    - **Reconciliation**: Devers 2029 All row PA=636 / AB=535 /
      H=124 / HR=27 / BB=96 / K=158 — exact match against
      `f_player_season_batting` (split_id=1). Mayer 2029 All matches
      similarly (PA=582 / AB=529 / H=139 / HR=13 / BB=47 / K=116).
    Verified: Devers 2029 RISP .881 (emerald — clutch) / RISP 2-out
    .689 (rose — choked w/ 2 outs) / Late & Close .685 (rose).
    Mayer 2029 Late & Close .752 (emerald — slight clutch in tying-
    run windows). Crochet (pitcher) → 0 rows.

    **Pitcher splits** added 2026-05-12 same day — see item 21 below.
    **Bases / handedness splits** added same day — see item 22.

20. ✅ **Multi-year `f_pa_event` via L0 cross-dump dedup** — done
    2026-05-12. The earlier "single-season only" caveat was build-
    side, not storage-side: L0 retains every ingested dump's rows by
    `dump_date`. Rebuilt `_build_f_pa_event` (`schema/l2.py`) to read
    from L0 directly with cross-dump dedup. Two structural surprises
    surfaced:
    - **`game_id` is recycled across seasons** in OOTP. Empirically
      the integer 10001 is one game in dumps 2026-08 → 2027-02 (67
      PAs) and a different game in dumps 2027-09 → 2028-02 (73 PAs).
      Solution: include `year` in the canonical key. PK changed from
      `(game_id, batter_id, pa_in_game_seq)` to
      `(year, game_id, batter_id, pa_in_game_seq)`.
    - **`games.csv` resets together with at-bats** at rollover. The
      JOIN to `l0_games` requires `dump_date` matching to keep
      same-dump pairing for the year extraction.

    Dedup rule: for each `(game_id, season_year)`, pick the latest
    `dump_date` that observed at-bats for it (post-Nov dumps are
    stable; early-spring dumps trim the prior year's data). The
    `pa_in_game_seq` is then synthesized within that scope by
    file-seq order (per OPEN-4 resolution).

    `f_pa_event` carries `game_type` directly now so the situational
    fetcher no longer needs a JOIN to `games_event`. L1 `at_bats_event`
    + `games_event` stay single-dump (audit reconcile depends on per-
    dump comparison).

    Row-count impact:
    - `f_pa_event`: 877,363 → **5,132,283** (4 years).
    - `f_player_season_statcast_batting`: 3,305 → **20,800**.
    - `f_player_season_statcast_pitching`: 3,692 → **21,513**.
    - `f_record_player`: 1,840 → **4,550**.

    Verified: Devers situational now shows 2026 / 2027 / 2028 (incl.
    AAA rehab stint) / 2029. Mayer's full 4-year arc visible — 2026
    rookie struggle (.602 OPS) → 2027 breakout (.770, RISP 2-out
    .970) → 2028 peak (.764, Late & Close **1.034**) → 2029
    regression (.741). Smoke + typecheck + HTTP fetch all clean.

    UI footer + schema docstring + situational fetcher comment
    updated to reflect "every save year ingested" rather than
    "current season only."

21. ✅ **Pitcher situational splits** — done 2026-05-12. Mirror of
    item 19 keyed on `pitcher_id` instead of `batter_id`. Same row
    shape (`PlayerSituationalRow` reused — same All / RISP / RISP 2-out
    / Late & Close × per-(year, level) grain) but slash columns
    reflect what the pitcher ALLOWED. UI color logic flips: emerald
    when OPS-allowed in a split is ≥25 pts BELOW the All baseline
    (kept opp from scoring), rose when it's ≥25 pts ABOVE (gave
    up too much in clutch).

    Implementation:
    - Schema: added `situational_pitching: list[PlayerSituationalRow]`
      to `PlayerResponse` (same shape as batting).
    - Route: `_fetch_situational_batting` generalized to
      `_fetch_situational(con, player_id, side)` where `side ∈
      {"batter", "pitcher"}`. SQL is templated — only difference is
      the join column (`batter_id` vs `pitcher_id`). Both fetchers
      called from the route handler; empty arrays for the
      wrong-handed audience.
    - UI: `SituationalBattingTable` generalized to `SituationalTable`
      with a `side` prop. `opsCellClass` takes `side` and inverts
      the threshold direction for pitchers. Footer copy adapts —
      "clutch hitters reach for the ball" vs "clutch pitchers shrink
      the strike zone with runners on."

    Verified: Crochet 2027 RISP 2-out **.316 OPS allowed** (emerald —
    elite clutch starter); 2028 RISP 2-out .395 (emerald); 2029 RISP
    2-out .839 (rose — regression year). Position players → empty
    pitching block; pitchers → empty batting block.

22. ✅ **Bases / handedness splits** — done 2026-05-12. Extended the
    situational sections from 4 splits to **8**:
    - **Bases** — `bases_empty` (low-leverage anchor) and
      `bases_loaded` (max RBI chance, all three bags occupied).
      Read off the `base1`/`base2`/`base3` columns already on
      `f_pa_event`.
    - **Platoon** — `vs_left` / `vs_right`. Side-aware labels: the
      batter card reads "vs LHP / vs RHP" (filtered on opposing
      pitcher's `throws`); the pitcher card reads "vs LHB / vs
      RHB" (filtered on the *effective* batter hand). Switch-
      hitters (`bats=3`) bat opposite the pitcher's throwing hand;
      that resolution is in the SQL CASE expression.

    Implementation:
    - SQL: 4 new UNION ALL branches in `_SITUATIONAL_QUERY_TEMPLATE`,
      plus two LEFT JOINs to `players_current` (one for batter, one
      for pitcher) to derive `pitcher_throw_hand` and
      `effective_bat_hand`. The hand-derivation CASE handles
      switch-hitters cleanly: `bats=3` → opposite of pitcher's
      throwing hand.
    - Side-aware label resolution moved out of the simple dict
      lookup into `_split_label_for(split, side)` — shared labels
      for the leverage cluster, side-specific for the platoon split.
    - Display order updated: leverage (risp / 2-out / late&close) →
      bases (empty / loaded) → platoon (vs L / vs R).

    Verified end-to-end:
    - Sanity invariants hold: `bases_empty + (bases-with-runners)
      = all`; `vs_left + vs_right = all` when handedness fully
      populated. Devers 2029: 162 vs LHP + 474 vs RHP = 636 (=All).
    - Switch-hitter test: Leo De Vries 2029 (697 PA, `bats=3`) →
      184 vs LHP / 513 vs RHP, summing to 697. The hand-derivation
      routes switch hitters correctly.
    - Devers 2029: bases-loaded **1.418 OPS** in 15 PA (small but
      tasty); textbook platoon — LHB does better vs RHP (.788) than
      vs LHP (.746).
    - Crochet 2029: vs LHB **.561 OPS allowed** (LHP-vs-LHB
      dominance), vs RHB .697 (typical platoon disadvantage); bases
      loaded .429 (locked in with bases full).

23. ✅ **Counts + spray splits** — done 2026-05-12. Extended the
    situational sections from 8 splits to **14** per (year, level).
    Three new clusters added on top of the existing leverage / bases /
    platoon clusters:
    - **Counts** — `first_pitch` (0-0 result; PA resolved on pitch 1),
      `two_strike` (strikes=2 when resolved), `full_count` (3-2 when
      resolved). Read off `f_pa_event.balls`/`strikes` which carry the
      count BEFORE the resolving pitch.
    - **Spray** — `pull`, `center`, `oppo`. Filtered to BIP only;
      AVG within these splits = hits-per-BIP (BABIP-with-HR);
      OBP collapses to AVG (BB/HBP excluded). UI skips OPS-vs-baseline
      color coding for spray since the denominator semantics differ.

    **Empirical finding** along the way: `hit_xy` is **batter-relative**,
    not field-absolute. Verified by computing mean `hit_xy` on HRs by
    bat hand at MLB-2029: LHB mean ≈73, RHB mean ≈71 — same pull-side
    band for both hands. If hit_xy were field-absolute the means would
    diverge. Updated the spray rule to be hand-INDEPENDENT
    (`x ≤ 5` → pull, `6..9` → center, `x ≥ 10` → oppo, applied to both
    L and R uniformly) and corrected the DATA_NOTES "Low = LF-side"
    claim.

    Verified: Devers 2029 spray reads correctly — Pull 12 HR (1.183
    OPS), Center 15 HR (1.190 OPS), Oppo 0 HR (.566 OPS); 12+15+0=27
    total HRs. Counts: First pitch .725, Two strikes .585 (drops
    sharply), Full count .820 (recovers). Crochet 2029 allowed-spray
    shows pull-side damage (.715 SLG-allowed pull, 13 HR allowed pull;
    0 HR allowed oppo).

24. **Port a CLI history surface** *(next slice)* — drain the
    `/history` stub with one of `records / awards / hof / streaks`.
    All four surfaces exist as L3 facts already; UI work only.
25. Then the rest of the UI_DESIGN.md ladder (pressure board, salary
    stream, compare under Explore, etc.).

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
