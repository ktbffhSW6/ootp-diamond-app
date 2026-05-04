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
- [x] **Custom WAR** — done 2026-05-07.
  `sabermetric.o_war_per_player` (wRAA + replacement-level adjustment
  / runs_per_win) gives Fangraphs-scale offensive WAR (Henderson 8.7,
  Kurtz 8.7, Judge 7.7 in 2029). `sabermetric.pit_war_per_pitcher`
  (FIP-based, replacement = lgFIP × 1.13) gives pitching WAR (Skubal
  4.1, McLean 4.1). Replacement constants:
  REPL_WRAA_PER_PA=20/600, RUNS_PER_WIN=10, REPL_FIP_MULT=1.13.
  Defensive contribution NOT folded in — would need RF/9 / framing
  conversion to runs-above-average (separate task).
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
  - [ ] **Stats tab v2** — fielding stats subtable (uses
    `f_player_season_fielding`; needs ~8 new dictionary entries:
    G_fielder, GS_fielder, INN, PO, A, E, DP, FPCT). Advanced-stats
    column block (wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR / Statcast
    EV+barrel) — requires either materializing
    `f_player_season_advanced_*` L3 tables (listed as future work in
    `src/diamond/schema/l3.py` docstring) or threading the existing
    `diamond.advanced.*` on-demand computations through the request
    handler.
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
