# Backlog

> Open work items, prioritized. Phases per D40 commitment (2026-05-17 evening):
> **Phase 4a (Audit Closure)** → **Phase 4b (Maximize Warehouse)** → **Phase 5 (Almanac)**
> → **Phase 6 (Multi-save)** → **Phase 7 (AI analyst)** → **Phase 8 (Distribution)**.
> See DECISIONS.md D40 for the full architectural commitment.

---

## 🎯 Active priority — Phase 4a: Audit Closure (~2-3 dev-days)

**Goal**: close the carry-forward audit queue before adding new warehouse capability. Each deliverable resolves a specific open research item. No new code on Phase 4b until Phase 4a exits cleanly.

### Phase 4a deliverables (in execution order)

- [x] **#1 — L0 inventory pass** ✅ **DONE 2026-05-10** (~1 hr)
  Shipped `scripts/inventory_l0_coverage.py` + `audit_output/l0_column_coverage.md`. Save-agnostic (works against any save via `--save NAME`). Findings: 2,466 non-admin L0 columns; **1,418 referenced (57%)**, **1,048 orphan (42%)**; **18 fully-consumed tables** (including `players_at_bat_batting_stats`, `players_awards`, `players_league_leader`, `players_individual_batting_stats`, `players_salary_history`, `players_streak`, `team_record`, `team_roster`, ...). Three tables D40 originally flagged as wire candidates are already 100% consumed — list refined for #2 below. Report includes per-table breakdown, top-orphan ranking, and category-bucketed Phase 4a wiring recommendations.

- [x] **#2 — Authoritative team-stat + valuation cache wiring** ✅ **DONE 2026-05-10** (~1 hr)
  New `src/diamond/schema/l2_ootp.py` adds 9 fact tables + 1 view as OOTP-cache passthroughs (intended as inputs for D40's Phase 4b invariants watchdog):
  - **Team-season facts** — `f_team_season_batting_ootp` (3,647 rows, PK team_id+year), `f_team_season_pitching_ootp` (3,647), `f_team_season_fielding_ootp` (3,647). Source `team_history_*_event`. Carry every OOTP-cached rate stat including `sa`/`da`/`ta`/`ra`, `r9`/`h9`, `cgp`/`qsp`/`winp`/`svp`/`bsvp`/`gfp`/`pig`/`ws`/`gbfbp`/`kbb`/`sbp`/`rtop`/`cera`.
  - **Player-stint facts** — `f_player_stint_batting_ootp` (116,728), `_pitching_ootp` (105,094), `_fielding_ootp` (85,505). Source `players_career_*_event`. Synthetic PK preserved from L1. Carry `ubr`, allowed-hit-type orphans, full opportunity-bucket grid `opps_0..5`/`opps_made_0..5` + `roe`/`plays_base`.
  - **League-season facts** — `f_league_season_pitching_ootp` (34), `f_league_season_fielding_ootp` (344). Carry `kp`/`bbp`/`kbbp`/`irsp` and the zone-rating + efficiency league baselines.
  - **Player valuation** — `f_player_value_current` (12,720 — one row per scoped player at latest dump). Surfaces all 39 orphan cols: per-side `offensive_value_vsl/vsr`/`pitching_value_vsl/vsr`/`leadoff_value_vsl/vsr`, master rolls `overall_value`/`talent_value`/`career_value`, 3-segment trajectory `stats_value_0..2`/`stats_mod_0..2`, per-position rolls `overall_sp/rp/c/1b/2b/3b/ss/lf/cf/rf`, award triggers, `oa`/`oa_rating`/`pot`/`pot_rating`.
  - **Per-side scouted ratings** — `v_player_ratings_by_side` view explicitly enumerates 95 batting + pitching + fielding rating columns (overall + talent + vs-L + vs-R + misc + per-position potentials) so they're addressable by name. Sourced from `players_ratings_current`.

  Each builder calls `_assert_columns_present` against an explicit `_*_ORPHAN_COLS` tuple — OOTP version-bumps that drop/rename a column fail the warehouse build loudly. Wired into `rebuild_l1_l2` orchestration between L2 and L3.

  **Outcome**: 1,418 → **1,681 referenced cols (57% → 68%)**; **263 orphans closed**; 10 target tables + 5 shared-column siblings now at **100% coverage**:
  - `l0_team_history_{batting,pitching,fielding}_stats(_stats)`: 1 + 16 + 2 orphans closed
  - `l0_team_{pitching,batting,fielding,bullpen,starting}_stats`: shared-column closure
  - `l0_players_career_{batting,pitching,fielding}_stats`: 1 + 4 + 14 orphans closed
  - `l0_players_value`: 39 orphans closed
  - `l0_league_history_{pitching,fielding}_stats`: 20 + 17 closed
  - `l0_players_scouted_ratings`: 45 closed

  `make smoke` passes; `diamond ingest --rebuild-only` succeeds in ~30s. **Closes**: unused-authoritative-data class of bugs.

- [ ] **#3 — MiLB levels 5-8 advanced-stats backfill** (~0.5 day)
  Investigate `lref_era_stats_minors` coverage for Short-Season A / Complex / DSL / AFL (currently NULL for pre-2026 player-seasons at these levels). Either close gap or document as permanent limitation. **Closes**: minor-league pre-2026 rows rendering "—".

- [ ] **#4 — EV-bucket OOTP-canonical calibration** (~0.5 day)
  Grid-search Soft%/Avg%/Solid% cutoffs against IE display values across Padres corpus; replace empirical 75/95 cutoffs with OOTP-canonical. **Closes**: DATA_NOTES "OOTP EV cutoffs unknown."

- [ ] **#5 — `hit_loc` semantic decoding** (~0.5 day)
  Map every hit_loc code (0-77 + 87 + 98-105) to a field zone. Unlocks `IFH%` reconciliation. Becomes input to Phase 4b per-player spray refinement. **Closes**: `IFH%` permanently NULL.

- [ ] **#6 — Multi-level OPS+/ERA+ formula refinement** (~0.5 day)
  ~5-10pp error on ~12 players who split MLB/AAA in one season. Hypothesis: OOTP applies level-weighted park factor. Either fix or document. **Closes**: carry-forward item #1.

- [x] **#7 — Permanent-limitation writeup in DATA_NOTES.md** — landed in the D40 docs commit (2026-05-17 evening). DATA_NOTES.md now has a "Permanent limitations" section consolidating `leader.category` codes 44+49, OOTP developed-pitch state, F-tier pitch-tracking 36 cols, and `players_pitching.csv` scouting-mode zeros. These items are no longer tracked as "open" in BACKLOG.

### Phase 4a exit criteria

- `Audit phase — carry-forward` section (below) is either resolved, re-classified to Phase 5+, or marked permanent
- Zero open audit research items without an explicit owner-phase
- Inventory output committed to `audit_output/l0_column_coverage.md`

---

## 🚀 Phase 4b — Maximize the Warehouse (~5-6 dev-days)

Starts after Phase 4a closes. Save-agnostic by construction (every builder reads `<save>/diamond/diamond.duckdb`, no IDs hardcoded). See DECISIONS.md D40 for full design.

### Tier A — Game-grain fact tables (~0.5 day)

- [ ] `f_player_game_batting` — PK `(player_id, year, game_id)` — built from `l0_players_game_batting` JOIN `games_event` for date denormalization, DuckDB sort key `(player_id, date)`
- [ ] `f_player_game_pitching` — same shape from `l0_players_game_pitching_stats`
- [ ] `f_player_game_fielding` — same shape from `l0_players_career_fielding_stats`

Unblocks: "last 12 days Merrill", calendar heatmaps, streak engine, Phase 5 stretch comparator.

### D40 invariants watchdog (~1 day)

- [ ] New table `_diamond_invariants` (dump_date, scope_type, scope_id, year, level_id, metric, dump_value, derived_value, delta, tolerance, status)
- [ ] Initial 10 invariants: team wOBA/OPS/ISO/AVG/OBP/SLG, team FIP/ERA/WHIP/BABIP, league wOBA, event-count consistency (PA/K/HR/AB)
- [ ] CLI: end-of-ingest Rich summary table (green/amber/red)
- [ ] API: `GET /api/admin/invariants` endpoint
- [ ] UI: cockpit drift status pill
- [ ] History trends visible across dumps

### Tier B — Per-dump derived-stat history snapshots (~1 day)

- [ ] `f_player_season_advanced_batting_history` — SCD Type 2 on the L3 layer
- [ ] `f_player_season_advanced_pitching_history`
- [ ] `f_player_season_statcast_batting_history` + `_pitching_history`
- [ ] `f_player_season_xstats_batting_history` + `_pitching_history`
- [ ] Current L3 tables become `_current` views filtered to `MAX(dump_date)`

Unblocks: trajectory queries, real sparklines, engine-patch detection, reconciliation history.

### Tier C — Per-dump leaderboard snapshots (~0.5 day)

- [ ] `f_record_player_history` — as-of leaderboard membership per dump_date
- [ ] `f_award_race_history` — running award-race standings per dump_date

Unblocks: "who was leading on June 1?"

### Tier D — Rolling-window materialized views (~0.5 day)

- [ ] `v_player_last_7_batting`, `v_player_last_15_batting`, `v_player_last_30_batting`
- [ ] `v_player_last_5_starts_pitching`, `v_player_last_10_starts_pitching`
- [ ] `v_player_calendar_heatmap` (per-game stat-line, all players)

### Per-player calibration improvements (~0.5 day)

- [ ] **Spray**: ingest `players_ratings.batting_pull` + `lref_pt_ballparks.{lh_max,rh_max}`; build per-player Pull/Cent/Oppo boundary instead of flat hit_xy<114. Target: 40% → 70-80% match.
- [ ] **xBA**: piecewise EV-bucket scalers replacing flat ×1.22 (calibrated against Padres corpus). Target: 89% → 95%+.

### UI rollout (~1 day)

- [ ] Cockpit drift status pill (consumes `_diamond_invariants`)
- [ ] Player page "Last 7 / 15 / 30 days" toggle on stats tables (consumes Tier D)
- [ ] Spotlight cards switch to real Tier B sparklines (currently faked from raw stats)
- [ ] `/settings/invariants` admin page surfaces full per-ingest drift report

### Phase 4b exit criteria

- Padres recon at 98%+ on Padres corpus
- "Last 12 days Merrill" returns in <100ms
- Every monthly ingest emits a self-validation report
- Every screen has a path to a time-windowed view

---

## 📖 Phase 5 — The Baseball Almanac (~10-14 dev-days)

Save-agnostic complete-history layer. **Pre-2026 = static reference** (lref_* + Lahman + Retrosheet + Baseball Savant), 12/31/2025 boundary machine-enforced. **2026+ = pure OOTP sim** from monthly dumps. Era-agnostic views bridge the two halves.

### Sequence

1. [ ] HoF Lahman drop — `lref_master.lahmanID` swap (~2 hrs)
2. [ ] `lref_player_*` ingest — Lahman batting/pitching/fielding/hof/awards, frozen per save (~1 day)
3. [ ] `lref_statcast_*` ingest — Baseball Savant 2015-2025, real-MPH scale labeled (~1 day)
4. [ ] Unified player resolver `/api/players/{key}` accepts OOTP int + Lahman string (~1 day)
5. [ ] Era-agnostic views (`v_player_season_*`, `v_player_game_*`, `v_game_log`) (~1 day)
6. [ ] `lref_game_log` — Retrosheet GL files, every MLB game 1871+ (~1 day)
7. [ ] `f_game_log` from OOTP — already built in Phase 4b Tier A, JOIN only (~free)
8. [ ] First Almanac page `/history/year/[YYYY]` MVP (~1-2 days)
9. [ ] `lref_game_player_*` — Retrosheet events via Chadwick tools (~2-3 days)
10. [ ] **Stretch comparator (Mantle vs Merrill flagship)** — built on Tier A (~2-3 days)
11. [ ] Streak engine / calendar heatmap / park-trip splits (~1 day each)

### Cross-cutting

- Source-attribution tooltips (which data source backs each number)
- Statcast scale labels (real-MPH vs OOTP-sim ~5mph low)

### Architectural commitments

- Pre-2026 = static reference data, frozen with the save
- 2026+ = pure OOTP sim from monthly dumps
- 12/31/2025 boundary machine-enforced via year filters on unified views + smoke-test invariant
- Save-agnostic by construction: any new save gets the same baseline depth on first ingest

---

## 🌐 Phase 6 — Multi-save scaffolding (~3-5 dev-days)

Multi-save is a workflow, not just a setup wizard. Summer of many saves needs ergonomics.

- [ ] Save-comparison views ("Padres-me at year 4 vs Sox-me at year 4") (~1 day)
- [ ] Cross-save player tracker (same real player, different sim universes) (~0.5 day)
- [ ] Reconciliation-as-CI across all saves with control data (~0.5 day)
- [ ] Save archive/restore + diff tooling (~1 day)
- [ ] Multi-save overlays on cockpit (~1 day)

Exit criteria: 5+ concurrent saves runnable through summer with no manual switching pain.

---

## 🤖 Phase 7 — AI as analytical layer (~3-5 dev-days)

Leverages Phase 4b Tier A (game-grain facts) + Tier B (derived history) + Phase 5 era-agnostic views.

- [ ] Trajectory tools — `get_player_trend`, `get_hot_cold`, `get_streak` (~0.5 day)
- [ ] Calendar / window-aware natural language — "Cabrera last month vs season" (~0.5 day)
- [ ] Almanac comparator tool — Mantle/Merrill via NL prompt (~1 day)
- [ ] Trade recommendation engine — uses pressure board + leverage stats (~1-2 days)
- [ ] Hot/cold streak narrative generation (~0.5 day)

---

## 📦 Phase 8 — Polish + distribution (deferred)

Gated on "ready to share Diamond beyond solo use." Scope decided post-summer. Possible items:
- [ ] Code signing + Inno Setup MSI installer (~1 day) — see Desktop shell v2 follow-ups below
- [ ] Auto-update (~1 day)
- [ ] Bundle Node.js (~0.5 day)
- [ ] Mac/Linux ports (~2-3 days each)
- [ ] Web-share path (its own decision per D16)

---

## ✅ D39 Statcast reconciliation deep-dive — SHIPPED 2026-05-17 evening

Four-part fix closed Padres Statcast/x-stat columns from ~85% → 95% match overall:

- **D39a — Spray classification** (`hit_xy` is **batter-relative**, not stadium-relative). HR-only events from 1,889 MLB 2028 HRs anchored the encoding: both LHB and RHB pulled HRs cluster at low `hit_xy`. Calibrated boundaries: Pull<114, Cent 114-195, Oppo≥196. **Pull% 5%→38%**, Cent 18%→56%, Oppo 9%→40%. Documented ceiling: 1D `hit_xy` can't capture per-player skew; ~50% within ±10pp is the realistic limit without (stadium handedness × pull-tendency-rating) features.
- **D39b — `game_type=0` filter** added to all three L3 builders (`f_player_season_statcast_batting`, `_pitching`, `_f_pa_event_xstats`). IE Statcast columns are regular-season only; L3 was silently inflating BIP/EV by 10-15% by including spring training + playoffs.
- **D39c — LA bucket recalibration** to GB<12 / LD 12-26 / FB 27-51 / PU≥52 (was 10/25/50). **LD% 31%→88%, GB% 60%→73%, FB% 4%→69%, IFFB 22%→72%, HR/FB 65%→79%, GB/FB ratio 3%→57%**.
- **D39d — x-stats** (three sub-bugs in D29 Slice 2):
  - Integer-EV interpolation collapsed `floor·0 + ceil·0 = 0` — silently zeroed 15-25% of every player's BIPs. Fixed with explicit `CASE WHEN ev_floor=ev_ceil THEN floor_val ELSE <interp>`.
  - IE-style denominators: `xBA=SUM(xba_pa)/AB`, `xSLG=SUM(xslg_pa)/AB`, `xwOBA=(SUM(xwoba_pa)+0.69·uBB+0.72·HBP)/PA`. Per-BIP averages retained as `*_bip` inspection columns.
  - Empirical scalers (`lref_x*_table` is real-MLB-calibrated, OOTP IE pre-scales higher): xBA × 1.22, xSLG × 1.09. xwOBA already within ~3% — no scaler needed.
  - xERA via Savant convention `21.5·xwOBA − 2.65`.
  - **Result**: Batting xBA 0%→89%, xSLG 0%→89%, xwOBA 0%→78%. Pitching xBA 0%→96%, xSLG 0%→97%, xwOBA 0%→82%, xERA 0%→87%.

Plus housekeeping: save-aware report header (`write_report()` no longer hard-codes "Red Sox"); `f_player_season_xstats_*` added to warehouse passthrough aliases.

Files: `src/diamond/audit/reconcile.py`, `src/diamond/schema/l3_advanced.py`. Verified on Perez (28026), Merrill (52256), Cabrera (1618). See DECISIONS.md D39 for the full diagnostic transcript including the HR-by-handedness analysis that surfaced the spray bug.

---

## ✅ D38 Padres reconciliation + wOBA formula fix — SHIPPED 2026-05-17 afternoon

**Status**: reconciled Padres save (`The Fathers.lg`) sim stats against
OOTP IE control data at `docs/helpful_files/recon/Padres/`. Three
distinct fixes in one commit (`20d161b`):

- ✅ **Multi-save reconciler infrastructure** — `_resolve_ie_path`
  org-agnostic suffix match (Padres `san_diego_padres_organization_-_*.csv`
  resolves via same FileSpec defs as Sox), `--ie-dir` + `--save` CLI
  flags, scouting-stamp fix (`scouting_team_id=4` constant regardless
  of save because L1 view is already audit-team-filtered at D12).
- ✅ **wOBA formula corrected to OOTP-canonical** — OOTP uses base
  linear weights × PA denominator, not FanGraphs (AB+uBB+SF+HBP) form
  with lg-OBP-scaled weights. Bastidas 2028 IE=.357 vs old Diamond=.372
  (.015 systematic high drift on minor-leaguers with SH>0). Fixed in
  `l3_advanced.py` (player_woba + both lg_constants views) and
  `reconcile.py` BATTING_DERIVED_CTE. wOBA tier match: 76% → 94%.
  **This bug existed in Sox save too** but didn't surface because
  Sox MLB hitters have SH=0 and we never reconciled minor leaguers.
  Sox warehouse will need `--rebuild-only` to refresh L3 with corrected
  formula (minor-league rows will shift; MLB unchanged).
- ✅ **Accuracy floor documented**: 197/197 A-tier columns 100%, 43/43
  B-tier 94-100% (rounding-grade), ~85% of recoverable surface at
  OOTP-canonical accuracy.

**Honest postmortem**: ~80% of the D36/D37/D38 bugs were latent in the
Sox save the whole time. The Padres save just exposed them. Pattern:
single-instance testing → assumptions that happened to hold for Sox
became invisible coupling. Mitigation going forward: Padres save is
now a permanent second test target. The recon CSV folder is a stable
ground-truth corpus we can re-run after every refactor.

---

## ✅ D37 in-progress season + endpoint resilience — SHIPPED 2026-05-17 morning

**Status**: shipped same-day fixes after user opened Padres save
mid-2028. Three issues:

- ✅ **In-progress season league constants** — OOTP only writes
  `league_history_*_stats.csv` rows for completed seasons. Mid-season
  dumps had zero (year, league, level) rollup rows for 2028 (except
  DSL which completes in July). Without league constants, OPS+/wRC+/
  ERA+/FIP/wOBA all returned NULL across every in-progress player.
  New `agg_bat_fallback` + `agg_pit_fallback` CTEs in
  `_lg_constants_advanced_native` aggregate from `f_player_season_*`
  for combos NOT in `league_history_*`, gated to years that already
  have SOME league_history coverage so pre-save Lahman-imported rows
  stay routed to `_lg_constants_advanced_imported`. Post-fix: 25 rows
  for 2028 in `_lg_constants_advanced` (was 2); Merrill 2028 OPS+ 124,
  Mason Miller ERA+ 252.
- ✅ **Cockpit nullable metrics** — `headline_metric_value: int | None`,
  cockpit endpoint passes None instead of coercing to 0, frontend
  renders "—" with `text-content-muted`, insight is suppressed when
  current metric is None.
- ✅ **`/api/hof` 500 on Padres save** — endpoint LEFT JOIN-ed
  `history_lahman_people` for `bbref_id` resolution, but Padres save
  was created without running `diamond fetch-history` so warehouse
  has zero `history_*` tables. New `_history_loaded(con)` probe +
  template-based query construction substitutes `NULL::VARCHAR AS
  bbref_id` and drops the JOIN entirely when the table's absent.
- ★ **Bonus**: `/api/admin/dump-status` reported 0 ingested even
  though warehouse had 29 — endpoint opened its own
  `duckdb.connect(read_only=True)` which fails on Windows with
  IOException because uvicorn's RW connection holds an exclusive
  lock; switched to `Depends(get_cursor)`.

---

## ✅ Multi-save productionization (D36) — SHIPPED 2026-05-16 end-of-day

**Status**: drove the Padres save (`The Fathers.lg`, audit_team_id=23,
29 dumps 2026_03 → 2028_07) end-to-end through Diamond. Five distinct
issues surfaced + fixed in three commits:

- ✅ **AI prompt save-awareness** (`95c13ce`) — `_resolve_org_context`
  reads active SaveConfig + `MLB_TEAMS_BY_ID` + warehouse-probes
  latest/earliest seasons; substitutes team city/name/org_id into the
  system prompt. No more "Boston Red Sox" hardcoding.
- ✅ **Desktop chrome save-awareness** (`95c13ce`) — new
  `diamond.saves.get_active_window_title()` is the single source of
  truth for `WINDOW_TITLE`. Both `launcher.py` and `single_instance.py`
  (used by `FindWindowW`) import from it. Splash HTML substitutes
  the active save name at load time.
- ✅ **VARCHAR-defensive scope filters** (`95c13ce`) — every scope
  filter in `l1_event.py` + `f_trade_participant` builder wraps ID +
  date columns in `TRY_CAST(... AS BIGINT)` / `TRY_CAST(... AS DATE)`.
  Fixes The Fathers' L0 inferring VARCHAR for several columns where
  Sox had BIGINT/DATE.
- ✅ **JS local-TZ date parsing** (`101573e`) — `fmtDate` now detects
  date-only ISO strings and constructs via `new Date(y, m-1, d)` to
  avoid the UTC-midnight off-by-one display bug. Three pages patched.
- ✅ **dump_date end-of-month convention** (`5b66839`) —
  `dump_name_to_date()` returns last-day-of-month (was 1st). New
  `migrate_dump_dates_to_eom()` + `diamond migrate-dump-dates` CLI
  command for existing warehouses. Idempotent via setting marker;
  not auto-run (10-15min stall on big saves).

**Migration status**:
- `The Fathers.lg`: ✓ MIGRATED.
- `Building the Green Monster.lg`: pending — run
  `diamond migrate-dump-dates --save "Building the Green Monster.lg"`
  when ready (expect 10-15 min).

### D36 follow-ups — DEFERRED

- [ ] **L0 type-coercion at ingest** — currently we defend with
      `TRY_CAST` at every consumption site. A cleaner design would
      pass explicit `columns={'team_id_0': 'BIGINT', ...}` overrides
      to `read_csv_auto` so the L0 tables are typed correctly from
      the start. Touches `l0.py` + every `L0Spec` definition. ~1
      day.
- [ ] **Sox warehouse migration** — opt-in CLI step; user runs when
      ready. Will eventually want to run.
- [ ] **`_resolve_org_context` cache** — every chat request
      recomputes the org context (cheap warehouse probe + dict
      construction, ~5ms). Could memoize per save. Probably not
      worth it; would add complexity around save-switch invalidation.
- [ ] **Save-config UI hardening** — `/settings/save` works but the
      discovery UI doesn't show save-config status (configured /
      needs-config). Would help users self-serve when they add a
      new save mid-session. ~half day.

