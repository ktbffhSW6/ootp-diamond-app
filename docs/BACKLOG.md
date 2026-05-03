# Backlog

> Open work items, prioritized. Phases: **Schema & Ingest** (current), **Analysis
> Layer**, **UI**. Phase 1 (Audit) closed 2026-05-04 — remaining open audit items
> are carry-forward research, not blockers.

---

## Schema & Ingest phase (current — Phase 2)

Audit-first gate (Decision D10) lifted 2026-05-04. ~270 of ~360 IE columns
reconcile cleanly; remaining gaps are structural (D5, xstats, multi-level
players) and documented as such. Safe to design schema.

### Foundation

- [x] **Promote inline `league_constants` CTE to a module** — landed 2026-05-05.
  `src/diamond/league_constants.py` registers `lg_constants_bat` and
  `lg_constants_pit` views (per `(league_id, year, level_id)` per Decision D11)
  on a DuckDB connection and exposes a `LeagueConstants` dataclass plus
  `lookup` / `compute_all` for Python callers. `reconcile.py` consumes the
  views via `register_views(con)` in `_connect()`. Reconcile output verified
  byte-identical pre/post-refactor. Follow-up: consolidate with
  `advanced/league_constants.py` (which adds wOBA-scale calibration) once
  the warehouse exists.
- [x] **Design 5-layer warehouse schema** — done 2026-05-05. See `docs/SCHEMA.md`;
  all 10 open questions resolved.
- [x] **Write CREATE TABLE DDL** for L0 + L1 + L2 — done 2026-05-05. `src/diamond/schema/`
  package holds the DDL across 5 phases (l0.py / l1_machinery.py / l1_reference.py /
  l1_event.py / l1_snapshot.py / l2.py + build.py orchestrator). `scripts/smoke_warehouse.py`
  builds end-to-end against the latest dump (<60s) and asserts all layer invariants.
  Layer counts: 69 L0 + 74 L1 entities + 8 L2 facts + 3 admin/machinery tables.

### Pipeline

- [x] Build `diamond ingest <dump_date>` and `diamond ingest --all` CLI commands —
  done 2026-05-05. Plus `--rebuild-only`, `--force`, `--no-rebuild`. Writes to
  `<save>/diamond/diamond.duckdb` per D2; skip-if-success via `_diamond_ingests`.
- [x] Run a full ingest of all 45 dumps as the smoke test — done 2026-05-05.
  44 ingested + 1 skipped; ~3.9 GB warehouse; all invariants pass.
- [x] Build per-ingest reconciliation report comparing ingest output to source CSVs
  (the `reconcile.py` harness becomes a regression check per D8) —
  done 2026-05-05. `--source warehouse` flag; output byte-identical to CSV mode.
- [ ] Build derived `player_movements` table from snapshot diffs + `trade_history`.

## Audit phase — carry-forward (non-blocking)

Items that surfaced during Phase 1 but didn't need to be closed for the schema
to proceed. Pick up opportunistically.

- [ ] **Multi-level OPS+/ERA+ refinement** — ~5-10pp error on ~12 players who
  split a season between MLB and AAA. Hypothesis: OOTP applies a level-weighted
  park factor. To investigate: extract per-level slash + park factors, compute
  weighted average, compare to IE.
- [ ] **hit_loc-based spray classification** — Pull/Cent/Oppo% currently 6-29%
  match. Grid-search confirmed hit_xy x-binning doesn't fit; OOTP likely uses
  per-event spray logic involving hit_loc + hit_xy + something else. Open-ended
  research item; current naive bins stay as best approximation.
- [ ] **Verify 13 unmapped `leader.category` codes** by computing the missing
  derived stats (RC, wOBA, FIP, SIERA, K%, SV%, QS%, CG%, SHO%, GO/AO) and
  re-running the matcher.
- [ ] **Investigate `Shea Sprague` PIT mismatch** (1/220 in `individual_pitch_ratings`):
  IE shows 2 but the player has 3 non-zero pitch ratings. Likely an
  OOTP-internal "developed pitch" flag we can't see from rating fields alone.
- [ ] **Decode `<entity:type#id>` tags** in `trade_history.summary` for structured
  movement parsing (`<Houston Astros:team#12>`, `<Bryan King:player#20728>`).
- [ ] **Personality "Type" archetype** (Captain/Selfish/Humble/Sparkplug/etc.) —
  derived from 5 traits + scouting accuracy; out of scope for v1.

## Analysis layer

Already shipped: 5-tier modern advanced stats library in `src/diamond/advanced/`
(HardHit%/SweetSpot%/Barrel%/Squared%/EV-by-batted-ball-type/spray; empirical
RE matrix + RE24 exposure + situational splits; wOBA/wRAA/wRC/wRC+/OPS+/ERA+/FIP/
Power-Speed/Speed Score/iso splits; RF/9, Catcher Framing+, OF Assist; 2-strike
and count-state splits).

