# Backlog

> Open work items, prioritized. Phases: **Schema & Ingest** (current), **Analysis
> Layer**, **UI**. Phase 1 (Audit) closed 2026-05-04 — remaining open audit items
> are carry-forward research, not blockers.

---

## 🔜 Next major work — L_REF reference layer (D26)

**Highest-priority next-up as of 2026-05-13 evening.** New ingest layer reads from
the OOTP parent folder (`<docs>/Out of the Park Developments/OOTP Baseball 27/`)
into `lref_*` tables shared across saves. See DECISIONS.md D26 for full
rationale; DATA_NOTES.md "OOTP installation layout" section catalogs the
source files.

Slice 1 — L_REF ingest layer (~90 min):

- [ ] `src/diamond/schema/l_ref.py` — new ingest module. CTAS for:
      - `lref_pt_ballparks` (240 rows) ← `database/pt_ballparks.txt`
      - `lref_era_ballparks` (3,105 rows × 155 years) ← `database/era_ballparks.txt`
      - `lref_era_stats` ← `database/era_stats.txt`
      - `lref_era_stats_minors` ← `database/era_stats_minors.txt`
      - `lref_master` ← `stats/Master.csv` (24,747-row OOTP↔Lahman crosswalk)
      - `lref_milb_master` ← `stats/MiLBMaster.csv`
      - `lref_teams_history` ← `stats/Teams.csv`
- [ ] Mtime-based skip logic — only re-ingest when source file mtime changed.
      Stored in `_diamond_ingests` with synthetic `dump_name` like `lref_<file>`.
- [ ] CLI: `diamond ingest --lref` flag (or runs automatically on every ingest;
      decide based on cost — should be ~5-10s for 6 CSV reads).
- [ ] Wire into `build_warehouse` orchestrator alongside L0.

Slice 2 — ballpark integration:

- [ ] `/api/parks` route reads from `lref_pt_ballparks`, returns full 7-segment
      geometry + LH/RH split factors per park.
- [ ] Update `web/components/StadiumSprayChart.tsx` to fetch from API instead
      of hand-coded `web/lib/stadiums.ts`. Delete `web/lib/stadiums.ts`.
- [ ] Add 7-segment outline rendering (we currently use 5 anchor points).

Slice 3 — D22 v2 era-aware park factors with handedness splits:

- [ ] Update `_park_factor_resolved` view to read from `lref_era_ballparks`
      (replaces `history_lahman_teams` join).
- [ ] Extend `f_player_season_advanced_batting` builder to read LH/RH splits
      and apply to OPS+/wRC+ via blending using player.bats.
- [ ] Verify Bonds 2001 / Pujols 2003 / Trout 2018 numbers match BBR more
      tightly than D22 v1.

Slice 4 — OOTP↔Lahman crosswalk swap:

- [ ] Replace `history_player_id_map` Chadwick lookup with `lref_master` JOINs
      in `history.py` and the records / awards / hof endpoints.
- [ ] Delete the Chadwick fetcher code if everything routes through lref_master.

Slice 5 — real team logos rendering:

- [ ] `/api/logos/{abbr}` route serves `<ootp>/logos/<filename>.oi` with
      `Content-Type: image/png` (`.oi` files are PNGs, magic-bytes confirmed).
- [ ] Logo filename map — likely a static dict extending `src/diamond/mlb_teams.py`.
      Per-era variants for historical pages.
- [ ] Replace `font-mono BOS` chips across standings / leaderboards / roster /
      cockpit with a `<TeamLogo abbr={abbr}>` `<img>` component.
- [ ] PlayerAvatar / current-team chip on player page header gets the logo.

Slice 6 — schema doc fold:

- [ ] Read `database/db_structure_complete_ootp21_csv.txt` and fold canonical
      column meanings into `docs/DATA_NOTES.md` + `docs/SCHEMA.md`. Stop
      reverse-engineering.

Slice 7 — MiLB pre-save baselines (clears v2.2 backlog item):

- [ ] Use `lref_milb_master` + `lref_era_stats_minors` to extend
      `_lg_constants_advanced_imported` with minor-league rows. OOTP-imported
      pre-2026 minor-league player-seasons get advanced stats instead of `—`.

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
- [x] **Verify 13 unmapped `leader.category` codes** — done 2026-05-05.
  Resolved 11 of 13: 21=RC (Bill James technical w/ IBB-corrected B-factor),
  22=RC/27, 24=wOBA (calibrated), 26=OPS+/wRC+ (close match, ambiguous formula),
  31=Win%, 41=Opp_BABIP, 46=HA/9, 51=GF (Games Finished), 53=QS%, 55=CG%,
  57=GB%. Coverage now 58/60 (97%). Codes 44 (pitching rate ~8-10) and
  49 (pitching rate ~47-70) remain unidentified — see DATA_NOTES.md for the
  candidates ruled out. Updated `LeaderCategory` IntEnum in constants.py.
- [x] **Investigate `Shea Sprague` PIT mismatch** — confirmed 2026-05-05 as
  structurally inaccessible. Exhaustive investigation ruled out rating
  thresholds, position/role, age/experience, rating-talent gaps,
  evolution patterns, and other CSVs. OOTP's "developed pitch" state is
  internal and not exposed in any dump column. Permanent 1/220 (99.5%
  match) limitation; count-non-zero rule stays. Full investigation logged
  in DATA_NOTES.md.
- [ ] **Decode `<entity:type#id>` tags** in `trade_history.summary` for richer
  structured parsing (`<Houston Astros:team#12>`, `<Bryan King:player#20728>`).
  Lower priority now that trade attribution lands without it (99.6%
  participant coverage from structured columns alone). Useful for
  surfacing 3-team trade narrative, draft-pick / cash / IAFA flows, and
  PR copy generation.
- [ ] **Personality "Type" archetype** (Captain/Selfish/Humble/Sparkplug/etc.) —
  derived from 5 traits + scouting accuracy; out of scope for v1.

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