---

## ✅ L_REF reference layer (D26 + D27) — analytical + cosmetic layer SHIPPED across D29 + D30

**Status as of 2026-05-15**: 9 of 10 slices fully shipped (1 / 2 / 3 / 4 / 5
analytical via D29; 6-frontend / 8 / 9 cosmetic via D30 — see "Capability wave"
section below). Slice 7 skipped (lref_master can't replace Chadwick — see
findings inline). Slice 10 partially blocked (brand colors not in install
folder per audit). The L_REF investment is essentially complete.

## ✅ Capability wave (D30) — leverage stack + real assets — SHIPPED 2026-05-15

**Status**: 4 of 4 slices shipped in one session. Pre-D30 the platform was
*trustworthy* (post-D29 L_REF rollout); post-D30 it's *visibly more capable*
on the modern save too:

- **Slice A** ✅ Leverage stack (WPA / LI / RE24 / Clutch) — new
  `f_player_season_leverage_*` tables (32,767 + 32,338 rows). Wire-up to
  player page Advanced columns + leaderboards (6 new stats) + 4 dictionary
  entries. Eldridge 2029 WPA +5.81 / RE24 +49.4. Commit `dec326d`.
- **Slice B** ✅ Real team logos via `/api/photos/teams/{team_id}.png` +
  `<TeamLogo>` component. Wired into 5 surfaces. Commit `fe41688`.
- **Slice C** ✅ Spray chart geometry sources OOTP-canonical 7-segment data
  via `/api/parks` adapter. Commit `1cd365b`.
- **Slice D** ✅ Real HoF plaques via `/api/photos/hof/{bbref_id}.png` +
  manifest endpoint + bbref_id resolution on `HofPlayer`. Plaque gallery
  on `/history/hof`. Commit `d5bbfaf`.

**Remaining D30-adjacent deferrals** (low priority): multi-year batter LI
+ multi-year WPA via `lref_li_table` / `lref_wpa_table` per-PA lookup;
inline plaque thumbnails per inductee row (needs Pillow downsample); full
7-segment outline rendering on the spray chart (vs the 5-point spline we
adapt to today).

## ✅ Cleanup pass (D34) — SHIPPED 2026-05-16

Three small commits removing pre-D32 vestigial code and tightening
the surface. User asked "do we need all the files at the root?" —
audit confirmed several no longer pulled their weight.

- ✅ **Launcher consolidation** (commit `d3d2bcc`) — deleted `api.bat`,
  `web.bat`, `kill-stale.bat`. `dev.bat` calls `make api` / `make web`
  directly; PYTHONIOENCODING exported from the Makefile; kill-stale
  loop inlined as 8 lines at the top of dev.bat. Launcher count
  5 → 2 (`Diamond.vbs` + `dev.bat`). DEV.md updated.
- ✅ **Header Quit button removed** (commit `b682fbb`) — pre-D32
  vestige; window X + tray Quit cover it cleanly. Removed
  `QuitButton.tsx`, `shutdownApp()`, `<QuitButton />` from layout,
  `POST /api/admin/shutdown` route, 100-line `_KILL_SCRIPT` constant,
  5 imports it required.
- ✅ **Tray Show focuses native window** (commit `f791080`) — was
  opening the cockpit in default browser; now uses Qt signal
  (`showRequested`) to un-minimize/raise/activate the existing
  window. Tray gains optional `on_show: Callable | None` parameter.