### Refinements

- [ ] **Park-factor integration** for OPS+/ERA+ in advanced library — currently
  park-neutral. `parks.csv` has avg, avg_l, avg_r, hr, hr_l, hr_r per park.
- [ ] **Custom WAR** — combines wRAA + dWAR vs replacement-level baseline
  (typically -2.0 wRAA per 600 PA).
- [ ] **Refine RE24** — current impl reports "expected runs exposed"; full RE24
  needs `(RE_after - RE_before + runs_scored)` which requires inferring post-AB
  base state from the result code.
- [ ] **Spray-chart visualization** — use hit_xy + hit_loc for on-field scatter
  plots per player.

### New reports / features

- [ ] **Draft analyzer / "Where are they now?"** — `players` table preserves
  `draft_year`, `draft_round`, `draft_overall_pick`, `draft_team_id` per drafted
  player. Build `diamond draft <year>` CLI: list class, join to current
  `players_roster_status` for current level/team, compute class
  WAR-through-N-years, flag hits/busts/on-track per pick. **Pre-req sanity
  check**: confirm dropped-and-released draftees survive in `players` long-term
  (hit-rate calc breaks if they don't).
- [ ] **Streaks decoder** — `players_streak` has 21 codes profiled (11 batter,
  9 pitcher, 1 mixed) but display labels are best-guess. Cross-reference OOTP
  UI screenshots / in-game help to lock names, then expose as
  "longest active streak per category."
- [ ] **Record breakers** — (a) computed records via max-agg over
  `players_career_*` + `league_history_*` + `team_history_*` (clean, B-tier);
  (b) `messages.csv` news-feed parsing for record-set events (sloppy, D-tier).
  Build (a) first.
- [ ] **Award winners leaderboards** — `players_awards` (13 codes verified).
  Career-totals per award, per-league/year top winners, franchise totals.
- [ ] **Hall of Fame tracker** — `players.hall_of_fame` + `players.inducted`
  direct columns. Join to `players_awards` for the path to induction.

### Closed as non-derivable

- [x] **Expected-stats model (xBA, xSLG, xwOBA, xERA)** — DEFERRED 2026-05-04
  as structural-limit D-tier. Two-probe EDA (`scripts/xstats_eda.py`,
  `scripts/xstats_3d.py`): 2D EV×LA bucket gets MAE 0.048 / r 0.29 on xBA;
  3D EV×LA×hit_loc with EB shrinkage only nudges r to 0.34. The systematic
  +0.036 bias indicates OOTP reads batter ratings or pitcher-quality directly
  into xstats — not recoverable from at-bat features alone. See DATA_NOTES.md
  "xBA / xSLG / xwOBA — structural-limit D-tier."

## UI phase (later)

Full design in [UI_DESIGN.md](UI_DESIGN.md). Build order:

- [ ] **Reference scope expansion** (per D13). Small — extends `_scoped_players`
  builder with the ≥1 MLB PA union when `SaveConfig.reference_scope_enabled`.
- [ ] **Stat dictionary + glossary** (per D15). `diamond/dictionary/` module +
  `/glossary` page with KaTeX-rendered formulas + hover tooltips on column
  headers. Infrastructure for everything else.
- [ ] **Player page** — Bref-shaped layout, Savant-styled visuals, AI assistant.
- [ ] **Promotion/demotion decision tool** — flagship "GM sidekick" feature.
- [ ] **Custom leaderboards** — Fangraphs-style sortable filterable tables.
- [ ] **Universes + chart builder + scatter** *(bundled)* — Vega-Lite spec
  artifact, no-size-limit cohorts (Plotly WebGL fallback at scale), set ops,
  cross-era support.
- [ ] **AI overlay** (per D14) — keyring-stored keys, pluggable provider
  adapters, OpenRouter live pricing, four use levels (Off/On-demand/Smart/
  Always-on), per-feature overrides, daily-cap auto-degrade.
- [ ] **Cockpit dashboard** — front-office home screen with anomaly flags.
- [ ] **Monthly + annual reviews** — long-form AI-augmented narrative pages.
- [ ] **Setup wizard** — first-launch onboarding (per UI_DESIGN.md "Cross-cutting
  infrastructure"). Includes save-setup picker (D3 v2 fulfillment).
- [ ] **Sync triggers + tracked-save management** — app-launch scan, manual
  refresh, untrack-vs-delete-warehouse distinction.

## Future / nice-to-have

- [ ] Cross-save analysis support (using DuckDB `ATTACH`).
- [ ] Per-save scope picker for non-MLB worlds (foreign leagues, fictional).
