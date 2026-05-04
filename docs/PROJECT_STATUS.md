# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-07 (in-game year 2029→2030) — **Phase 3: player page Stats tab is live.** First real product feature shipped; Diamond now renders Bref-shaped year-by-year batting + pitching tables with a Savant-leaning bio header. `GET /api/players/{id}` + `/player/[id]` route work end-to-end against the warehouse — 16-season Carlos Rodón career (1796⅓ IP, 3.92 ERA, 9.69 K/9), 5-stint single-season disclosure for Raymer Medina with synthesized "TOT" rows and indented per-(level, team) sub-rows on click. Dictionary expanded to 52 entries (+13: G_batter / AB / H / D / T / L / G_pitcher / GS / ER / H_allowed / R_allowed / HR_allowed / BB_allowed) so every column header reads from `STATS[id]` per D15. `POSITION_NAMES` + `LEVEL_NAMES` lifted from `draft.py` to `constants.py` for shared use. **Next: player Charts tab** (radial career arc, percentile bars) or **demotion/promotion review** per UI_DESIGN.md build order.

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
  - L3: 6 derived (`f_trade_participant`, `player_movements` w/ `trade_id`,
    `f_draft_class`, `f_record_player`, `f_award_career_player`,
    `f_award_franchise`)
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
5. ✅ **Player page Stats tab** — done 2026-05-07.
   - `GET /api/players/{player_id}` returns bio + per-(year, level,
     team) batting + pitching stints + synthesized per-season "TOT"
     combined rows + career totals. One big payload, one fetch.
     Pydantic schemas in `src/diamond/api/schemas/player.py`; route
     in `src/diamond/api/routes/players.py`; warehouse connection
     pool in `src/diamond/api/warehouse.py` (per-process root con
     + cursor-per-request).
   - `/player/[id]` page (URL uses internal `player_id`; bbref-id
     lookups deferred). Server component fetches player + glossary
     in parallel; bio header (name, nickname, position, B/T,
     current team, retired/HoF flags) + tab strip (Stats active;
     Charts/Game log/Comparisons/Scouting/Contract as placeholders).
   - `web/components/PlayerStatsTab.tsx` (client component) — Bref-
     shaped disclosure-row tables. Default rendering: one row per
     year (combined "TOT" if multi-stint, single stint otherwise).
     Clicking the chevron on a multi-stint row expands per-(level,
     team) sub-rows indented below. Career-total row pinned at the
     bottom of each table.
   - Column headers + tooltips read from `STATS[id]` (D15 contract):
     dictionary expanded by 13 entries to cover G/AB/H/2B/3B/L/GS/
     ER + H/R/HR/BB allowed for the v1 column set.
   - Fielding stats + advanced cohort (wOBA / wRC+ / OPS+ / FIP /
     ERA+ / WAR / Statcast EV + barrel) **deferred to follow-up
     slices**. Advanced stats currently live as functions in
     `diamond.advanced.*`; surfacing them on the player page needs
     either per-season L3 materialization or threading the on-
     demand computation through the request handler.
6. **Player page Charts tab** — radial career arc visualization
   (angular axis = year, radius = headline stat: OPS+/wRC+/WAR/ERA+).
   Per the design discussion 2026-05-07: radial earns its keep as
   a viz, not a navigation aid; the Stats tab disclosure rows are
   the foundation, the chart adds visual signature.
7. Then per UI_DESIGN.md: demotion/promotion → custom leaderboards →
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