**Net delta**: 4 files deleted at repo root + ~325 LOC removed
across backend + frontend.

**Files audited and intentionally kept**: `Diamond.vbs`, `dev.bat`,
`Makefile`, `scripts/xstats_*` (D-tier evidence per DATA_NOTES),
all `docs/*.md` (well-partitioned by audience), all
`src/diamond/*` modules (every one imported somewhere — earlier
"unused" scan was a false positive caused by multi-line imports).

---

## ✅ AI sidebar (D33) — SHIPPED 2026-05-16

**Status**: full four-tier AI surface replacing D14's single-button
"Summarize career". Floating launcher on every page; tool-using
analyst over the warehouse; GM-copilot modes; prompt-to-dashboard via
Metabase API.

- ✅ **Tier 1 — page-aware** (`AISidebar.tsx` reads `usePathname()`,
  system prompt includes "user is on /player/123")
- ✅ **Tier 2 — tool-using analyst** (`src/diamond/ai/tools.py` —
  6 tools: query_warehouse, get_player, compare_players,
  get_glossary, list_leaderboard_stats, create_metabase_card; route
  drives the tool loop with iteration cap = 6)
- ✅ **Tier 3 — GM copilot modes** (4 modes: chat / callup / trade /
  draft; mode pills in sidebar footer; structured prompts in
  `_MODE_PROMPTS`)
- ✅ **Tier 4 — prompt-to-dashboard** (`create_metabase_card` tool
  POSTs MBQL spec via `diamond.api.metabase` coordinator; returns
  card_url; sidebar renders inline as ✓ green launcher link)
- ✅ **Provider-agnostic** (Anthropic + OpenAI both support tool use;
  OpenAI adapter translates message format + tool_calls in both
  directions)
- ✅ **Safety** (read-only SQL with regex-blocked mutation keywords +
  single-statement guard + LIMIT 1000 + 5s timeout; tool errors
  return `{"ok": False}` rather than raising)
- ✅ **Metabase link fix** — `QWebEnginePage.createWindow` override
  routes target="_blank" to system browser via
  `QDesktopServices.openUrl`. Workshop tab's deep-link cards now work
  inside the desktop shell.

### Same-day D33 follow-ups — SHIPPED 2026-05-16

- ✅ **Anthropic snapshot auto-migration** (`061e2f6`) — `RETIRED_MODELS`
  map rewrites stale model strings; default flipped to rolling alias
  `claude-haiku-4-5`.
- ✅ **DuckDB timeout fix** (`03943aa`) — dropped Postgres-style `SET
  statement_timeout` that was failing every tool call.
- ✅ **`describe_table` tool + LIMIT-injection fix** (`3de5bbd`) — model
  has a clean schema-discovery path; `DESCRIBE` no longer mangled
  by LIMIT injection. Tool count 6 → 7.
- ✅ **Persona setting + tool-plumbing hide** (`fe74739`) — free-form
  `persona` field in `/settings/ai` (5 presets); tool calls hidden
  by default with verbose toggle in sidebar header; Metabase cards +
  errors stay visible regardless.
- ✅ **Page-payload wiring** (`2381f0b`) — `<PagePayloadProvider>`
  Context + `<PagePayloadBridge>` server-component bridge with 16KB
  cap. Cockpit + player page publish their data; AISidebar reads via
  `usePagePayload()`.
- ✅ **`get_career_arc` tool + cite-your-sources prompt** (`5711f98`) —
  fixed Crochet-vs-Ryan hallucination class. Deterministic age-per-
  year + warehouse-aggregated career WAR. System prompt mandates
  citing tool sources for every specific number. Tool count 7 → 8.

### AI sidebar v2 follow-ups — partially shipped via D35

- ✅ **Streaming responses** (SSE) — D35 Tier C. New `POST
  /api/ai/chat/stream` endpoint emits provider-agnostic events
  (`text_delta`, `tool_use`, `tool_result`, `iteration`, `done`,
  `error`); both Anthropic + OpenAI adapters implement native
  streaming; frontend `streamChat()` parses SSE incrementally with
  abort support; UI shows blinking ▍ cursor + Stop button. (D35,
  2026-05-16)
- ✅ **Markdown rendering for assistant text** — D35 Tier A.
  `MarkdownMessage` component via `react-markdown` + `remark-gfm` +
  `rehype-katex` + `remark-math`. Tables / headings / lists / code
  blocks all render properly; per-text-block card chrome dropped.
- ✅ **Coalesced response groups + Claude.ai-style asymmetry** —
  D35 Tier B. Consecutive assistant turns render under one Diamond
  label; user messages right-aligned pills; assistant flat
  full-width prose; hover copy button.
- ✅ **Resizable + repositioned chrome** — D35 Tier D. Drag-to-
  resize handle on left edge (380-900px, persisted); mode pills
  moved into header; jump-to-latest button when scrolled away
  mid-stream.
- [ ] **Conversation persistence** — threads live in component state
      only. Per-save persistence to `~/.diamond/<save>/ai-threads/*.json`
      would let users resume long analyses. ~half day.
- [ ] **Page-payload opt-in for more pages** — cockpit + player page
      done; standings, leaderboards, movements, history, draft still
      send pathname only. 2-line change per page. ~half day total.
- [ ] **More tools** — `get_team`, `get_standings`, `get_movements`,
      `get_recent_news`, `compare_seasons` would broaden the analyst
      surface. ~half day per tool.
- [ ] **Token usage tracking + daily cap** — D14's reserved
      `use_level` field can drive a soft daily cap so users don't
      surprise-burn API credits. ~half day.
- [ ] **Inline embedded Metabase card preview** — D31 noted that
      static-embed (signed JWT) iframes work even with OSS's
      `frame-ancestors 'none'` for individual cards. Could render the
      card the model just created inline in the sidebar instead of
      linking out. ~1 day.

---

## ✅ Native desktop shell (D32) — SHIPPED 2026-05-15 late-evening

**Status**: Diamond is now a native Windows app. One `Diamond.exe`, no browser
tab, no flapping cmd windows, clean shutdown via Windows Job Object. Five-slice
ship in a single session.

- ✅ **Slice 1 — Launcher MVP** (`src/diamond/desktop/{launcher,sidecar,paths}.py`,
  `desktop/__main__.py`, pyproject `[desktop]` extra). PySide6 QMainWindow +
  QWebEngineView, uvicorn in a daemon thread (in-process), Next.js standalone
  as hidden `node server.js` child via `CREATE_NO_WINDOW`. Both bind 127.0.0.1;
  ports auto-fallback.
- ✅ **Slice 2 — Standalone build** (`web/next.config.mjs` `output: 'standalone'`,
  `scripts/build_desktop.py`, `Makefile` `desktop` / `desktop-package` targets).
  Build script copies `.next/static` and `public/` into the standalone tree
  (Next omits these by default).
