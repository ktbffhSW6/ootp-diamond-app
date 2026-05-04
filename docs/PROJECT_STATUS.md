# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-07 (in-game year 2029→2030) — **Phase 3: player page Stats tab now full — batting + pitching + fielding + advanced stats.** Diamond surfaces wOBA / wRAA / wRC / wRC+ / OPS+ / FIP / ERA+ / oWAR / pit_WAR per (player, year, league, level), pre-materialized into two new L3 tables (`f_player_season_advanced_batting`, `f_player_season_advanced_pitching`) — park-aware (halved for OPS+, 80% for ERA+ per OOTP convention), league-constants-aware (per (league, year, level) — D11). Numbers cross-checked: Crochet 2029 ERA+=127 ✓ (matches IE-reconciled audit value), Skubal 2029 FIP=2.65 ✓, Gunnar Henderson 2029 oWAR=8.7 ✓. Pre-2026 rows show `—` for advanced stats since the save's league_history coverage starts in 2026. Cross-level rollups intentionally omitted (different league constants). **Next: Charts tab** (radial career arc) **or pivot to demotion/promotion review**.

---

## One-line summary

Phases 1-2 closed; analytical CLI surface complete; real MLB history through 2025 backfilled; Phase 3 UI scaffold (FastAPI + Next.js) live with the glossary route as proof-of-life. Player page is the next move.

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
  - L3: 8 derived (`f_trade_participant`, `player_movements` w/ `trade_id`,
    `f_draft_class`, `f_record_player`, `f_award_career_player`,
    `f_award_franchise`, `f_player_streak`,
    `f_player_season_advanced_batting` + `_advanced_pitching` [the
    sabermetric stack materialized per (player, year, league, level)])
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
7. **Player page Charts tab** — radial career arc visualization
   (angular axis = year, radius = headline stat: OPS+/wRC+/WAR/ERA+).
   Per the design discussion 2026-05-07: radial earns its keep as
   a viz, not a navigation aid; the Stats tab disclosure rows are
   the foundation, the chart adds visual signature.
8. Then per UI_DESIGN.md: demotion/promotion → custom leaderboards →
   universes + chart-builder → AI overlay → cockpit → reviews →
   setup wizard → sync triggers.

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
