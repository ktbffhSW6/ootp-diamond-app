# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-05 (in-game year 2029) — **Phase 2 closed**. All 7 items complete: warehouse built, ingest pipeline live, full --all ingest verified (45 dumps, 3.9 GB), reconcile harness wired to L1, `player_movements` shipping. UI/product design captured in [UI_DESIGN.md](UI_DESIGN.md) + decisions D13/D14/D15. **Phase 3 (UI implementation) is the next phase.**

---

## One-line summary

Diamond is entering **Phase 2 — schema & ingest**. Audit phase closed: ~270 of
~360 IE columns reconcile cleanly, all C-tier and G-tier eliminated, remaining
gaps are structural (D5, xstats, multi-level players). Next: design the 5-layer
warehouse and build the ingest pipeline.

## What works today

- **Project skeleton**: Python 3.14 + DuckDB + Polars + Typer; package at
  `src/diamond/`; editable install via `pip install -e .[dev]`.
- **CLI**: `diamond decode`, `diamond decode-codes`, `diamond reconcile`,
  `diamond coverage`, `diamond advanced`. All write reports to
  `audit_output/` (gitignored).
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

## What's next — Phase 2

Per [BACKLOG.md](BACKLOG.md), in priority order:

1. ~~**Promote inline `league_constants` CTE to a module**~~ — done 2026-05-05.
2. ~~**Design the 5-layer warehouse schema**~~ — done 2026-05-05.
   See [SCHEMA.md](SCHEMA.md). All 10 open questions resolved with rationale.
3. ~~**Write CREATE TABLE DDL** for L0 + L1 + L2~~ — done 2026-05-05.
   `src/diamond/schema/` package holds all DDL across 5 phases.
   `scripts/smoke_warehouse.py` validates the full pipeline.
4. ~~**Build `diamond ingest <dump_date>` and `diamond ingest --all` CLI**~~ —
   done 2026-05-05. Wires the schema builders to a per-save file DB at
   `<save>/diamond/diamond.duckdb` per D2. Skip-if-success logic via the
   `_diamond_ingests` admin table; flags for `--all`, `--rebuild-only`,
   `--force`, `--no-rebuild`.
5. ~~**Smoke test: ingest all 45 dumps end-to-end**~~ — done 2026-05-05.
   44 ingested + 1 skipped, ~3.9 GB warehouse, fully populated.
6. ~~**Wire `reconcile.py` as a post-ingest regression check** (Decision D8)~~ —
   done 2026-05-05. `--source warehouse` flag added; output verified
   byte-identical to CSV-source mode (D8 contract satisfied).
7. ~~**Build derived `player_movements` table**~~ — done 2026-05-05.
   `src/diamond/schema/l3.py` with snapshot-diff + draft sources.
   95,643 movements built from 45 dumps. Trade attribution deferred until
   `trade_history.summary` parser lands (audit carry-forward).

**Phase 2 closed.** Phase 3 (UI implementation) is the next phase, per
[UI_DESIGN.md](UI_DESIGN.md). Eleven items in build order: scope
expansion → glossary → player page → demotion/promotion → leaderboards →
universes+charts → AI overlay → cockpit → reviews → wizard → sync.

Open audit carry-forward items (non-blocking, can pick up opportunistically):
multi-level OPS+/ERA+ park weighting, hit_loc-based spray, 13 unmapped
LeaderCategory codes, Sprague PIT edge case, trade_history `<entity:type#id>`
tag parsing, personality archetype "Type." All in BACKLOG.md.