- ✅ **Slice 3 — Lifecycle hardening** (`desktop/{win_jobobject,single_instance}.py`).
  Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` — every spawned PID
  assigned to it; hard-killed launcher takes its kids down. Single-instance
  via `CreateMutexW` + `Local\\Diamond.OOTP.Desktop.SingleInstance`; second
  double-click sees `ERROR_ALREADY_EXISTS`, focuses the running window via
  `FindWindowW` + `SetForegroundWindow`, exits.
- ✅ **Slice 4 — PyInstaller bundle** (`desktop/diamond.spec`). One-folder
  spec (not `--onefile` — standalone tree's many small files would add 2-3s
  per-launch unpack to TEMP). Datas: web standalone tree → `web_standalone/`,
  asset folder → `desktop_assets/`. Hidden imports cover all 23 API route
  modules + uvicorn dynamic imports + PySide6 widgets/QtWebEngine + pystray + PIL.
- ✅ **Slice 5 — Polish** (`desktop/{splash,tray}.py`, `desktop/assets/splash.html`).
  Single-window-morph: one window opens with splash HTML at final size; boot
  thread calls `window.load_url(main_url)` when ready (thread-safe in
  pywebview). No WebView2 runtime dependency — QtWebEngine ships its own
  Chromium, so end-users on Win10 don't need to install anything separately.
  Tray icon (pystray, daemon
  thread): Show / Open Metabase / API docs / Quit.
- ✅ **Docs**: `docs/DESKTOP.md` (architecture, build pipeline, troubleshooting,
  when-not-to-use); `docs/DECISIONS.md` D32 (full architectural reasoning vs
  Tauri / Electron / static-export Next.js).

**What this enables**: Diamond now feels like a real desktop app — the same
class as Tableau Desktop / Power BI Desktop / OBS / Discord. Single
double-click → splash → polished UI in 3-5s. Close = nothing left running.
Hard-kill safe (Job Object). No `kill-stale.bat` needed for the desktop
path.

### Desktop shell v2 follow-ups — DEFERRED

These extend D32 but aren't blocking:

- [ ] **Code signing** — Authenticode cert so Windows SmartScreen doesn't
      flag `Diamond.exe` on first run. ~$200/yr for a real cert + 1 day to
      wire into the build pipeline. Worth it once we distribute outside the
      author's machine.
- [ ] **Inno Setup MSI installer** — wraps `dist/Diamond/` into a single
      installer with Start Menu shortcut + uninstall entry. ~half day.
      Needed before any "share with
      friends" milestone.
- [ ] **Auto-update** — Tauri-style updater (download patch, swap binaries,
      relaunch). ~1-2 days. Not urgent for single-user — relaunch after
      `git pull` + `make desktop-package` works fine.
- [ ] **Bundle Node.js** — eliminate the "node on PATH" requirement. ~half
      day; +50MB bundle. Not blocking — most users have Node from dev
      already.
- [ ] **Mac/Linux ports** — PySide6 supports both with the same API but
      Diamond's saves path is hardcoded to Windows. Cross-platform is a
      separate scope (would also revisit Tauri if smaller bundle matters).
- [ ] **Minimize-to-tray** — currently close-window = full shutdown.
      Power-user mode: minimize keeps backends warm in the tray. ~1 hr.
      Tray menu already has "Show Diamond" stub for this.
- [ ] **Pre-warm splash UX** — show progress percent during sidecar boot
      (e.g., "Starting API…" / "Compiling routes…" / "Ready"). Boot
      thread already has the milestones; just needs to evaluate JS in
      the splash window. ~1 hr.
- [ ] **Auto-launch Metabase from launcher** — add a third sidecar
      (`metabase.bat /b`) so `Diamond.exe` brings up the full BI stack.
      Gated on user preference (some users may not want Metabase
      always-running).

---

## ✅ Metabase BI workshop (D31) — SHIPPED 2026-05-15 evening

**Status**: full-BI surface integrated into Diamond. Self-hosted, save-aware,
free, AI-assistable. 4 commits + the spike.

- ✅ **Spike** — Java 21 + Metabase OSS 0.59.10 + DuckDB driver 1.5.2.0
  installed at `~/.diamond/metabase/`. 5 sample cards + 1 dashboard built
  via REST API in 8 min. Proved AI-assisted dashboard workflow works.
- ✅ **Pattern A wiring** (commit `8451168`): `src/diamond/api/metabase.py`
  coordination module (auth + cached session + `repoint_active_save()`).
  `POST /api/saves/active` extended: PUT new database_file + sync_schema.
  Best-effort + silent-on-failure. Verified end-to-end.
- ✅ **Port flip** (commit `0f3d4ff`): Metabase moved from `:3000` (collides
  with Next.js) to `:3001` everywhere — `metabase.bat`, `metabase.py`,
  `MetabaseWorkshop.tsx` (with `NEXT_PUBLIC_METABASE_URL` override).
- ✅ **`/explore` SSR fix** (commit `68ae5ce`): hoisted data-fetch to single
  top-level async server component (avoided inline-async-child quirk in
  Next App Router).
- ✅ **Launcher pivot** (commit `2b3f03f`): hit Metabase OSS's
  `X-Frame-Options: DENY` — interactive embedding is paid Pro only.
  Pivoted Workshop tab from iframe to launcher. Same shape as Tableau
  Desktop / Power BI Desktop sidecars. Click → opens Metabase
  full-screen in new tab. Three deep-link sub-cards. New
  `GET /api/admin/metabase-status` for same-origin liveness probe.
- ✅ **Docs**: `docs/METABASE.md` (install, ops, Pattern A, threat
  model, troubleshooting, AI workflow); `docs/DECISIONS.md` D31 +
  same-day addendum (port flip + iframe→launcher pivot).

**What this enables**: any chart Metabase supports (~30 types) against
the active save, drag-and-drop or native SQL, dashboards, parameters,
drill-through. Pattern A means save-switching in Diamond auto-syncs
Metabase. Save-agnostic cards work across saves; player-specific cards
should stay in Diamond's player page (player_ids aren't stable across
saves).

### Metabase v2 follow-ups — DEFERRED

These extend D31 but aren't blocking:

- [ ] **`diamond metabase deploy` CLI** — read YAML specs from
      `diamond/metabase/dashboards/*.yaml` and POST to Metabase API.
      Source-controlled, reproducible dashboards. Currently dashboards
      live only in Metabase's H2 metadata DB — reset Metabase = lose
      them. ~1.5 days. Highest-leverage follow-up.
- [ ] **Pre-built starter dashboards** (depends on the YAML deploy CLI):
      leaderboards explorer, distribution histograms, career-arc lineup
      compare, team season summary, pressure cohort, rookie tracker.
      ~6-8 dashboards as YAML in the repo. Auto-deployed on first run
      via the CLI above.
- [ ] **Save-switch flash UX** — currently the save-switch handler
      logs the Metabase repoint result; surface it in the UI as a toast
      ("Metabase synced" / "Metabase not running") instead of just
      logs. ~30 min.
- [ ] **Static-embed dashboards inline** — Metabase OSS supports
      static embedding (signed JWTs) for individual dashboards via
      iframe. Could add per-dashboard inline views in Diamond pages
      (e.g., a "Sox 2029 review" dashboard rendered on the cockpit).
      Different from the launcher. ~2-3 hr per dashboard.
- [ ] **Auto-launch Metabase from `dev.bat`** — currently a separate
      step. Could chain `metabase.bat /b` into `dev.bat` so all three
      processes (FastAPI / Next.js / Metabase) start together. ~30 min;
      gated on user preference (some users may not want Metabase
      always-running).

**What this means in practice**: pre-save advanced stats (wOBA / wRC+ / OPS+ /
FIP / ERA+) for any player-season — MLB or MiLB, real-history or save-era —
are now end-to-end OOTP-canonical. Every reference grid feeding the calc is
pulled from L_REF (frozen at first ingest per D27). Real-life historical
seasons backfilled into the warehouse get baselines from `lref_era_stats` /
`_era_stats_minors`, park factors from `lref_era_ballparks` (with handedness
splits for batters), and per-BIP x-stat estimates from `lref_xwoba_table`
+ siblings.

See **DECISIONS.md D26** for the layer rationale, **D27** for the per-save
freeze-at-first-ingest convention, and **DATA_NOTES.md "OOTP installation
layout"** for the source-file catalog.

**Structural requirement (D27)**: L_REF is per-save and frozen at first ingest.
On first `diamond ingest`, L_REF tables snapshot into the save's own DuckDB and
stay pinned to that vintage for the save's lifetime. Refresh is opt-in via
`diamond ingest --refresh-lref` with CLI diff preview. This mirrors OOTP's own
engine convention (save captures reference data at creation; install-folder
patches don't retroactively rewrite running saves).

Re-ranked 2026-05-13 evening based on the deep-dive of `misc/` + `database/` +
`hof/` + `colors/` + `tables/`. The misc/ analytical lookup tables jumped to
top priority — they're the single highest-leverage win in the parent folder
(swap our hand-rolled xwOBA/RE/WPA/LI math for OOTP's lookup tables, guaranteed
in-game-UI parity, ~30 minutes of CSV-loader work).

### Slice 1 — L_REF ingest layer with per-save freeze ✅ **SHIPPED 2026-05-14**

Implemented in `src/diamond/schema/l_ref.py`. 27 reference tables / 575,587 rows
loaded into per-save `<save>/diamond/diamond.duckdb` on first `diamond ingest`.

- [x] `src/diamond/schema/l_ref.py` — new ingest module with `LRefSpec` catalog,
      three-tier `HeaderStyle` parser (`AUTO` / `COMMENT` / `HEADERLESS`), and
      `ensure_lref` / `compute_lref_diff` / `refresh_lref` entry points.
- [x] **Per-save freeze (D27)** — `_diamond_settings.lref.frozen_at` is the
      single source of truth; `is_lref_frozen(con)` gate skips re-ingest when
      set. Verified: 2nd CLI invocation prints `"L_REF already frozen at ..."`
      and proceeds straight to L1 rebuild.
- [x] **Provenance** — `_diamond_settings.lref.frozen_at` (ISO timestamp),
      `lref.source_root` (install folder path), `lref.ootp_version` (e.g.
      `"27"`), `lref.table_count`, and `lref.files_json` (per-file `{mtime,
      sha1, size_bytes, rows}`).
- [x] **Refresh path** — `diamond ingest --refresh-lref` calls
      `compute_lref_diff()` to print added/changed/removed by SHA1, then
      re-ingests changed files only and updates provenance. Bare `--refresh-lref`
      with no install-folder changes prints "no changes". Implies a full L1+L2
      rebuild because downstream advanced-stat calcs JOIN to `lref_*`.
- [x] CTAS for the analytical-table tier (Tier 1, `misc/`):
      - `lref_xwoba_table` / `lref_xba_table` / `lref_xslg_table` — 106 rows each
        (LA -45 to +60, EV 50-110 wide grid)
      - `lref_xiso_table` — 6 rows (6-zone LSA classifier)
      - `lref_re288_table` — 24 rows (3 outs × 8 base states × 12 counts)
      - `lref_li_table` — 432 rows
      - `lref_wpa_table` — 480 rows
      - `lref_pi_table` — 3 rows (FB/BR/OFF)
- [x] CTAS for the baselines + park factors tier (Tier 2, `database/`):
      - `lref_pt_ballparks` 240 rows (Fenway sanity-checked)
      - `lref_era_ballparks` 3,105 rows × 155 years (Coors 1995 BPF 1.106 ✓)
      - `lref_era_stats` 156 rows (1870-2025)
      - `lref_era_stats_minors` 2,335 rows
      - `lref_era_modifiers` 153 / `lref_era_fielding` 155 / `lref_total_modifiers` 155
      - `lref_financials` 156 / `lref_weather` 513 / `lref_default_players` 12,854
- [x] CTAS for the crosswalks + history tier (Tier 3, `stats/`):
      - `lref_master` 24,746 rows (Bonds → `bondsba01` ✓)
      - `lref_milb_master` 212,325 rows (29MB)
      - `lref_teams_history` 3,142 / `lref_milb_leagues` 2,317 / `lref_milb_teams` 23,075
      - `lref_eos_rosters` 99,643 / `lref_od_rosters` 102,254
      - `lref_uni_numbers` 86,589 / `lref_series_post` 411
- [x] Wired into `build_warehouse` via `rebuild_l1_l2(...)` — fires before L1
      machinery so downstream layers can JOIN to `lref_*` (Slice 2+ work).

### Slice 2 — calculation-parity swap ✅ **SHIPPED 2026-05-14**

Implemented in `src/diamond/schema/l3_advanced.py`. Two new fact tables
materialize OOTP-canonical x-stats for every (player, year, league, level)
with BIP ≥ 30:

- `f_player_season_xstats_batting` — 20,787 rows
- `f_player_season_xstats_pitching` — 21,504 rows

Each carries `xwoba_bip` / `xba_bip` / `xslg_bip` (avg per-BIP value over
the season's BIP) plus `bip_xstat` (sample size). Reads OOTP's canonical
(LA, EV) → x-stat lookup tables out of L_REF — guaranteed to match the
in-game UI exactly.

Implementation:

- [x] Three long-form lookup views via DuckDB `UNPIVOT` over the
      `lref_*_table` wide grids: `_xwoba_lookup` / `_xba_lookup` /
      `_xslg_lookup` with columns `(la, ev, val)`. ~4,895 (LA, EV)
      cells with values; sparse/empty cells filtered out.
- [x] Per-BIP interpolation view `_f_pa_event_xstats` — for every BIP
      in `f_pa_event`, compute `xwoba_pa` / `xba_pa` / `xslg_pa` via
      1D linear interpolation along the EV axis (LA is integer in
      OOTP's at-bat dump, so no LA-axis interpolation needed). Clamps
      LA to `[-45, +60]` and EV to `[50, 110]`. Empty corners → 0.
- [x] Season aggregations: batting keyed on `batter_id`; pitching on
      `pitcher_id` (= "what contact did the pitcher allow?").
- [x] Wired into `PlayerAdvancedBattingRow` / `PlayerAdvancedPitchingRow`
      Pydantic schemas + the `/api/players/{id}` route via LEFT JOIN
      (NULL-safe for pre-2026 seasons predating `f_pa_event` coverage).
      Player page Advanced columns now show `wOBA | xwOBA` side-by-side.
- [x] Added `xwOBA` / `xBA` / `xSLG` to the leaderboards stat catalog
      under the `statcast_b` discipline. Verified: 2029 MLB top
      xwOBA-on-BIP leaders are Gunnar Henderson .315 / Kazuma Okamoto
      .309 / Arjun Nimmala .302 — sensible BIP-quality leaderboard.
- [x] Glossary entries for `xwOBA` / `xBA` / `xSLG` (with KaTeX formula
      + interpretation + caveat about K/BB/HBP exclusion from the
      BIP-only figure).

Empirical verification:
- Devers 2026-2029: actual wOBA .320-.355 vs xwOBA-BIP .264-.288 — gap
  reflects K/BB/HBP exclusion (xstats are BIP only); year-to-year trend
  matches (xwOBA peaks 2029 alongside actual wOBA recovery).
- Crochet 2026-2029 allowed-xwOBA: .277 → .266 → .236 → .237 — pairs
  with FIP 2.80 → 2.26 → 2.70 → 2.74 (BIP-quality improvement, real).

**Deferred to a future slice** (out of Slice 2 scope, but unblocked
now that L_REF is in place):

- [ ] **xISO via `lref_xiso_table`** — needs an LSA classifier first.
      The `lref_xiso_table` is keyed on `launch_speed_angle` (1-6) but
      OOTP's at-bat dump only has `(LA, EV)`, not LSA. To use the
      table, we'd need to reverse-engineer OOTP's `(LA, EV) → LSA`
      mapping. Defer until UX needs xISO specifically — `xSLG - xBA`
      already provides an equivalent contact-quality signal.
- [x] **RE24 + WPA + LI columns** ✅ **SHIPPED 2026-05-15 (D30 Slice A)**
      as new fact tables `f_player_season_leverage_batting` (32,767 rows) +
      `_pitching` (32,338) at the same grain as `_advanced_*`. WPA + LI
      from L0 game-event tables (current-year only — see caveats below);
      RE24 multi-year from `lref_re288_table` joined to `f_pa_event` via
      window-function after-state. Wired to player Advanced columns +
      leaderboards (6 new stats) + 4 dictionary entries.

      Caveats / future work tracked separately:
      - **Multi-year batter LI** — needs decoding of `lref_li_table`'s
        5-column variable-width score-diff format (col06-col14, AWAY rows
        wider than HOME rows). Per-PA LI lookup at f_pa_event grain unlocks
        batter LI + Clutch and 2026-2028 LI for pitchers.
      - **Multi-year WPA** — would require persisting per-PA win-prob
        lookup against `lref_wpa_table` instead of summing L0's per-game
        column (which only ships current year). Same shape as the batter LI
        slice.
- [ ] **Barrel/SS/HH redefinition** — current Statcast cohort uses
      Statcast-standard EV+LA bands. Could swap to OOTP-empirical
      barrel definition once LSA is reverse-engineered (xiso_table
      shows LSA=6 = "barrels" with 69% HR rate per OOTP's empirical
      table). Defer with xISO.

### Slice 3 — era-aware park factors (D22 v2) ✅ **SHIPPED 2026-05-14**

Implemented in `src/diamond/schema/l3_advanced.py`. `_park_factor_resolved`
swapped from `history_lahman_teams` to `lref_era_ballparks` (3,105 rows
1871-2025); LH/RH split columns added; batter handedness blend in builder.

- [x] `_park_factor_resolved` reads from `lref_era_ballparks` with 6 PF
      columns (Overall + LH + RH for both bat and pit sides). Modern
      (≥ 2026) rows fall through to `parks.avg` with splits collapsed
      to Overall.
- [x] `f_player_season_advanced_batting` builder applies handedness:
      bats=R → bat_park_avg_rh, bats=L → bat_park_avg_lh, bats=S →
      0.6×rh + 0.4×lh blend (Tango convention).
- [x] Soft-skip predicate flipped from `history_teams_loaded` →
      `lref_era_bp_loaded` (L_REF always present on Slice-1+ saves).
- [x] Verified pre-2026 numbers shift toward BBR for handed hitters in
      handed-PF parks: Bonds 2001 OPS+ 267→262 (BBR 259), Walker 1999
      215→191, Mantle 1956 220→219, Pujols 2003 193→190 (BBR 189).
      Modern Devers 2026-2029 invariant.

**Pitcher-side handedness deferred** to a follow-on — applying it
requires weighting opposing-batter mix per (pitcher_throws, league-year),
a richer model. Pitcher park_avg keeps using Overall today.

### Slice 4 — D20 v2 (replace Lahman+BREF UNION with era_stats) ✅ **SHIPPED 2026-05-14**

Implemented in `src/diamond/schema/l3_advanced.py`. The 4 prior CTEs
(lahman_bat, bref_bat, lahman_pit, bref_pit) + all_bat / all_pit UNION
collapsed into a single `mlb_joined` CTE reading from `lref_era_stats`.

- [x] Single OOTP-canonical source (1870-2025 in 156 rows × 82 cols).
- [x] No 2019/2020 boundary; era_stats covers the whole range uniformly.
- [x] Drops external Lahman+BREF fetch dependency for league constants.
- [x] Soft-skip predicate flipped from `history_loaded` → `lref_era_loaded`.
- [x] Verified: Bonds 2001 OPS+ 267, Pujols 2003 193 (BBR 189 — exact),
      Trout 2018 201 (BBR 198) — values within ±1% of pre-swap (both
      sources trace to the same aggregates).

### Slice 5 — MiLB pre-save baselines ✅ **SHIPPED 2026-05-14**

Implemented in `src/diamond/schema/l3_advanced.py`. Closes the long-
deferred backlog item where pre-2026 MiLB player-seasons rendered `—`.

- [x] `milb_xwalk` CTE hardcodes 11 (save_league_id, era_stats_minors
      League name) pairs covering all MiLB leagues with substantive
      Lahman MiLB coverage: IL/PCL (AAA), EL/SL/TL (AA), NWL/SAL/MWL/
      CAL/CAR (A+/A), FSL.
- [x] `milb_level_per_league` derives level_id from save's own
      `f_player_season_batting` so the view works against per-save scope
      customizations (D3 v2.1).
- [x] `milb_joined` CTE produces same column shape as `mlb_joined`,
      UNION ALL'd into `joined`. Reuses BFP as lg_pa, recovers SF from
      `'SF/(IPouts-K)' × non-K-outs`, runs from `'Runs per 27 IPouts'
      × IPouts/27`, ER from `ERA × IPouts/27`. Pitcher-side aggregates
      (HR allowed / BB / HBP / K) reuse batter-side league totals by
      identity.
- [x] Verified: 84,000 newly-resolved player-seasons (pre-2026 MLB+MiLB
      with non-null wOBA went from ~88k MLB-only → ~172k). Real
      historical AAA legends resolve: Joe Lis 1972 IL wRC+ 289, Willie
      McCovey 1959 PCL 284, Trout 2012 PCL 190, Walker 1989 EL 174.
- [x] PCL 2012 lg_obp .343 vs IL 2012 lg_obp .329 — properly
      differentiated (PCL historically more offense-friendly).

**Levels still uncovered** (no era_stats_minors data):
- level_id=5 (Short-Season A), 6 (Complex/DSL), 7 (Rookie), 8 (AFL).
  Lahman has no meaningful coverage either; defer.

### Slice 6 — ballpark integration 🟡 **DATA LAYER SHIPPED 2026-05-14**

- [x] `/api/parks` route reads from `lref_pt_ballparks` and returns
      all 240 modern parks with 7-segment geometry + LH/RH split
      factors. Files: `src/diamond/api/schemas/parks.py`,
      `src/diamond/api/routes/parks.py`.
- [x] **Frontend swap** ✅ **SHIPPED 2026-05-15 (D30 Slice C)** —
      `StadiumSprayChart` accepts a `parksApi` prop carrying
      `/api/parks` data; adapter (`stadiumFromApi`) maps the
      7-segment OOTP geometry to the renderer's existing 5-point
      spline (LL→lf_line, LCF→lcf, CF→cf, RCF→rcf, RL→rf_line).
      Hand-coded `web/lib/stadiums.ts` retained as fallback for
      missing parks + cosmetic feature flair (Green Monster, ivy,
      splash hits, etc. — those stay hand-coded since they're
      not in OOTP's data model). Player page fetches /api/parks
      in parallel with player+glossary+batted-balls+save.
      Verified Fenway: API LL=310 / LCF=379 / CF=390 / RCF=383 /
      RL=302 + walls 37/9/3 — corrects the dead-CF wall (9 OOTP
      vs 17 hand-coded — 17 was the LCF triangle, not dead-CF).

- [ ] **Full 7-segment renderer** (future) — render 7-anchor
      outline instead of 5 (LL + LF + LCF + CF + RCF + RF + RL).
      Adds power-alley bumps + matches the OOTP visual exactly.
      Touches the Catmull-Rom spline math. Deferred — current
      5-point view is visually accurate to within 1-3 ft.

### Slice 7 — OOTP↔Lahman crosswalk swap ⏸ **SKIPPED — partial value, deferred**

After audit, `lref_master` carries:
- `playerid` (OOTP) ↔ `lahmanID` ↔ `retroID` ↔ `BBrefMiLBid` (minor-league)
- bio info: `birthYear`/`birthCountry`/`namefirst`/`namelast`/`college`
- ratings hints: pitch-type ratings, position experience, ethnicity

But it does NOT carry `mlb_id` (MLB.com modern API id) or `BBrefMLBid`
(major-league BBref id). All current Chadwick consumers in Diamond
go from `mlb_id` → `bbref_id`:
- `hof.py:97`  HoF candidates from MLB API
- `l3.py:1153` Awards external_id resolution
- `l3.py:1428` Award career rollup

So lref_master can complement (player bio enrichment, retroID lookup
for an OOTP playerid) but **cannot replace** Chadwick for the existing
mlb_id-keyed paths. Slice 7's framing in the original D26 backlog was
overstated. Closing as skipped; revisit if a future slice needs the
bio enrichment.

### Slice 8 — real team logos rendering ✅ **SHIPPED 2026-05-15 (D30 Slice B)**

- [x] `/api/photos/teams/{team_id}.png?size=N` route streams the
      pre-rendered PNG from `<save>/news/html/images/team_logos/`
      (resolved via `teams.logo_file_name`). Snaps the size param to
      OOTP's nearest pre-rendered variant (16/25/40/50/110/full); falls
      back to full-size if the requested variant doesn't exist.
- [x] No filename map needed — OOTP's `teams.logo_file_name` column
      points directly at the right file. Per-era variants out of
      scope (modern logos only).
- [x] New `<TeamLogo teamId={...} abbr={...} size={...} />` component
      (`web/components/TeamLogo.tsx`) with abbr-pill fallback on 404 /
      network failure. Wired into:
      - cockpit standings strip
      - cockpit spotlight cards (`CockpitSpotlightCard.team_id` added)
      - league standings page rows
      - movements ledger (`<MoveArrow>` puts logos on either side of
        the from→to arrow, handling all 4 direction shapes)
      - leaderboards team column
      - player page bio header

- [ ] **Roster page logo column** (future) — current roster groups by
      level only (not per-team), so this is a smaller win. Punted.

### Slice 9 — real HoF plaques on `/history/hof` ✅ **SHIPPED 2026-05-15 (D30 Slice D)**

- [x] `GET /api/photos/hof/{bbref_id}.png` streams from install `hof/`
      folder (NOT save folder — install ships ~8 marquee plaques).
      Strict bbref_id allowlist (`[a-z0-9.]{1,12}` — covers Lahman's
      `.` placeholder for double-initial pads like `sabatc.01`).
- [x] `GET /api/photos/hof` manifest endpoint enumerates the bbref_ids
      that actually have a PNG on disk, joined to OOTP's `index.json`
      metadata (name + induction line). Frontend uses this to render
      only gallery slots that will load — skips 192 of 200 inductees
      that would 404-spam.
- [x] `HofPlayer.bbref_id` resolved via name + birth-year-disambiguated
      JOIN against `history_lahman_people` (NOT lref_master — that
      lacks `bbrefMLBid` per Slice 7's findings). Resolves for hundreds
      of real-life HoFers (Cabrera, Pujols, Cano) even though only 8
      plaque PNGs ship — sets up future plaque additions to Just Work.
- [x] Frontend gallery: `/history/hof` (inductees view) gets a
      horizontal-scroll plaque gallery above the inductees table.
      Each thumbnail (140×180 px, lazy-loaded) shows player name +
      induction line; clicking deep-links to `/player/{id}` when
      resolvable, else opens the PNG in a new tab.
- [x] Verified: 7 of 8 plaques deep-link to active save inductees
      (Griffey Jr is the outlier — only Sr is in this save's data;
      gallery still renders the plaque, link opens PNG directly).

- [ ] **Inline thumbnail per inductee row** (future) — would require
      server-side downsampling (each plaque is 5-8 MB at full res; 285
      rows × 5 MB = 1.4 GB cache). Pillow dep needed. Deferred.

### Slice 10 — schema doc fold + per-team brand colors ⏸ partially blocked

**Brand colors blocked**: After auditing `colors/*.xml`, the files
turn out to be **uniform-asset metadata** (pointing to .oi PNG files
for caps/jerseys/pants/socks per uniform variant), not hex color
palettes. D26's "per-team brand palettes" framing was wrong. No
parseable hex/RGB values available in the install folder.

If brand colors become a real UX need, source from the team logo
.oi PNG files (extract dominant colors via image-processing) — but
that's substantial work for marginal gain.

**Schema doc fold** (separable):

- [ ] Read `database/db_structure_ootp27_csv.txt` (version-current, replacing
      our ootp21 fallback) and fold canonical column meanings into
      `docs/DATA_NOTES.md` + `docs/SCHEMA.md`. Stop reverse-engineering.
- [ ] Parse `<ootp>/colors/<team>.xml` files into a small lookup (team_abbr →
      primary/secondary hex). Wire into standings rows + player-page bio header
      as accent stripes / colored chips. Cosmetic but visibly elevates the IA.

---

## Wave-2 UI polish (D25 follow-ons)

The LSEG density refactor (D25, 2026-05-13) shipped the structural shifts.
These are the visual polish follow-ons:

- [ ] **Sharp-corner pass** — drop most `rounded-lg` to `rounded-sm` /
      `rounded-none` for full LSEG utilitarian feel.
- [ ] **Cockpit multi-pane** at 2xl — push standings + pressure + recent-moves
      into a 3-column grid instead of stacking.
- [ ] **Player page two-column** at xl+ — bio sidebar on left, tab content on
      right. Saves ~400px of vertical scroll.
- [ ] **Table density** — bump rows from ~32px to ~24-26px, smaller column
      headers (matches LSEG dense-table aesthetic in the Market Monitor /
      Economic Monitor screenshots).
- [ ] **Sub-tab pattern** on `/league` and `/history` — inline secondary tabs
      (Standings | Leaderboards | Compare | Awards) instead of separate routes.
- [ ] **Color-blind mode v2** — extend `cb` theme to swap verdict / badge
      palettes (currently chrome-only).

---

## 🔬 L_NEWS layer — DEFERRED (D28)

After the 2026-05-13 evening deep-dive of `<save>/<save_name>.lg/`, we
identified the `temp/text_data.sqlite3` SQLite database as a potential
augmentation source. **Deferred per D28** — dumps remain primary; L_NEWS
is the option-to-pull-in-later if a UX need surfaces. Do NOT implement
ahead of the L_REF slices above unless explicitly asked.

The SQLite is empirically stable across 4 seasons in the canonical save
(append-only by source `*_id`) but lives under `temp/` which is a
yellow flag for long-term dependence. When L_NEWS lands, it follows a
**per-save append-only mirror pattern** (different from L_REF's
freeze-at-first per D27) — copy SQLite rows into per-save DuckDB tables
keyed by source `*_id`, never re-read old rows, independent of OOTP's
`temp/` retention.

### Three uplift areas L_NEWS would unblock

1. **Movements augmentation** — replace our snapshot-diff inferred
   `transaction_type` in `f_l3_player_movements` with OOTP's authoritative
   `league_transactions.transaction_type` integer code (sign / release /
   trade / call-up / send-down / DFA / Rule 5 / etc.). Cross-validates
   against snapshot-diff for any deltas. SQLite has 149,769 transactions
   in this save with date + type + narrative.

2. **Player career bio timeline (NEW capability)** — `player_history`
   table has 314,678 dated narrative rows ("Drafted by Colorado in 46th
   rd from Gilbert HS, AZ", signed-bonus, debut, traded-to, awards,
   retired). NO dump equivalent. Would land as a new "Career Timeline"
   section on the player page below the bio header.

3. **League / team news ticker (NEW capability)** — `league_news`
   (16,718) + `team_news` (43,206) give dated news headlines. NO dump
   equivalent. Cockpit headline ticker + per-team news feeds. Tag format
   is HTML anchors `<a href="../players/player_<id>.html">Name</a>` so
   we can deep-link into player/team pages.

### Sketch implementation (when not deferred)

- [ ] `src/diamond/schema/l_news.py` — new ingest module reading from
      `<save>/temp/text_data.sqlite3` via DuckDB's `sqlite_scanner`
      extension or direct `sqlite3` library.
- [ ] **Append-only mirror** — `INSERT INTO lnews_league_news SELECT *
      FROM read_sqlite(...) WHERE news_id > (SELECT COALESCE(MAX(news_id),
      0) FROM lnews_league_news)`. Same pattern for transactions /
      player_history / injuries / draft_log.
- [ ] Tables: `lnews_league_news`, `lnews_team_news`,
      `lnews_league_transactions`, `lnews_team_transactions`,
      `lnews_player_history`, `lnews_league_injuries`,
      `lnews_league_draft_log`.
- [ ] Skip `messages/*.txt` (per D28 — dropped); skip ephemeral
      `news/html/box_scores/*.html` and `replays/*.rpl` (per D28 — never
      depend on).
- [ ] Decode `transaction_type` integer codes — likely an `IntEnum` in
      `src/diamond/constants.py` once we sample enough rows to verify.
- [ ] HTML-anchor parser — small util to extract `(entity_type, id,
      display_name)` tuples from `<a href="../{type}s/{type}_{id}.html">
      {name}</a>`. Trivial regex.
- [ ] `/api/news?league_id=&limit=` and `/api/news/team/{team_id}` and
      `/api/players/{id}/timeline` endpoints.
- [ ] UI: cockpit headline ticker; player-page Career Timeline section;
      per-team news feed on team page (when team page lands).

### Why deferred

- L_REF (D26 + D27) is committed and ready to implement. Layering
  L_NEWS on top of unimplemented L_REF risks scope creep.
- All three uplift areas are augmentations or new-capability — none
  block existing functionality.
- SQLite stability evidence is encouraging but `temp/` path leaves room
  for future surprise; the mirror layer to make us independent is
  itself ~half the L_NEWS work.
- User explicitly chose to keep monthly dump cadence in 2026-05-13
  conversation — strong signal that "intramonth freshness" isn't
  a current priority.

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
- [x] Build derived `player_movements` table from snapshot diffs + `trade_history` —
  done 2026-05-05. `src/diamond/schema/l3.py` first L3 table. 95,643 movements
  across 45 dumps.
- [x] **Trade attribution on `player_movements`** — done 2026-05-06.
  Added `f_trade_participant` (long-format trade roster, 1,275 rows) and a
  `trade_id` column on `player_movements` populated via org-rolled-up
  from/to-team match + ±60-day window. Coverage: 1,270/1,275 trade
  participants (99.6%) attributed to their trade; all 445 trades have ≥1
  matched player; the 5 residuals are DFA-paired/release-after-trade
  edge cases. The `<entity:type#id>` summary parser remains a separate
  carry-forward item — structured columns covered the use case without
  it.
- [x] **Refine `movement_type` taxonomy** — done 2026-05-06. Replaced the
  generic `team_change` label with 5 specific subtypes:
  `trade` (1,270), `promotion` (20,141), `demotion` (18,325),
  `intra_org_lateral` (6,288), `waiver_or_other` (4,772). Uses the
  parent_team_id org rollup + level comparison the trade attribution
  already needed. Now downstream queries can ask "all of Mayer's
  promotions" or "Sox 2029 call-up wave" directly. See DATA_NOTES.md
  for the full enumeration.

**Phase 2 (Schema & Ingest) closed.** Move on to UI phase.

## Audit phase — carry-forward (recategorized 2026-05-17 evening per D40)

Items that surfaced during Phase 1 but didn't need to be closed for the schema
to proceed. Per D40, each is now assigned a closing phase. **Phase 4a closes
the must-resolve subset; Phase 5+ inherits orthogonal items; permanent
limitations move to DATA_NOTES.md.**

### Closes in Phase 4a (Audit Closure)

- [ ] **Multi-level OPS+/ERA+ refinement** — ~5-10pp error on ~12 players who
  split a season between MLB and AAA. Hypothesis: OOTP applies a level-weighted
  park factor. To investigate: extract per-level slash + park factors, compute
  weighted average, compare to IE. **Phase 4a deliverable #6.**

- [ ] **hit_loc semantic decoding** — Pull/Cent/Oppo% jumped to 38-56% in D39
  but the residual gap requires (stadium handedness × pull-tendency × pitch-type).
  Phase 4a #5 decodes every hit_loc code (0-77 + 87 + 98-105) to a field zone
  for the IFH% unlock + Phase 4b per-player spray refinement input. **Phase 4a
  deliverable #5.**

### Closes in Phase 5 (Almanac) — orthogonal to Phase 4 work

- [ ] **Decode `<entity:type#id>` tags** in `trade_history.summary` for richer
  structured parsing (`<Houston Astros:team#12>`, `<Bryan King:player#20728>`).
  99.6% trade-participant coverage already lands via structured columns. The
  tag decode unlocks 3-team trade narrative, draft-pick / cash / IAFA flows,
  and PR copy generation — natural fit alongside the Almanac trade-history
  pages in Phase 5.

### Marked as permanent limitations (see DATA_NOTES.md)

- [x] **`leader.category` codes 44 + 49** — 11/13 resolved 2026-05-05 (coverage
  58/60 = 97%). Codes 44 (pitching rate ~8-10) and 49 (pitching rate ~47-70)
  remain unidentified after exhaustive candidate ruling-out. **Permanent
  limitation** — accepting 97% category coverage.
- [x] **OOTP "developed pitch" state** — Shea Sprague PIT mismatch confirmed
  2026-05-05 as structurally inaccessible. Rating thresholds, position/role,
  age/experience, rating-talent gaps, evolution patterns, and other CSVs all
  ruled out. **Permanent 1/220 (99.5%) limitation.**
- [x] **F-tier pitch-tracking columns** — 36 columns across `batting_superstats_2`
  + `pitching_superstats_2` (WH%, CH%, Z%, CL%, OS%, ZS%, SW%, OC%, ZC%, CTC%,
  FF%, BR%, OFF%, RV-FB, RV-BR, RV-OFF, RV) require per-pitch zone/type data
  that OOTP doesn't expose in any dump. **Permanent limitation — F-tier in
  DECISIONS.md D8.**

### Deferred / out-of-scope

- [ ] **Personality "Type" archetype** (Captain/Selfish/Humble/Sparkplug/etc.) —
  derived from 5 traits + scouting accuracy; out of scope for v1. Revisit if
  Phase 5 / Almanac surfaces a UX need.

## Analysis layer

Already shipped: 5-tier modern advanced stats library in `src/diamond/advanced/`
(HardHit%/SweetSpot%/Barrel%/Squared%/EV-by-batted-ball-type/spray; empirical
RE matrix + RE24 exposure + situational splits; wOBA/wRAA/wRC/wRC+/OPS+/ERA+/FIP/
Power-Speed/Speed Score/iso splits; RF/9, Catcher Framing+, OF Assist; 2-strike
and count-state splits).

### Refinements

- [x] **Park-factor integration** for OPS+/ERA+ — done 2026-05-07.
  `sabermetric.ops_plus_per_player` now applies the halved park
  factor `(1 + (parks.avg - 1) / 2)`; `era_plus_per_pitcher` applies
  the 80% factor `(1 + (parks.avg - 1) * 0.8)`. Both match the
  audit-decoded OOTP convention (Crochet ERA+ 127 vs IE 127 for Fenway
  in `reconcile.py`). Home park comes from `players → teams → parks`;
  mid-season trades attribute to the latest team.
- [x] **Custom WAR (offensive + pitching only)** — done 2026-05-07.
  `sabermetric.o_war_per_player` (wRAA + replacement-level adjustment
  / runs_per_win) gives Fangraphs-scale offensive WAR (Henderson 8.7,
  Kurtz 8.7, Judge 7.7 in 2029). `sabermetric.pit_war_per_pitcher`
  (FIP-based, replacement = lgFIP × 1.13) gives pitching WAR (Skubal
  4.1, McLean 4.1). Replacement constants:
  REPL_WRAA_PER_PA=20/600, RUNS_PER_WIN=10, REPL_FIP_MULT=1.13.
  Defensive contribution NOT folded in — these are kept as our
  "inspectable" custom WAR variants. Combined bWAR / pWAR ships
  via OOTP's directly-supplied WAR (see UI phase 2026-05-10 entry).
- [x] **Refine RE24** — done 2026-05-07. `situational.re24_per_player`
  now returns full Tango formulation `(RE_after - RE_before) + rbi`
  via `LEAD()` window function on `(outs ASC, lineup_spot ASC,
  base_state DESC)` within (game × inning × bat_team_id). Last PA
  of half-inning gets RE_after=0. Per-PA runs uses `rbi` (driven in
  on this play) rather than `r` (batter's own scoring, which OOTP
  attributes to the AB where the batter reached base). Vavra 170.4
  RE24 leads the latest dump.
- [ ] **Spray-chart visualization** — use hit_xy + hit_loc for on-field scatter
  plots per player.

### New reports / features

- [x] **Draft analyzer / "Where are they now?"** — done 2026-05-06.
  New L3 table `f_draft_class` (one row per drafted player, joining
  current status + first-MLB outcome + cumulative MLB career stats).
  CLI: `diamond draft <year> [--team <team_id>]`. Each pick is bucketed
  into `mlb_star` / `mlb_regular` / `mlb_callup` / `in_draft_org` /
  `traded_away` / `released` / `retired`. Pre-req sanity check passed:
  100% of 4 draft classes (2026–2029) retain all draftees in
  `players_current` — released and retired draftees stick around in
  the snapshot. Watch out: the synthetic `drafted` movement assigns
  `to_team_id = draft_team_id` (always MLB-level), so first-MLB
  detection has to exclude it (otherwise every draftee falsely flags
  ever_made_mlb on draft day).
- [x] **Streaks decoder** — done 2026-05-07. New L3 table
  `f_player_streak` (top-50 per streak_id × scope, ~2,100 rows) +
  CLI `diamond streaks [--all-time] [--category <id>]`. Two scopes:
  `active` (alive in latest dump) and `all_time` (every streak ever
  observed in the latest dump's `players_streak.csv`, since OOTP
  retains finished streaks indefinitely). Display labels come from
  the `StreakId` IntEnum and remain best-guess pending OOTP UI
  cross-reference; the integer code is authoritative. Charlie
  Szykowny holds the save's all-time hitting-streak record at 56
  (tying DiMaggio's real-life mark).
- [x] **Record breakers** — done 2026-05-06. New L3 table
  `f_record_player` (825 rows) with all-time MLB top-25 leaderboards
  per (scope × discipline × category) — single-season + career, batting +
  pitching, counting stats only (HR/RBI/R/H/BB/SB/2B/3B/PA/WAR for
  batting; W/S/K/IP/SHO/CG/QS/WAR for pitching). MLB-scoped
  (league_id=203, level_id=1) for v1; foreign / minor-league records
  unlock by parameterizing `RECORD_LEAGUE_ID`/`RECORD_LEVEL_ID` and
  rebuilding L3. CLI: `diamond records [--scope][--discipline]
  [--category][--limit]`. Rate stats (AVG/OBP/SLG/ERA/FIP) deferred —
  they need PA / IP gates and are better surfaced via the advanced
  stats library when needed. Path (b) (messages.csv news-feed parsing)
  remains punted; (a) covers the use case cleanly.
- [x] **Award winners leaderboards** — done 2026-05-06. Two L3 tables:
  `f_award_career_player` (career award totals per player×award, 7,063
  rows) and `f_award_franchise` (franchise totals with parent_team_id
  rollup, 1,856 rows). CLI: `diamond awards [--player <id>] [--team
  <id>] [--award <id>]`. Note: `f_award_event` only contains awards
  from in-save dumps (2026+), so career-MVP leaderboards count
  same-save wins only — pre-save real-life MVPs from Aaron Judge,
  Mike Trout, etc. are surfaced via OOTP's historical seed data
  rather than `players_awards.csv`, and showed up correctly in the
  spot-check (Ohtani 7 MVPs, Judge 6, Trout 3).
- [x] **Hall of Fame tracker** — done 2026-05-06. CLI `diamond hof`
  (lists current inductees) + `diamond hof --candidates` (top-25
  career-MLB-WAR players not yet inducted, with hardware lines).
  No new L3 table — surfaces directly off `players_current`
  (`hall_of_fame` + `inducted` cols) joined to `f_award_career_player`.
  In a fresh save these cols are 0 across the board until enough
  in-game years pass; `--candidates` is the useful-now mode. Updated
  2026-05-06 to also surface real Cooperstown via Lahman (340+ inductees).
- [x] **Backfill MLB historical data (Lahman + Statcast)** — done
  2026-05-06. New `diamond fetch-history` CLI loads `history_lahman_*`
  (8 tables, ~140k rows for batting/pitching/awards/HoF/all-star/teams)
  and `history_statcast_*` (~11k rows for season-aggregated EV/barrel
  leaderboards). One-time backfill capped at `save_start_year - 1` so
  OOTP's universe owns save start onward. f_record_player and
  f_award_career_player gained a `source` column ('save' | 'lahman'),
  with --era flag on the records/awards/hof CLIs. Bonds 73 (2001) now
  shows as the all-time MLB single-season HR record; Mantle/Schmidt/Pujols/A-Rod
  surface in MVP leaderboards alongside Ohtani / Judge.
- [x] **Fill 2020-2024 Lahman gap via Baseball-Reference** — done
  2026-05-06. New `history_bref_batting` (4,112 rows) +
  `history_bref_pitching` (4,794 rows) tables. `diamond fetch-history`
  pulls them automatically; `--skip-bref` opts out. UNION'd into
  f_record_player as source='bref'. SHO + CG categories stay
  save+lahman-only because BREF season frames don't expose them.
  Awards UNION not added — BREF doesn't carry award data.
  Pujols Lahman 656 + BREF 30 now correctly merge to 686 HR via
  the cross-source player linkage shipped same-day (see below).
- [x] **Add Statcast record categories** — done 2026-05-06.
  `f_record_player` UNIONs `history_statcast_batting_season` with
  source='statcast' for season + career: MAX_EV, AVG_EV,
  HARD_HIT_PCT, BARREL_PCT, SWEET_SPOT_PCT, MAX_DIST. Career rows
  use MAX-aggregable stats only (rate-stat career rollups need
  PA-weighted aggregation; deferred). Cruz 122.9 mph (2025) leads
  all-time max EV; Judge 27.5% barrel% (2023) leads season barrel%.
  Pitching Statcast (`history_statcast_pitching_season`) loaded but
  not yet UNION'd — backlog item below.
- [x] **Pitching Statcast records** — done 2026-05-07.
  `history_statcast_pitching_season` (6,060 pitcher-year rows,
  2015-2025) joined into `f_record_player` as
  `discipline='pitching'` + `source='statcast'`. New `direction`
  column on `f_record_player` (`'asc'` or `'desc'`) drives
  ranking — pitching rate-stats-allowed (AVG_EV, HARD_HIT_PCT,
  BARREL_PCT, SWEET_SPOT_PCT) sort ASC (lowest = rank 1, the
  achievement); MAX_EV / MAX_DIST sort DESC (peak feat). The CLI
  renderer prefixes leaderboards with "Fewest" or "Most" based on
  direction. Spot-check: Brad Ziegler 0.6% barrel% allowed in 2017
  leads single-season; Logan Henderson 122.9 mph leads max-EV-
  allowed (2025). Hoby Milner 80.4 mph leads single-season avg-EV-
  allowed (2017).
- [x] **Save-side EV records** — done 2026-05-07. New CTE
  `save_ev_season` aggregates per-batter (year × team) BIP from
  `f_pa_event` to produce season MAX_EV / AVG_EV / HARD_HIT_PCT
  with a 50-BBE qualifier (matches Statcast loader `minBBE`).
  Career rows take per-batter MAX. UNION'd into f_record_player
  as `source='save'`, discipline='batting'. Calibration probe
  (year 2029 MLB): OOTP league-avg EV is **~5 mph lower** than
  real Statcast (save 82.9 vs real 88-89), and OOTP's top-end
  avg-EV stars sit ~5-7 mph below their real counterparts (save
  Henderson 88.5 vs real Judge ~95). HARD_HIT_PCT scales
  proportionally lower (save Judge 34.2% vs real 65%). Source-
  color in the UI tells the two scales apart; `--era statcast`
  filters to real-only. Documented in DATA_NOTES.md.
- [x] **Awards UNION dedup** — done 2026-05-07. Replaced the
  previous {save, lahman, mlbapi} 3-source design with {save,
  merged} via bbref_id collapse. Lahman 1871-2017 awards +
  All-Star events + MLB Stats API 2018+ awards now roll up into
  a single 'merged' career-row per (bbref_id × award × league),
  filtered to bbref_ids NOT active in the user's save. Active
  OOTP-import players (Trout, Judge, Ohtani, etc.) keep their
  pre-save real awards in 'save' source via OOTP's historical
  seed import. Bonds 7 MVPs (1990-2004) now sits alongside
  Ohtani 7 MVPs (2021-2028) in the unified leaderboard with no
  Trout double-count. CLI: `--era` enum collapsed to {all,
  save, merged}; `--lahman-id` flag renamed `--bbref-id`.
- [x] **MLB Stats API gap-fill (awards + HOF 2018-2025)** — done
  2026-05-06. Lahman caps awards at 2017 + HOF at 2018; the MLB Stats
  API (`statsapi.mlb.com/api/v1/awards/<ID>/recipients`) fills the
  gap. New `history_mlbapi_awards` (377 rows: MVP/CY/ROY/GG/SS/Reliever/
  WSMVP for 2018-2025) and `history_mlbapi_hof` (28 rows: Jeter
  '20, Walker '20, Big Papi '22, Rolen '23, Helton/Mauer/Beltré '24,
  Wagner/Sabathia/Ichiro '25, Beltrán/A-Jones/Kent '26). UNION'd into
  f_award_career_player with `source='mlbapi'`, dedup'd to bbref_ids
  NOT in save (active players already have real awards via OOTP
  import). HoF view now shows real Cooperstown through 2026 in
  `diamond hof --era lahman`. Linked via Chadwick Register (mlb_id
  → bbref_id).
- [x] **Cross-source player linkage** — done 2026-05-06. Discovered
  OOTP `players_current.historical_id` IS bbref_id natively for
  real-life imported players (1,699 of 15,940 in current save —
  Judge='judgeaa01', Trout='troutmi01', Ohtani='ohtansh01' etc.).
  So OOTP↔Lahman is direct; only BREF/Statcast need crosswalk.
  Pulled Chadwick Register via `pybaseball.chadwick_register()` →
  `history_player_id_map` (26,046 rows: bbref_id, mlb_id, retro_id,
  fangraphs_id, name, played_first/last). New `_build_f_record_player`
  career-dedup logic: save-rows win; non-save lahman+bref+statcast
  rows for the same bbref_id collapse into a single 'merged' source
  row with summed value. Pujols now correctly shows 686 HR
  (Lahman 656 + BREF 30) as one career row. Awards UNION dedup
  not yet wired (followup).

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

- [x] **Reference scope expansion** (per D13) — done 2026-05-07.
  `SaveConfig.reference_scope_enabled` field added; `_scoped_players`
  builder UNIONs org-tier with the ≥1-MLB-appearance cohort (PA OR IP)
  when enabled. CLI `--reference-scope` / `--no-reference-scope` flags
  toggle + persist in new `_diamond_settings` admin table. Empirical
  expansion: 15,992 → 35,261 players (+19,269) on the live warehouse.
  Smoke test exercises both modes. Cohort refined from D13's original
  "≥1 PA" to "PA OR IP outs ≥ 1" so universal-DH-era relief pitchers
  aren't dropped (3,022 such in this save).
- [x] **Stat dictionary + glossary** (per D15) — thin v1 done 2026-05-07.
  `src/diamond/dictionary/{__init__.py, _stats.py}` module ships the
  `Stat` frozen dataclass + `CATEGORIES` tuple + `STATS` dict with 39
  entries (slash + counting batting / advanced / pitching / value /
  statcast / fielding). `diamond glossary` CLI renders terminal +
  markdown views (`audit_output/glossary.md`); smoke Phase G
  validates required fields, category enum, related-id resolution,
  id uniqueness. Long-tail entries (~110 more) land as UI screens
  reach for them per the maintenance contract — strict rule: any new
  UI label MUST come from the dictionary.
- [x] **Tech stack pick** (per D16) — locked 2026-05-07. FastAPI +
  Next.js (App Router) with Pydantic-derived TS types. Tailwind +
  KaTeX + react-katex base; shadcn/ui + Vega-Embed + Plotly +
  TanStack Table deferred until features need them.
- [x] **API + web scaffold** — done 2026-05-07, **verified live**.
  `src/diamond/api/` (FastAPI app with health + glossary routes,
  Pydantic schemas), `web/` (Next.js 15 App Router + Tailwind +
  KaTeX, glossary list + detail pages), `scripts/generate_types.py`
  (Pydantic → TS pipeline), `Makefile`, `docs/DEV.md` setup guide.
  End-to-end browser flow validated: home → /glossary → /glossary/wOBA
  with KaTeX-rendered MathML + related-stat chips + Fangraphs link.
- [/] **Player page** — Bref-shaped layout, Savant-styled visuals, AI assistant.
  - [x] **Stats tab v1** — done 2026-05-07. `GET /api/players/{id}` +
    `/player/[id]` route. Bio header (name, nick, position, B/T,
    current team, retired/HoF flags) + tab strip (Stats active;
    Charts/Game log/Comparisons/Scouting/Contract placeholders).
    Bref-shaped batting + pitching disclosure rows: per-year row
    (combined "TOT" if multi-stint, single stint otherwise), click
    chevron to expand per-(level, team) sub-rows. Career-totals row
    pinned at table bottom. Column headers + tooltips read from
    `STATS[id]` (D15 contract); dictionary expanded by 13 entries
    (G_batter, AB, H, D, T, L, G_pitcher, GS, ER, H_allowed,
    R_allowed, HR_allowed, BB_allowed). Smoke tested live: 16-yr
    Carlos Rodón career renders w/ 1796⅓ IP, 3.92 ERA; 5-stint
    2029 Raymer Medina with synthesized TOT + indented stints
    expanding correctly.
  - [x] **Fielding subtable** — done 2026-05-07. Per-(year, position,
    team) flat rows + per-position career rollups. Dictionary +8:
    G_fielder, GS_fielder, INN, PO, A, E, DP, FPCT. Cross-position
    totals deliberately omitted (combining PO+A+E across positions
    doesn't carry useful semantics; explainer line in the UI when a
    player has multi-position career rows). Smoke verified live with
    Samad Taylor (7-position UTIL) and Carlos Rodón (pitcher-only
    fielding).
  - [x] **Advanced stats column block** — done 2026-05-07. New L3
    module `src/diamond/schema/l3_advanced.py` materializes
    `f_player_season_advanced_batting` + `_advanced_pitching` per
    (player, year, league_id, level_id). Park-aware (halved for OPS+,
    80% for ERA+), league-constants-aware. UI renders "Advanced
    Batting" + "Advanced Pitching" sections below the standard
    counting tables. Math verified: Crochet 2029 ERA+=127 ✓
    (audit IE-reconciled), Skubal FIP 2.65 ✓, Gunnar Henderson
    oWAR 8.7 ✓.
    - Note: league_history coverage is 2026-2029 in this save.
      **D20 (2026-05-12)** closes the pre-save MLB gap by UNIONing
      Lahman 1871-2019 + BREF 2020-2025 league aggregates into
      `_lg_constants_advanced` via `_lg_constants_advanced_imported`.
      f_player_season_advanced_batting 30k → 244,183 rows; Bonds 2001
      OPS+ 257 (BBR 259), Pujols 2003 OPS+ 189 (BBR 189 — exact),
      Trout 2018 OPS+ 198 (real 198 — exact). Minor-league pre-save
      seasons remain null (Lahman MiLB coverage is spotty; OOTP↔real
      league_id crosswalk non-bijective). Pre-2026 park factors fall
      back to the team's *current-day* park — small bias on OPS+/ERA+
      only; wOBA/wRC+/wRAA unaffected. See DECISIONS D20 + DATA_NOTES.
    - Statcast advanced (MAX_EV / AVG_EV / barrel%) materialized
      2026-05-09 as two new L3 tables (`f_player_season_statcast_*`)
      and surfaced on the roster Contact mode. Player-page version
      is the natural follow-on.
  - [ ] **Charts tab** — radial career arc (angular = year, radius
    = headline stat: OPS+/wRC+/WAR/ERA+, color = team or level).
    Per the design discussion 2026-05-07: radial earns its keep as
    a viz, not a navigation aid. Optional: clicking a wedge scrolls
    Stats tab to that year.
  - [ ] **Other tabs** — Game log, Comparisons, Scouting, Contract.
    URL pattern `/player/<id>/<season>` (per-year zoom) blocked on
    Stats tab v2.
  - [ ] **Right-rail AI assistant** (per D14) — defer until AI
    overlay scaffolding lands.
- [x] **Movement ledger** (the v1 form of the GM-sidekick demotion/
  promotion tool) — done 2026-05-08. `/movements` page + `GET /api/
  movements?year=YYYY` endpoint. Four direction buckets — internal
  (promotion/demotion), incoming (trade/signed/waiver_or_other from
  outside), outgoing (released/trade/waiver to outside) — with
  level-aware verdicts (MLB ≥100 = working, lower levels ≥90) and
  inverted semantics on departures. Pending-rows (too-small sample)
  hidden by default with a `?include_pending=1` toggle. Real signal
  surfaced six 🔴 departures in 2029 Red Sox (Bello 163 ERA+,
  Cespedes 146 OPS+, Ehrlicher 142 ERA+, Fis 186 ERA+, Primera 151
  OPS+, Urbina 141 OPS+).
- [x] **IA backbone** (D17) — done 2026-05-08. Five-tab nav: Club /
  League / World / History / Explore + Glossary + ThemeSwitcher + Quit.
  League / World / History / Explore are routable stubs via the
  shared `TabStub` component; each lights up section-by-section as
  content lands.
- [x] **Real landing page (Club view v0)** — done 2026-05-08.
  `/api/save` returns save identity + warehouse health; `/` renders
  org header + status grid + tools card list with `Live` / `Soon`
  pills. The placeholder three-link home is gone.
- [x] **Theme system** (D18) — done 2026-05-08. Light / Dark / Neutral
  / CB themes via CSS-variable tokens + Tailwind semantic-color
  extension. Dark is the default. `<ThemeSwitcher />` in header
  with no-flash init script. CB mode is chrome-only in v1 — see
  next item.
- [x] **In-app Quit + dev.bat one-shot launcher** — done 2026-05-08.
  `POST /api/admin/shutdown` reliably kills uvicorn + Next dev (all
  three pnpm-spawned node processes) + their cmd parents. Fully
  detached subprocess via `cmd /c start /B` so the kill cascade
  doesn't reach it; web-side kills run first so even partial
  detachment is robust. `dev.bat` spawns api.bat + web.bat + opens
  browser at :3000.
- [x] **Roster page** — done 2026-05-09. `/roster` lists every active
  org-tree player grouped by current level. Filter pills for Level /
  Role / Hand; **three-mode stat toggle** (Basic / Advanced /
  Contact). Server returns full ~200-player payload in one round-trip
  (~95 KB JSON); client-side filters / sort / mode. Names link to
  `/player/[id]`. Backend: `src/diamond/api/{routes,schemas}/roster.py`.
  Frontend: server page + `RosterClient` component holding filter
  state. Stats reflect the player's CURRENT-level stats only —
  cross-level totals stay on the player page so roster grouping
  doesn't conflate stints.
- [x] **Surface wRAA + wRC + park_avg** in advanced batter view — done
  2026-05-09. Were already in `f_player_season_advanced_batting`;
  pure UI work. Roster Advanced batter columns: PA · wOBA · wRAA ·
  wRC · wRC+ · OPS+ · oWAR · Park.
- [x] **Materialize SIERA** in `f_player_season_advanced_pitching` —
  done 2026-05-09. Fangraphs canonical regression on K/BB/BF/GB/FB,
  all inputs present in `f_player_season_pitching`. Verified Crochet
  2.25 SIERA vs IE-reconciled 2.27 (±0.02). Roster Advanced pitcher
  columns: IP · FIP · SIERA · ERA+ · pWAR · Park.
- [x] **Statcast cohort L3 tables** — done 2026-05-09. Two new tables
  (`f_player_season_statcast_batting` + `_pitching`) per-(player,
  year, league, level), BIP ≥ 30 threshold, materialized from
  `f_pa_event` via formulas mirroring `diamond.advanced.contact.*`.
  Surfaced via roster Contact mode: BIP / max_EV (P90) / avg_EV /
  HH% / Brl% / SS%. Pitcher rows interpret all percentages as
  allowed-contact (lower = better).
- [x] **Combined bWAR / pWAR** — done 2026-05-10. Reframed mid-slice
  after audit: OOTP **directly supplies** the canonical combined WAR
  (`players_career_batting.war` and `players_career_pitching.war` /
  `.ra9war`), already aggregated into `f_player_season_*.war`. The
  audit had been reconciling these as A-tier since 2026-05-04. No
  defensive-runs build required — OOTP bakes `zr` + `framing` +
  `arm` + positional adjustment + base-running + leverage into the
  WAR field. Slice was plumbing: SUMed across stints into the
  (player, year, league, level) grain in `f_player_season_advanced_*`,
  added new schema fields (`b_war` / `p_war` / `p_ra9_war`), surfaced
  on roster Advanced view + player page Advanced sections. Verified
  Mayer 3.2 = IE 3.2, Anthony 0.9 = IE 0.9, Crochet 5.5 = IE 5.5,
  Whitlock 0.4 = IE 0.4 — all exact. Deprecated the ambiguous `WAR`
  dictionary entry; added `bWAR` / `pWAR` / `RA9_WAR` (62 entries).
  Custom `oWAR` / `pit_WAR` stay in the warehouse as inspectable
  alternatives (gap vs OOTP value = the defensive component for
  batters / leverage + replacement-scaling differences for pitchers).
- [x] **Per-position fielding view** — done 2026-05-10. New
  "Defensive Profile" section on the player page surfaces the
  9-position scouted-rating cube. New `players_fielding_current`
  view (latest snapshot per player) registered alongside the other
  `_current` views in `l1_snapshot.py`. New `PlayerPositionFielding`
  Pydantic schema; `PlayerResponse.position_fielding` is always 9
  rows (1=P..9=RF) with zero values normalized to null so the UI
  renders em-dashes for "never rated." Sorted by experience desc
  in the UI so the "where they actually play" view comes first;
  no-data rows hidden. 20-80 rating cells color-coded (emerald
  / amber / rose). Sample signal: Justin Gonzales (POS=1B) really
  reads as a corner-OF guy — current 65 LF, 60 RF, 50 CF with
  ~200 plays at each, vs current 50 at his listed 1B.
- [x] **Service-time / arbitration clock** — done 2026-05-10. New
  "Service & Status" card on the player page (between bio header and
  tab strip). MLB service formatted Bref-style ("4y 128d"; 172 service
  days = 1 year), computed service class (Pre-arb / Arb Y1-Y3 / FA-
  eligible) with color-coded chip, days-to-FA estimate, options-used
  block, and a status-flag row (Active / 40-man / IL / DFA / waivers
  — only renders truthy ones). Backed by a new `PlayerRosterStatus`
  Pydantic schema + `_fetch_roster_status()` route handler. `years_protected_from_rule_5`
  + `has_received_arbitration` not surfaced (semantics unclear from
  data alone). Super-Two qualifiers not modeled in v1 (OOTP handles
  internally; no public flag). Verified Mayer 4y 128d Arb(Y2) FA-216d
  / Crochet 9y 28d FA-eligible / Gonzales 1y 94d Pre-arb FA-766d.
- [x] **Salary stream** *(2026-05-12)* — Contract section on player
  page. `PlayerContract` Pydantic schema flows the L1
  `contract_current` view; option types (TO/PO/VO), buyouts,
  opt-outs, no-trade flags resolved server-side. Bar-chart UI per
  year with current-year highlight + total / remaining USD totals.
  Bonus incentives (minimum_pa_bonus, mvp_bonus, etc.) and AAV
  computation skipped for v1.
- [x] **Standings page** (League tab) — done 2026-05-11. Replaced the
  `/league` `TabStub` with a real server-rendered standings view.
  `GET /api/standings?league_id=&year=` returns sub-league × division ×
  team rows from `team_record_snapshot` at MAX(dump_date) within the
  chosen year. League picker grouped by level (MLB / AAA / AA / A+ A
  / Rk DSL); year picker as a strip; user's org row highlighted with
  a left-border accent + "You" pill. Magic-number sentinels (`-1` =
  clinched, `1000` = N/A) collapse into `magic_number: int | None` +
  `clinched: bool`. Streak signed int → "W9"/"L4"/—. Sub-league/division
  null cases (AAA divisions only, AFL flat) handled. Pythagorean / RS /
  RA columns deferred (snapshot carries W-L-Pct only).
- [x] **Clutch / RISP splits on player page** — done 2026-05-12.
  New "Situational batting" + "Situational pitching" sections on the
  player page Stats tab. Four splits per (year, level): All / RISP /
  RISP 2-out / Late & Close. Slash + counting per row; OPS color-coded
  vs the All baseline (≥25 pts emerald, ≤-25 rose). Color logic
  inverts for pitchers (lower OPS allowed in clutch = better).
  Backed by `_fetch_situational(con, player_id, side)` — same SQL
  template, ``side ∈ {"batter", "pitcher"}`` selects the join
  column. Multi-year coverage as of same day. **Splits expanded
  same day from 4 to 14** in five clusters:
  - **Leverage** (4): All / RISP / RISP 2-out / Late & Close.
  - **Bases** (2): empty / loaded.
  - **Platoon** (2): vs L / vs R; side-aware labels (vs LHP/RHP
    for batter, vs LHB/RHB for pitcher); switch-hitters resolve to
    opposite of pitcher's throwing hand.
  - **Counts** (3): first pitch / two strikes / full count
    (count BEFORE the resolving pitch).
  - **Spray** (3): pull / center / oppo; BIP-only; UI skips color
    coding since denominator semantics differ from the All baseline.
- [x] **Pressure board** *(2026-05-12)* — `/pressure` lives.
  `GET /api/pressure?year=&limit=` returns per-level promotion
  candidates (top OPS+/ERA+) + pressure cases (bottom) for the
  org tree. Two-column cards per level (MLB / AAA / AA / A+ /
  A / Rk / DSL) — left = promotion, right = pressure. Color-coded
  metric cells (emerald for ≥10 above 100, rose for ≤10 below).
  Sample bars: 50 PA / 20 IP. Org scope auto-derived from
  `audit_team_id`. Cross-level reading reveals decisions: a 130
  OPS+ at AAA next to a 75 OPS+ at MLB = obvious roster swap.
  Sits as a peer page (`/pressure`) for now; renest under
  `/club/pressure` when the Club tab gets a coordinated cleanup
  pass alongside `/movements` and `/roster`.
- [x] **Compare under Explore** *(2026-05-12)* — `/explore/compare?ids=`
  lives. Side-by-side career stat blocks for ≤4 players + overlaid
  WAR sparkline. Backed by `GET /api/compare?ids=`. Cross-era is
  fair game via D20 baselines. Empty state surfaces three demo
  deep-links (Bonds·Aaron·Ruth / Trout·Ohtani·Judge / Pedro·Maddux·Clemens).
  Chart-stack decision (Vega-Lite vs Plotly) deferred — the v1
  side-by-side cards work with hand-rolled Sparkline; full chart
  lib lands when spray charts / EV-LA / distributions need it.
- [x] **Player headshots** *(2026-05-12)* — `PlayerAvatar` component
  + `GET /api/photos/players/{id}.png` streaming endpoint over the
  active save's `news/html/images/person_pictures/` directory.
  Per-image onError fallback to deterministic-color initials disc.
  Wired into player page header (lg), cockpit spotlight (sm),
  roster name cells (xs), compare cards (md). Photos exist for
  4,721 in-save players; pre-1990 imported real-history players
  fall back to initials gracefully.
- [ ] **Custom leaderboards** — Fangraphs-style sortable filterable tables.
  TanStack Table integration, filter strip across year/level/age/min-PA/
  position, save-to-URL. Curated default version under League;
  build-your-own under Explore.
- [ ] **Color-blind mode v2** — extend the `cb` theme to swap verdict
  glyphs and move-type badges away from green/amber/rose. Currently
  only chrome (page bg, accent, links) is CB-safe. Touches every
  badge in the movements page + the Free Agent / HoF pills on the
  player bio header.
- [ ] **Distributions / Spray charts / EV-LA scatter / Chart builder
  / Cohorts** — under Explore. Each is its own slice. Listed in
  Explore stub page.
- [ ] **Universes + chart builder + scatter** *(bundled)* — Vega-Lite spec
  artifact, no-size-limit cohorts (Plotly WebGL fallback at scale), set ops,
  cross-era support.
- [ ] **AI overlay** (per D14) — keyring-stored keys, pluggable provider
  adapters, OpenRouter live pricing, four use levels (Off/On-demand/Smart/
  Always-on), per-feature overrides, daily-cap auto-degrade.
- [x] **Cockpit dashboard v2** *(2026-05-12)* — `/` is now the cockpit.
  Composes save header + warehouse stats + Sox AL East standings +
  top-3 MLB promotion/pressure pairs + 6 spotlight cards (career-WAR
  Sparkline + auto-generated NLG insight per card) + last 8 movement
  ledger rows. Single round-trip via `GET /api/cockpit`. Year is
  implicit (latest); historical snapshots stay on dedicated tabs.
  Anomaly flags + Pythag still deferred — would need a per-team
  RS/RA snapshot + an "expected wins" derivation, neither of which
  is in the warehouse yet. Decisions-queue framing is implicitly
  satisfied by the pressure summary card; an explicit "your top
  regrets" view is a future slice.
- [x] **Visual upgrade — heat-scale + Sparkline + CareerArc**
  *(2026-05-12)* — three primitives for richer table rendering, all
  reusable across future leaderboard / cockpit / player surfaces.
  See CLAUDE.md "Visual primitives" section for usage.
- [x] **History view content** *(2026-05-12)* — fully drained. All
  five sections (Records / Awards / HoF / Streaks / Draft) live.
  Hub page links through to each retrospective.
  - [x] **Records** *(2026-05-12)* — `/history/records` lives.
    `GET /api/records?scope=&discipline=&category=&era=&limit=` UNIONs
    save + Lahman 1871-2019 + BREF 2020-2025 + cross-source merged
    career rollups + Statcast 2015-2025. Three flat picker rows
    (Scope / Discipline / Era) + a Category strip dynamically populated
    from `f_record_player`. Source chips color-coded per source
    (emerald=save, indigo=lahman, sky=bref, violet=merged, amber=statcast);
    rows clickable to `/player/<id>` when the row carries a save
    player_id. Server re-ranks globally when era=all; bad query strings
    fall back to defaults rather than 404'ing.
  - [x] **Awards** *(2026-05-12)* — `/history/awards` lives.
    `GET /api/awards?league_id=&award_id=&era=&limit=` returns career
    trophy-count holders for any (league × award) combination with
    era filter (all / save / real). League picker grouped by tier
    (MLB at top); award picker ordered by prestige (MVP / Cy / RoY
    / GG / SS / Reliever / All-Star / WSC / Series MVP / monthly
    awards). Per-season races deferred (need `f_award_event`-grain
    query); per-team rollups deferred (need `f_award_franchise`-grain
    query — same UI shape, different fact).
  - [x] **Hall of Fame** *(2026-05-12)* — `/history/hof` lives.
    `GET /api/hof?view=&limit=` toggles between Inductees (285
    players flagged `hall_of_fame=1`, ordered by induction year)
    and Candidates (top-25 career WAR who aren't inducted —
    Bonds / Clemens / Pete Rose / A-Rod headline the absentees).
    Career WAR aggregation pulls from
    `f_player_season_advanced_batting.b_war` + `_pitching.p_war`,
    GREATEST'd to a single per-player value. View toggle pill
    shows "·N" count hints on each side.
  - [x] **Streaks** *(2026-05-12)* — `/history/streaks` lives.
    `GET /api/streaks?streak_id=&scope=&limit=` returns top-50
    holders for any of 21 streak types × 2 scopes (active |
    all_time). Picker ordered by relevance (Hitting / Scoreless
    Innings / On-Base / Win headlines first, rare codes last).
    Active streaks render a "Live" badge instead of an end date.
    Hitting streak all-time top: Charlie Szykowny 56 games (DiMaggio
    mark).
  - [x] **Draft classes** *(2026-05-12)* — `/history/draft` lives.
    `GET /api/draft?year=` returns the entire ~600-pick class
    grouped by outcome bucket (MLB Regulars → Callups → Still
    Developing → Traded → Released → Retired). Year picker defaults
    to oldest class with material outcome variation (2026 in this
    save — fresh classes have ~570 in_draft_org rows). Class summary
    header surfaces total picks + reach-MLB% + color-coded outcome
    chips. Per-team filter deferred (30 teams = lots of pills).
    Per-class draft trade retrospectives deferred (would need to
    join `f_trade_participant` × `f_draft_class`). The 'mlb_star'
    bucket from D8's original taxonomy is unused in the L3 builder
    — only mlb_regular / mlb_callup are emitted today.
- [ ] **League view content** — Standings shipped 2026-05-11; remaining:
  leaderboards, awards races, free-agent pool. Stub-strip below the
  standings block lists what's still pending.
- [ ] **World view content** — All-leagues browser, cross-league
  movements, world rankings, international prospects. Forward-
  looking; thin until scope expands.
- [ ] **Monthly + annual reviews** — long-form AI-augmented narrative pages.
- [ ] **Setup wizard** — first-launch onboarding (per UI_DESIGN.md "Cross-cutting
  infrastructure"). Includes save-setup picker (D3 v2 fulfillment).
- [ ] **Sync triggers + tracked-save management** — app-launch scan, manual
  refresh, untrack-vs-delete-warehouse distinction.
- [ ] **Historical park factors** — D20 follow-on. Pre-2026 OOTP player
  rows currently fall back to the team's *current-day* park factor when
  computing OPS+ / ERA+, which is a modern-stadium proxy for the historical
  context (a 2001 SF Giants row resolves to Oracle's 1.003, not 2001's
  Pacific Bell). Park enters OPS+ at half-leverage and ERA+ at 80%-leverage,
  so the bias is small but real. Real fix: load BREF historical team-year
  park factors + a (OOTP team_id, year) → bbref_team_id crosswalk so the
  dominant-team join in `f_player_season_advanced_*` can pick up the
  historically correct factor. wOBA / wRC+ / wRAA aren't affected (no
  park term), so the priority is moderate.
- [ ] **Pre-save minor-league baselines** — D20 covers MLB only.
  OOTP's pre-2026 minor-league rows (IL/PCL/EL/etc., league_ids 204-218)
  still render `—` for advanced stats because Lahman's MiLB coverage is
  spotty and the OOTP↔real league_id crosswalk for those leagues isn't
  bijective. Lower priority than MLB — most users care about the MLB
  career arc on imported real-history players. If pursued, would need
  a new `history_lahman_minors_batting/_pitching` loader plus a curated
  league-id map.

## Future / nice-to-have

- [ ] Cross-save analysis support (using DuckDB `ATTACH`).
- [ ] Per-save scope picker for non-MLB worlds (foreign leagues, fictional).
