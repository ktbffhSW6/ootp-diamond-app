# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read these first

The project keeps long-running engineering context in `docs/`. Always read at the start of a session:

- `docs/PROJECT_STATUS.md` — current phase, what works, what was last done, what's next.
- `docs/DECISIONS.md` — append-only log of architectural/scope decisions with rationale (D1–D43).
- `docs/DATA_QUIRKS.md` — ⭐ **master at-a-glance reference for every OOTP-data quirk, formula calibration, permanent limitation, and display-policy decision**. Read this BEFORE re-investigating any reconcile mismatch. SEALED entries explicitly say "don't re-investigate."
- `docs/DATA_NOTES.md` — chronological deep-dive log of empirical findings, codebooks, IE display conventions. DATA_QUIRKS is the index; this is the long-form receipts.
- `docs/BACKLOG.md` — prioritized open work, grouped by phase (Schema/Ingest → Analysis → UI).
- `docs/UI_DESIGN.md` — UI build order + design conventions; committed five-tab IA + theme system live here.
- `docs/DEV.md` — two-process dev workflow (FastAPI + Next.js), `make` targets, troubleshooting.
- `docs/METABASE.md` — Metabase BI workshop (D31): install, Pattern A save-aware sync, ops, troubleshooting, AI-assisted dashboard workflow.
- `docs/DESKTOP.md` — Native desktop shell (D32): PySide6 launcher, Job Object lifecycle, PyInstaller bundle, build pipeline, troubleshooting.

These files are the source of truth for "why" — favor updating them over leaving knowledge in chat.

**Current phase: Phase 4b — Maximize the Warehouse** (in progress, ~85% shipped), then Phase 5 — Baseball Almanac, then Phase 6 (multi-save) → 7 (AI analyst) → 8 (distribution, deferred). **Phase 4a ✅ CLOSED 2026-05-10**; **Phase 4a-extended-1/-2/-3 ✅ CLOSED 2026-05-10**; **Display ditch ✅ CLOSED 2026-05-10** (D41); **L_IE display routing Slice 1 ✅ CLOSED 2026-05-14** (commit `521cc22`); **Phase 4b deferred-items chain ✅ CLOSED 2026-05-14** (pitching xstats re-enable + POW-aware calibration + batting xBA / pitching xwOBA re-enable: `8a446ec`, `b571cbb`); **Phase 4b Tier A (game-grain) ✅ CLOSED 2026-05-14** (`d7a9b7c`); **Phase 4b Tier D (rolling windows + Recent form panel) ✅ CLOSED 2026-05-14** (`335d5c2`); **Phase 4b D40 invariants watchdog ✅ CLOSED 2026-05-14** (`251a0dd`); **Phase 4b career-event scope fix ✅ CLOSED 2026-05-14** (`8137ab3` — 99.8% → 100% green); **Phase 4b Tier B (per-dump history + trajectory API) ✅ CLOSED 2026-05-14** (`e6146e3`). **Phase 4b remaining**: Tier C per-dump leaderboard snapshots, UI rollout (real Tier B sparklines on spotlight cards, `/settings/invariants` admin page), Tier B v2 (rate-stat history). **See DECISIONS.md D40 + D41 + D42 + D43 + DATA_QUIRKS.md for the full picture.**

**Most recent ship — 2026-05-14 shipped Phase 4b Tier B per-dump history snapshots + trajectory API.** New `src/diamond/schema/l2_history.py` (~250 LOC) materializes three counting-stat history tables sourced from L0 directly (L1 events collapse to MAX(dump_date); L0 retains all dumps): `f_player_season_batting_history` PK `(player_id, year, league_id, level_id, split_id, dump_date)` 15M rows on Padres; `_pitching_history` 8M rows; `f_player_career_history` PK `(player_id, dump_date)` 3M rows. Cross-stint dedup at the `(player, year, team, league, level, split, stint, dump_date)` grain before GROUP BY collapses to per-season rollup. Same team-scope filter as the D40 fix (catches retired-player historical stints). Wired into `rebuild_l1_l2` between L2_game_grain and L3; +100s rebuild penalty. New `GET /api/players/{id}/trajectory` endpoint returns `career_bat` + `career_pit` per-dump trajectory points + latest-season slices, with rate stats (AVG/OBP/SLG/OPS/ERA/WHIP/K-9) computed server-side from counting stats. Pre-Tier-B-defensive: empty arrays on warehouses predating the build. **Verified on Padres**: Merrill 2028 monthly AVG trajectory .231 → .290 → .284 → .282 → .288 (29 career-batting dumps surface, 5 in-season for latest 2028). Mason Miller career closer line: 250G/115SV/ERA=2.69 → 289G/138SV/ERA=2.55 across 29 dumps — real sparkline data ready. Tier B v2 (advanced rate-stat history with per-dump league constants) deferred to Phase 5 if needed. **Unblocked**: trajectory queries, real sparklines, engine-patch detection, reconciliation history. UI rollout (spotlight cards switching to real per-dump trajectories) is a follow-up.

**2026-05-14 (earlier) shipped Phase 4b D40 invariants watchdog + scope fix.** Watchdog comparing OOTP-cached aggregates vs Diamond-derived (commit `251a0dd`) flagged 7 real team_pa_count reds in initial Padres run (99.8% green). Investigation found `_scoped_players` is snapshot-based — retired/released players whose 2026+ stints on scoped teams got dropped. Fix `8137ab3` switched career-stint events from `_SCOPE_PLAYER` to `_SCOPE_TEAM` filter. Watchdog 99.8% → **100% green** (4,553/4,554; the remaining 1 red is OOTP's own L0-vs-team_history -2 PA quirk on Boston 2026 MLB — not a Diamond bug).

**2026-05-14 (earlier) shipped Phase 4b D40 invariants watchdog.** New `src/diamond/schema/invariants.py` (~330 LOC) compares OOTP-cached aggregates from L2_OOTP (`f_team_season_batting_ootp.avg/obp/slg`, `f_team_season_pitching_ootp.era/whip/k9/bb9`, `pa`, `hr`) against Diamond-derived aggregates (SUM/COUNT from `f_player_season_batting`/`_pitching` grouped by team). Stores result in new `_diamond_invariants` table (dump_date, scope_type, scope_id, year, level_id, metric, dump_value, derived_value, delta, tolerance, status). Status: green (|delta| ≤ tolerance), amber (tolerance < |delta| ≤ 2·tolerance), red (clear bug). 9 initial invariants (`team_woba` dropped — OOTP doesn't cache team-level wOBA, all rows are 0). Auto-runs at end of every `rebuild_l1_l2` after L3+L_IE. New `GET /api/admin/invariants` endpoint returns overall + per-metric rollup + top-20 failures sorted by |delta|. Cockpit page header gets a "Drift NN.N%" pill colored green/amber/red, with red-count badge when red > 0. Tolerance convention: 0.001 for rate stats (3-decimal display), 0.02-0.05 for ERA/WHIP/K9/BB9, 0.5 for integer event counts (allows 1-row rounding from cross-dump dedup). **Padres outcome**: 4,545 / 4,554 green (99.8%); 7 real `team_pa_count` failures surface a cross-stint aggregation bug somewhere in L1/L2 (team 274 2026 L4 is off by 79 PA — to-investigate). Smoke + TS typecheck pass.

**2026-05-14 (earlier) shipped Phase 4b Tier A + Tier D.** **Tier A** (commit `d7a9b7c`) — new `src/diamond/schema/l2_game_grain.py` (~210 LOC) materializes two game-grain fact tables: `f_player_game_batting` PK `(player_id, year, game_id)` 1.1M rows on Padres (430K Sox smoke), 18 stat cols sourced from `l0_players_game_batting` (split_id=0); `f_player_game_pitching` 355K rows / 134K smoke, 25 cols from `l0_players_game_pitching_stats` (split_id=1). Cross-dump dedup via `ROW_NUMBER PARTITION BY natural_key ORDER BY dump_date DESC` (same pattern as `f_pa_event` D17). JOIN to deduped `l0_games` CTE for canonical date. `ORDER BY (player_id, date)` in CTAS physically sorts the table — sequential scans for player-game-log queries hit contiguous storage. Wired into `rebuild_l1_l2` between L2_OOTP and L3 (+1.1s rebuild penalty). Phase E.5 smoke check added. Game-grain fielding deferred (no source in L0). **Tier D** (commit `335d5c2`) — consumes Tier A for rolling-window aggregates. New `GET /api/players/{id}/recent?windows=7,15,30` returns batting + pitching lines over each calendar-day window, anchored to the player's most recent regular-season game (NOT today — works for retired/mid-season). Multi-window in one round-trip (~6 rows payload). Frontend `RecentFormPanel.tsx` renders both tables stacked above the Stats-tab year-by-year tables. **GM-decision signal verified**: Merrill last 7d 9-for-28 SLG=.714 OPS=1.101 (hot stretch); Mason Miller last 30d 4 IP / 20 K / 1 BB / ERA=0.00 (elite closer); Brad Keller last 30d 5.1 IP / ERA=15.19 (DFA candidate). The windows surface trajectory that cumulative season totals hide — exactly what Tier D was built for. TS typecheck + smoke pass.

**2026-05-14 (earlier) shipped Phase 4b per-player x-stat calibration + batting xBA + pitching xwOBA re-enable.** OLS fit on Padres single-stint org corpus (n=43, L1-L4, BIP≥30) found `r(xba_gap, POW) = 0.65` — high-power hitters had positive xBA/xSLG gap (flat 1.22 / 1.09 scalers were over-correcting them). Replaced flat scalers with per-player POW-rating-aware linear corrections in `_build_f_player_season_xstats_batting`: `xba_correction = 0.00823 + 0.00054·(POW-50)`; `xslg_correction = 0.01527 + 0.00115·(POW-50)`. Year-aware POW lookup via `players_ratings_snapshot` (29 monthly snapshots → latest within season's year; pre-2026 falls back to POW=50). **Reconcile outcome**: batting xBA **89% → 95%** (clears D41 bar), xSLG 89% → 93% (close, stays out), xwOBA 78% → 92% (cascade from improved LA buckets); pitching xwOBA **82% → 96%** (cascade win — clears bar). **Re-enables on player page**: batting `xba` column (Merrill 2028 xBA=0.274 — bit-for-bit IE match via L_IE routing); pitching `xwoba` column (Keller 2028 xwOBA=0.296). Batting xSLG/xwOBA + pitching xERA stay deferred. **Caveat**: calibration constants are Padres-specific (fit on one save); Sox / other saves may benefit from per-save refit at ingest time — out of scope for this slice but documented as Phase 4b follow-up.

**2026-05-14 (later) shipped pitching xstats re-enable (xBA + xSLG).** Restored on the player page pitching Advanced view + leaderboards catalog (`xBA_pit` / `xSLG_pit` ids; default 30-BIP qualifier; ascending order — lower is better for pitchers). Match rates per Padres reconcile sweep: **xBA 96%, xSLG 97%** (both over D41's 95% bar). Sourced from `f_player_season_xstats_pitching` (scaled SUM/AB values via 1.22 / 1.09 empirical scalers from Phase 4a-ext-1). Per the new L_IE routing layer: bit-for-bit OOTP IE values for single-stint org-roster pitchers in the latest year; L3 derivation at 96-97% match elsewhere. New `xba` + `xslg` fields added to `PlayerAdvancedPitchingRow` schema; `_fetch_advanced_pitching` JOINs `f_player_season_xstats_pitching` (gated by table-existence check) + COALESCEs L_IE values where eligible. New `_XPIT` constant + 2 catalog entries in `routes/leaderboards.py`. Frontend `ADV_PITCHING_COLUMNS` adds xBA + xSLG between ERA+ and pit_WAR; `SLASH_FIELDS` set extended for 3-decimal OOTP-canonical display (".251" not "0.251"). `make types` regenerated. Smoke passes. **Verified**: William Kempner / Randy Vasquez / Brad Keller / Braylon Doughty all show IE-routed bit-for-bit. xwOBA (82% match) + xERA (87%) stay deferred until per-player calibration brings them over the bar.

**2026-05-14 shipped L_IE display routing Slice 1.** Per D41, the display ditch dropped every column with <95% IE match. L_IE routing closes the remaining 1-5pp rounding/algorithmic noise on the columns that DO display, via direct read of OOTP's `<save>/import_export/*.csv` roster exports. New `src/diamond/schema/l_ie.py` (~700 LOC) ingests 21 `lie_*` tables (org-agnostic suffix discovery; matches both Sox + Padres prefix conventions; DROP-and-rebuild on every refresh — point-in-time snapshot semantics, unlike L_REF which is frozen). Per-discipline unified views `v_lie_player_{batting,pitching,fielding}_display` parse OOTP display strings (`.250`, `9.1%`, `$28 800 000`, `1 (auto.)`, `-`) to typed numerics ready to COALESCE in API CTEs. Stamps `_diamond_settings.l_ie.*` provenance (timestamp, source dir, per-file rows, missing list). Wired into `rebuild_l1_l2` after L3. **API routing live for**: `_fetch_advanced_batting` + `_fetch_advanced_pitching` in `routes/players.py`. CTE pattern derives a `latest_year` + `ie_eligible` (single-stint players only — multi-stint years keep per-stint derivations to avoid mismatching IE's per-player aggregate against our per-(year, level) grain). View-existence gated by new `_view_exists` helper so warehouses predating L_IE fall through to derivations without erroring. **Verified on Padres save**: Jackson Merrill 2028 derived wOBA=0.350 OPS+=124 bWAR=3.6 → L_IE-routed wOBA=0.343 OPS+=125 bWAR=3.6 (bit-for-bit OOTP IE match). Pre-routing gap distribution on 98 single-stint MLB batters: OPS+ median 2pts max 25; FIP median 0.02 max 0.82; ERA+ median 3pts max 186 — all eliminated by routing. Coverage 98 batters + 114 pitchers (the current-year org roster). Smoke passes. **Remaining slices (deferred — diminishing returns)**: basic batting/pitching stints (already 99%+ exact), fielding (view ready, not wired), roster + leaderboards + cockpit (same pattern), per-position spray %s / BAR / Statcast cells re-enable (column resurrection). See `docs/DATA_QUIRKS.md` L_IE entry + `docs/BACKLOG.md` Phase 4b deferred-work section for full receipts.

**2026-05-10 (final) shipped the display ditch (D41).** Per the policy "any column where Diamond's value can differ from OOTP IE by more than rounding (≥ ~5pp) is hidden from the UI." Two commits in sequence: (1) **Spray ditch + chart clipping fix** (`cd422af`) — fixed the StadiumSprayChart hit_xy clipping bug (`[0,130]` → `[0,255]`, was mis-rendering ~30% of events on the oppo foul line); dropped Pull%/Cent%/Oppo% cells from the player page situational table (`hit_xy` doesn't carry per-batter spray info — `r=0.17` against IE Pull%, MAE 7pp ceiling). (2) **Full ditch** (`169ad0c`) — removed xstats triplet (`xwoba_bip`/`xba_bip`/`xslg_bip`) from `PlayerAdvancedBattingRow`/`PitchingRow` schemas, dropped roster Contact mode from 6 → 2 cols (kept Max EV @ 97% + HH% @ 94-95%, dropped BIP/Avg EV/Brl%/SS%), dropped AVG_EV/BARREL_PCT/SWEET_SPOT_PCT/xBA/xSLG/xwOBA from the leaderboards catalog (Chart Builder auto-inherits). L3 tables stay materialized as drift-watch + invariants-watchdog inputs. Reconcile ColSpec notes tagged `SEALED Phase 4a-ext-3` so future sessions don't re-litigate. **Net effect**: every number in the user-facing app is now bit-for-bit OOTP-matching within rounding. See `DATA_QUIRKS.md` for the full ledger of what's dropped + why.

**2026-05-10 (earlier) shipped Phase 4a-extended-3 — OOTP barrel cone reverse-engineered.** User pushed back on the earlier "structural" labeling for barrel rate: "we literally solved barrel rate though?" Git-history audit showed we never had it at 100%, only iterative empirical re-fits — but `lref_xiso_table` was ingested in 2026-05-14 L_REF Slice 1 with DATA_NOTES claiming it would "replace our barrel/SS/HH classification," then the actual reverse-engineering was never done. Phase 4a-ext-3 did it. Inspection: xiso is a (LSA × outcome) histogram, **not** a (LA, EV) → LSA lookup. The classifier must be derived from per-player IE BAR ground truth. Grid-searched cone shapes against 74-batter Padres corpus: best fit **`EV ≥ 97 AND LA in [26-(EV-97), 30+(EV-97)]`, capped at LA [8, 50]** — centered at LA=28, half-width 2 at EV=97, expanding 1°/mph. Almost identical to Baseball Savant canonical (which uses EV ≥ 98) — OOTP only differs by 1 mph lower floor. Result: BAR 40% → **67% (+27pp)**, BAR% 74% → **94% (+20pp)**. Applied to both `audit/reconcile.py:BATTING_SUPERSTATS_CTE` and `schema/l3_advanced.py:_STATCAST_BARREL_EXPR` (L3 production). Soft/Med/Solid stay on EV cutoffs — tested LSA bands {1+2}/{3+4}/{5+6} at MAE 12.4/5.3/8.8 vs current EV-cutoff (76, 95) at MAE 1.7/2.1/1.2; LSA-band hypothesis rejected. Commit `903810f`.

**2026-05-10 (earlier) shipped Phase 4a-extended-2 — stress-test "structural" claims.** User pushed back on "things at 60-80% match labeled structural too quickly." Rigorous stress-tests on every claim: **(1) Spray Pull/Cent/Oppo confirmed TRULY structural** via Pearson correlation analysis — `r(avg_xy, IE Pull%) = 0.17`, essentially zero. Top-10 IE pull hitters had avg_xy=128, bottom-10=126 (identical). hit_xy genuinely doesn't carry per-batter spray info; OOTP IE uses internal sim features (bat hand × pitch type × swing angle) we can't reach. Tested every encoding × cutoff combo — all bottom out at MAE ~7pp. **(2) IFH% multi-dim** — was deferred to Phase 4b but actually achievable now. Grid-searched (hit_loc, EV, LA): best `hit_loc ≤ 30 AND EV < 95 AND LA < 5` at MAE 3.09pp. IFH% recon 57% → **71% (+14pp)**. **(3) BIP PCB widening REGRESSED** — tried widening level filter L1-L6 → no-filter, hoping to capture L7-L8 DSL/foreign stints. Result: 82% → 81% (worse). IE's org-roster aggregate excludes foreign-league stints. Reverted. **(4) BUH% confirmed sparse-noise** — most batters have 0-3 bunts; denom <5 swings % by 20+pp. No formula change. Commit `018f594`.

**2026-05-10 (earlier) shipped Phase 4a-extended-1 — recon drive on never-re-examined gaps.** Post-Phase-4a-close, an honest audit surfaced 72 recon columns still under 100%. Five formula corrections in `reconcile.py` + `l3_advanced.py`: **(1) BIP filter `sac=0` removed** — IE counts sac flies AND sac bunts as BIP (probe: 59/78 exact vs 7/78 prior, cascade across 9+ downstream rate cols). **(2) BAR recalibration** EV≥99 LA[13..41] (27/74 exact vs prior 13/74; later superseded by ext-3 cone). **(3) xwOBA scaler 1.03** in L3 builders (63/73 exact vs no-scaler 52/73). **(4) xERA formula refit** to `19.5*xwOBA - 2.5` post-scaler change (67/71 exact vs broken 30/71). **(5) LA bucket re-fit** to GB<11/LD 11-25/FB 26-50/PU≥51 (MAE 1.54 vs prior 2.54 — cascades into +20-45pp on GB/FB/HR-FB/IFFB across batting AND pitching). Net jumps: batting GB/FB 47→92, GB% 68→92, FB% 65→91, HR/FB 83→95, LA 53→94, HHi 68→94, xwOBA 78→92; pitching GB/FB 61→92, GB% 76→95, FB% 73→95, xwOBA 82→96, xERA 87→97 (briefly regressed to 44 before refit, then jumped). Commit `bf31cef`.

**2026-05-10 (earlier) shipped Phase 4a #3-6 — audit-closure deliverables.** Four findings closed the carry-forward queue. **#3 (MiLB 5-8 backfill)** — two-bug fix in `_lg_constants_advanced_imported`: (a) level fan-out (`MIN(level_id)` → `milb_levels_per_league` PLURAL, one row per (league_id, level_id) seen) closes OOTP's 2021-reorg-induced gap where leagues 209-213 + 252 had been reclassified between L4 (modern) and L6 (historical); (b) extended `milb_xwalk` with American Association + Pioneer League. Result: L6 NULL 100% → 85%, L7 100% → 84%. Remaining nulls = foreign/complex/independent leagues with no `lref_era_stats_minors` data — documented as permanent. **#4 (EV-bucket calibration)** — grid-search across Padres corpus (74 batters × 12,506 BIP + 73 pitchers × 12,780) chose **(76, 95)** cutoffs at MAE 1.68pp/1.81pp vs prior (75, 95) at 1.92/2.06. The 95-mph solid threshold matches MLB-Statcast hard-hit convention exactly. Recon: batting Soft% 58→68 (+10), Avg% 58→60, pitching Soft% 53→74 (+21), Med% 64→73 (+9). **#5 (hit_loc decoding)** — grid-search across three FanGraphs IFH% formula variants picked **F2 (IFH/all-GB) at cutoff=22** (MAE 3.54pp). Decoding: `hit_loc ≤ 22 = infield`, `≥ 23 = outfield` — natural 12× jump at the 22/23 break. IFH% NULL → **60% recon match**. **#6 (multi-level OPS+/ERA+)** — hypothesis was wrong. Padres sweep (28 multi-stint players) showed median PA-weighted gap = 2 OPS+; outlier gaps come from foreign/winter-league stints (L11 Caribbean Winter, KBO) IE excludes — not a formula bug. Per D11, rate stats are never rolled up across levels; per-level rows are individually correct. **No formula change.** DATA_NOTES.md, DECISIONS.md D40, PROJECT_STATUS.md, BACKLOG.md all updated to mark Phase 4a closed.

**2026-05-10 (earlier) shipped Phase 4a deliverable #2 — authoritative cache wiring.** New `src/diamond/schema/l2_ootp.py` (~430 LOC) adds **9 L2 fact tables + 1 view** that pass OOTP-cached aggregates through to the analytical layer as named columns. **Team-season facts** (`f_team_season_{batting,pitching,fielding}_ootp`) carry every OOTP cached rate stat per (team_id, year) including the previously-orphan `sa/da/ta/ra`, `r9/h9`, `cgp/qsp/winp/svp/bsvp/gfp/pig/ws/gbfbp/kbb/sbp/rtop/cera`. **Player-stint facts** (`f_player_stint_{batting,pitching,fielding}_ootp`) preserve the L1 synthetic PK and surface the orphan `ubr` (ultimate baserunning), allowed-hit counts per-pitcher, plus the full zone-rating opportunity grid `opps_0..5`/`opps_made_0..5`/`roe`/`plays_base`. **League-season facts** (`f_league_season_{pitching,fielding}_ootp`) surface `kp`/`bbp`/`kbbp`/`irsp`/`eff` and per-bucket opps counts. **`f_player_value_current`** (12,720 rows — one per scoped player at latest dump) exposes all 39 orphan cols in `l0_players_value`: per-side valuations (`offensive_value_vsl/vsr`, `pitching_value_vsl/vsr`, `leadoff_value_vsl/vsr`), master rolls (`overall_value`/`talent_value`/`career_value`), 3-segment trajectory (`stats_value_0..2`/`stats_mod_0..2`), per-position rolls (`overall_sp/rp/c/1b/2b/3b/ss/lf/cf/rf`), award triggers, `oa/oa_rating/pot/pot_rating`. **`v_player_ratings_by_side`** enumerates 95 batting + pitching + fielding rating columns per side / talent / overall / misc — surfaced from `players_ratings_current`. Each builder calls `_assert_columns_present` against an explicit `_*_ORPHAN_COLS` tuple — an OOTP version-bump that drops/renames a column fails the warehouse build loudly. Wired into `rebuild_l1_l2` between L2 and L3. **Outcome**: 1,418 → **1,681 cols referenced (57% → 68%)**; **263 orphans closed**; 10 target tables + 5 shared-column siblings now at 100% coverage. `make smoke` passes; rebuild succeeds in ~30s. Feeds the **D40 invariants watchdog** in Phase 4b — every wired column is a candidate invariant input.

**2026-05-10 (earlier) shipped Phase 4a deliverable #1 — L0 inventory pass.** `scripts/inventory_l0_coverage.py` (save-agnostic, runs via `--save NAME`) + `audit_output/l0_column_coverage.md`. Enumerates every column in every L0 table, word-boundary-greps references across `src/diamond/**` + `web/{app,components,lib}/**` + `scripts/**`. Initial findings on The Fathers warehouse: 69 L0 tables, 2,466 non-admin columns, 1,418 referenced (57%), 1,048 orphan (42%), 18 fully-consumed tables. Surfaced that three D40 Phase 4a #2 candidates were already wired (`l0_players_league_leader`/`_individual_batting_stats`/`_salary_history`); refined the wire-list to drive deliverable #2.

**2026-05-17 (evening) shipped D39 — Statcast reconciliation deep-dive.** Four sub-fixes closed Padres recon from 85% → 95%: D39a (spray) `hit_xy` is batter-relative (HR analysis across 1,889 MLB 2028 HRs); D39b game_type=0 filter on all L3 Statcast builders; D39c LA bucket recalibration (GB<12/LD<27/FB<52/PU≥52); D39d x-stats triple fix (integer-EV interpolation zero-bug, IE-style SUM/AB denominators, empirical scalers ×1.22 xBA / ×1.09 xSLG). xwOBA 0%→78%, xBA 0%→89-96%, xSLG 0%→89-97%, xERA 0%→87% (new). Plus save-aware report header. Commit `88664c6`.

**2026-05-17 (afternoon) shipped D38 — Padres reconciliation pass + wOBA formula correction.** After D37 stabilized the Padres save, user provided OOTP control data (`docs/helpful_files/recon/Padres/`: 21 stat CSVs + 65 screenshots @ 7/31/2028) and asked to reconcile sim stats to OOTP IE before layering in baseball history. Three D38 changes: (1) **Multi-save reconciler infra** — `_resolve_ie_path` org-agnostic suffix match (so Padres `san_diego_padres_organization_-_*.csv` files resolve via the same FileSpecs originally written for Sox), `--ie-dir` + `--save` CLI flags so the harness can target any folder, scouting-stamp fix (D12 L1 view is already audit-team-filtered, but FileSpec CTEs hardcode `WHERE scouting_team_id = 4` for Sox-era reasons — re-stamp constant 4 regardless of save so the WHERE passes). (2) **wOBA formula correction (OOTP-canonical)** — investigation revealed OOTP uses BASE linear weights × PA denominator, NOT the FanGraphs (AB+uBB+SF+HBP) form with lg-OBP-scaled weights. Bastidas 2028 IE=.357 vs old Diamond .372 (.015 systematic high drift on minor-leaguers with SH>0). Fix: `l3_advanced.py:woba_calc` uses base weights × PA; `_LG_CONSTANTS_NATIVE_VIEW_SQL` + `_LG_CONSTANTS_IMPORTED_VIEW_SQL` woba_denom→lg_pa and lg_woba→base_lg_woba (no longer = lg_obp by construction); `reconcile.py:BATTING_DERIVED_CTE` switched to PA denom to match. Verified: Bastidas .356, Ocopio .287/.288, Merrill .350. (3) **Accuracy floor**: 197 A-tier columns 100%, 43 B-tier 94-100% (rounding-grade). Statcast aggregation (33 cols), xBA/xSLG/xwOBA (7 cols), pitch-tracking (36 cols F-tier) flagged for future investigation. Output at `audit_output/reconciliation_padres_2028_07.md`. wOBA tier match: **76% → 94%**.

**2026-05-17 shipped D37 — in-progress season league constants + multi-save endpoint resilience.** Day after D36 shipped, user opened the Padres save mid-2028 (`dump_2028_07`, mid-July) and reported the cockpit was showing a giant red "0" headline metric on every spotlight player + "No qualifiers yet" on the MLB Pressure board + History → Hall of Fame returned 500. Three fixes: (1) **In-progress season league constants** — OOTP only writes `league_history_*_stats.csv` rows for completed seasons, so mid-season dumps had zero (year, league, level) rollup rows for the active year (only DSL leagues had 2028 entries by July). New `agg_bat_fallback` + `agg_pit_fallback` CTEs in `_lg_constants_advanced_native` aggregate from `f_player_season_*` (already dump-deduplicated to latest dump) for combos NOT in `league_history_*`, gated to years that already have SOME league_history coverage so pre-save Lahman-imported rows stay routed to `_lg_constants_advanced_imported`. Post-fix: 25 rows for 2028 in `_lg_constants_advanced` (was 2); Merrill 2028 OPS+ 124, Mason Miller ERA+ 252. (2) **Cockpit nullable metrics** — `headline_metric_value: int | None`; cockpit endpoint passes None instead of coercing to 0; frontend renders "—" with `text-content-muted`; insight is suppressed when current metric is None (was misleadingly producing "Off year — 0 down from 135 peak"). (3) **`/api/hof` 500 on Padres save** — endpoint LEFT JOIN-ed `history_lahman_people` for `bbref_id` resolution, but Padres save was created without running `diamond fetch-history` so the warehouse has zero `history_*` tables. New `_history_loaded(con)` probe + template-based query construction substitutes `NULL::VARCHAR AS bbref_id` and drops the JOIN entirely when the table's absent. (★ Bonus) `/api/admin/dump-status` reported 0 ingested even though warehouse had 29 — endpoint opened its own `duckdb.connect(read_only=True)` which fails on Windows with IOException because uvicorn's RW connection holds an exclusive lock; switched to `Depends(get_cursor)`. **All 14 main API endpoints return 200 on the Padres warehouse post-fix.** **The Padres save's 2005-2028 history range is a save-creation property** (OOTP "import last 20 years" instead of "full Lahman history"), not a Diamond bug — pre-2026 Padres rows still resolve advanced stats via the lref_era_stats-backed imported view.

**2026-05-16 (end-of-day) shipped D36 — multi-save productionization (Padres save smoke test).** User pointed Diamond at their Padres save (`The Fathers.lg`, San Diego Padres, audit_team_id=23, 29 dumps 2026_03 → 2028_07) which surfaced five distinct issues: (1) **AI prompt save-awareness** — opening sentence + org-structure block was hardcoded to Boston Red Sox / Building the Green Monster / Worcester / Portland / Greenville / Salem; new `_resolve_org_context(cursor, save)` substitutes team city/name/org_id from `MLB_TEAMS_BY_ID` + warehouse-probes latest/earliest seasons. Both sync `/api/ai/chat` and streaming `/api/ai/chat/stream` handlers wire it in. (2) **Desktop chrome save-awareness** — `WINDOW_TITLE` was hardcoded in both `launcher.py` and `single_instance.py` (the latter uses it for `FindWindowW` so single-instance focus was Sox-only); splash HTML had a hardcoded Sox title. New `diamond.saves.get_active_window_title()` is the single source of truth (reads `~/.diamond/active_save.toml` directly so the desktop launcher boots before FastAPI). Splash gets a placeholder substituted at load time. (3) **VARCHAR-defensive scope filters** — The Fathers' L0 inferred VARCHAR for several ID + date columns where Sox had BIGINT/DATE (`l0_trade_history.{team_id_0, team_id_1, player_id_0_*, player_id_1_*, message_id, date}` + `l0_league_playoff_fixtures.{league_id, team_id0, team_id1}`). Naive `team_id IN (BIGINT_LIST)` and `trade_date BETWEEN TIMESTAMP ...` died with Binder Errors. `_SCOPE_PLAYER` / `_SCOPE_TEAM` / `_SCOPE_LEAGUE_HARDCODED_15` / `_SCOPE_TRADE` now wrap LHS in `TRY_CAST(... AS BIGINT)`; `f_trade_participant` builder TRY_CASTs every team_id + player_id (in UNNEST) + message_id + date (→ DATE). NULL-on-failure semantics safely excludes any non-numeric ID rows. (4) **JS local-TZ date parsing** — `fmtDate("2028-07-01")` did `new Date("2028-07-01")` which parses as UTC midnight, then `toLocaleDateString` shifts back a day in any TZ west of UTC ("Jun 30" instead of "Jul 1"). Three pages had the same bug (cockpit / league / history streaks); all defensively detect date-only ISO strings and construct via `new Date(y, m-1, d)` instead. (5) **dump_date end-of-month convention** — User pointed out `dump_YYYY_MM` is exported when OOTP advances *into* month MM+1, so its data is "stats through last day of MM", not first day. `dump_name_to_date()` was returning 1st-of-month; now returns last-day via `calendar.monthrange` (handles leap years). New `migrate_dump_dates_to_eom()` runs DuckDB's `LAST_DAY()` over every `dump_date` column on every BASE TABLE (filters out views — DuckDB can't UPDATE views), idempotent via `_diamond_settings.dump_date_convention='end_of_month'` marker, with `WHERE dump_date <> LAST_DAY(dump_date)` optimization. New `diamond migrate-dump-dates [--save NAME]` CLI command runs it explicitly. **NOT auto-run on warehouse open** — a 10+ minute API stall on first connect would be unacceptable for the legacy Sox save (45+ dumps × 80+ snapshot tables × millions of rows). The Fathers warehouse migrated in ~30s; Sox migration deferred to opt-in CLI. **Verified post-fix on The Fathers**: 208 tables, 27 lref_*, 22 facts, 37 events; Padres MLB roster 51 / org 245; 2027 top OPS+ Jackson Merrill 124 (3.9 bWAR), Ozuna 120, Salvy 112; 2027 top pWAR Vasquez 2.7, Chapman 1.6 (163 ERA+). Active save flipped to `The Fathers.lg`. Three commits on top of D35: `95c13ce` (Sox-identity removal + VARCHAR), `101573e` (fmtDate), `5b66839` (dump_date EOM + migration CLI). **2026-05-16 (later) shipped D35 — AI sidebar Claude.ai-style polish: markdown rendering + SSE streaming.** Four-tier rebuild closing the visual gap between D33's functionally-complete sidebar and a Claude.ai-grade chat surface. **Tier A — markdown rendering**: new `web/components/ai/MarkdownMessage.tsx` (~140 LOC) renders assistant text via `react-markdown` + `remark-gfm` + `rehype-katex` + `remark-math`; custom `Components` map applies theme-aware Tailwind to h2/h3/tables/lists/inline code/block code/blockquotes/links — no `@tailwindcss/typography` dep. Per-text-block card chrome dropped — assistant prose flat against panel bg. **Tier B — visual polish**: consecutive assistant turns coalesce into one rendered "response group" (a tool-using loop produces 3-4 turns; user perceives one answer, gets one Diamond label). User vs assistant asymmetry — user messages right-aligned `bg-surface-card` pills (max 85% width, rounded-2xl with sharp top-right corner); assistant flat full-width with ✦ glyph + accent-colored "Diamond" label. Hover-revealed copy button at the bottom of each completed response. Panel default width 440 → 520. **Tier C — SSE streaming**: new `POST /api/ai/chat/stream` endpoint returns `text/event-stream` driving the same tool loop as the sync endpoint (6-iteration cap), but yielding provider-agnostic SSE frames per event (`text_delta` / `tool_use` / `tool_result` / `iteration` / `error` / `done`). Both adapters implement native streaming: Anthropic via `httpx.stream()` consuming `content_block_start` / `_delta` / `_stop` per the Messages streaming spec (input_json_delta accumulating partial JSON for tool_use blocks); OpenAI via `delta.content` + `delta.tool_calls[]` with per-`index` arguments accumulating piece by piece. `AIClient.chat_stream` has a default fallback that re-emits `chat()` results. Frontend `streamChat()` parses SSE incrementally with `fetch().body.getReader()` + `TextDecoder` + abort support; `StreamingState` machine in `AISidebar.tsx` mutates an in-flight turn array per event then drains into committed thread on `done`. Send button swaps to a Stop button while streaming; blinking ▍ cursor at the end of streaming text. **Tier D — chrome polish**: mode pills moved into the header; drag-to-resize via 2px handle on left edge (380-900px range, persisted to localStorage); jump-to-latest button when scrolled away mid-stream. **Files**: 5 modified + 1 new component. **Compat**: existing `POST /api/ai/chat` (sync) endpoint stays for tests/fallback; both share system prompt + tool loop. **Bundle delta**: ~80KB gzipped from the four markdown libs. **2026-05-16 (earlier) shipped the D34 cleanup pass + six D33 follow-ups + everything below from yesterday.** D34 cleanup: deleted `api.bat` / `web.bat` / `kill-stale.bat` (launcher count 5→2, kill loop inlined into `dev.bat`, PYTHONIOENCODING exported in Makefile, `dev.bat` calls `make api`/`make web` directly); removed redundant header Quit button + `/api/admin/shutdown` endpoint + 100-line `_KILL_SCRIPT` (window X + tray Quit cover it); fixed tray "Show Diamond" to focus the existing Qt window via signal instead of opening browser. Net: 4 files deleted at root + ~325 LOC removed. **D33 follow-ups (also today)**: (a) Anthropic snapshot auto-migration — `RETIRED_MODELS` map rewrites `claude-3-5-haiku-20241022` → `claude-haiku-4-5` rolling alias; (b) dropped Postgres-style `SET statement_timeout` from `query_warehouse` (DuckDB 1.5.x doesn't have it; was failing every tool call); (c) LIMIT-injection now skipped on non-SELECT queries + new `describe_table` tool with strict alphanumeric validation (model has clean schema-discovery path; tool count 6→7); (d) **persona setting** — free-form `persona: str` field in AISettings + 5 presets in `/settings/ai` (Default / Terse analyst / Hardboiled scout / Stats nerd / GM coach); appended to chat system prompt verbatim; **tool plumbing hidden by default** in sidebar with "Tools" toggle in header (persisted to localStorage); Metabase cards + tool errors stay visible regardless; (e) **page-payload wiring** — `<PagePayloadProvider>` Context + `<PagePayloadBridge data={...}>` server-component-friendly bridge with 16KB cap + truncation hint; cockpit (`/`) publishes `{save, cockpit}` and player page (`/player/[id]`) publishes the full PlayerResponse; AISidebar reads via `usePagePayload()` and includes in `page_context.payload`; (f) **`get_career_arc` tool + cite-your-sources prompt** — fixes Crochet-vs-Ryan hallucination class (model claimed Ryan career pWAR 1,650.6 vs actual 117.9; got year-to-age mapping wrong: claimed 1969=age 30 when Ryan was 22 in 1969). New deterministic tool returns season-by-season + age (`year - dob.year`, minus 1 if birthday > July 1, OOTP convention) + warehouse-aggregated career WAR; system prompt strengthened: "cite tool sources for every specific number; do NOT cite from training-data memory". Tool count 7→8. **2026-05-16 (earlier) shipped the AI sidebar (D33)** — replaces D14's single-button "Summarize career" with a full four-tier AI surface reachable from every page. Floating launcher (`✦ Ask Diamond`, bottom-right) opens a 440px slide-out panel with chat thread + mode pills + textarea. **Tier 1** (page-aware): sidebar reads `usePathname()` and system prompt includes "user is on /player/123" so generic questions land in context. **Tier 2** (tool-using analyst): six tools wired into warehouse + dictionary — `query_warehouse(sql)` (read-only DuckDB cursor with regex-blocked mutations, single-statement guard, LIMIT 1000 default, 5s timeout), `get_player(id)`, `compare_players(ids)`, `get_glossary(stat_id)`, `list_leaderboard_stats()`, `create_metabase_card(name, sql, viz_type)`. Tools return `{"ok": False, "error": ...}` rather than raising. **Tier 3** (GM copilot): four modes (chat / callup / trade / draft) — non-default modes prepend a structured prompt template; mode pills in the sidebar footer + page-aware empty-state suggestions both wire in. **Tier 4** (prompt-to-dashboard): `create_metabase_card` POSTs MBQL spec via the D31 Metabase coordinator (`diamond.api.metabase._get_session()`); returns `card_url` rendered as inline ✓ green launcher link the user can click to open in browser. **Tool loop** in `routes/ai.py:chat()` translates frontend `ChatTurn` ↔ provider-native messages, drives the loop until `stop_reason != "tool_use"`, capped at 6 iterations to prevent runaway. **Provider-agnostic**: `AIClient.chat()` is a new abstract method; Anthropic adapter passes through (already matches our internal Anthropic-shaped content blocks); OpenAI adapter translates messages + `tool_calls` in both directions. **Frontend rendering**: assistant text in standard bubbles; `tool_use` blocks as collapsible `<details>` with input args + "Tier 4" badge for `create_metabase_card`; `tool_result` blocks special-case warehouse query results (preview table, first 25 rows, SQL inline) and Metabase card creations (green ✓ link). Errors render in rose styling. **Empty-state suggestions are page-aware**: `/player/[id]` → "Summarize this player's career"; `/league` → "Who should I call up from AAA?" (mode=callup); `/movements` → trade analysis. **Safety**: read-only SQL only, single-statement guard, regex-blocked DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/ATTACH/DETACH/COPY/EXPORT/LOAD/INSTALL/PRAGMA/VACUUM, default LIMIT 1000, 5s timeout, 6-iteration cap. **Same-day Metabase link fix**: QtWebEngine doesn't handle `target="_blank"` natively (Workshop tab's "New question / Sample dashboard / Browse warehouse" cards opened nothing inside the desktop shell). Subclassed `QWebEnginePage` to override `createWindow`; new-window navigation now routes to system default browser via `QDesktopServices.openUrl`. **Files**: `src/diamond/ai/tools.py` (new, 6 tools + ToolContext), `src/diamond/ai/client.py` (added `chat()` abstract), `src/diamond/ai/adapters/{anthropic,openai}.py` (added `chat()` impls), `src/diamond/api/schemas/chat.py` (new schemas), `src/diamond/api/routes/ai.py` (new `/api/ai/chat` endpoint + tool loop + system prompt builder + 4 mode templates), `src/diamond/desktop/launcher.py` (ExternalLinkPage subclass), `web/components/AISidebar.tsx` (new, ~470 LOC), `web/lib/ai-chat.ts` (new), `web/app/layout.tsx` (wires sidebar). **Deferred to v2** (BACKLOG.md): SSE streaming (currently synchronous), conversation persistence to disk, per-page payload-aware context (`page_context.payload` field reserved but not populated), more tools (get_team / get_standings / get_movements), token usage tracking + daily cap, inline embedded Metabase static-embed previews. **2026-05-15 (late-evening) shipped the native desktop shell (D32)** — Diamond is now a native Windows app: one `Diamond.exe`, no browser tab, no flapping cmd windows, clean shutdown via Windows Job Object. **Five-slice ship**: (1) **Launcher MVP** — `src/diamond/desktop/{launcher,sidecar,paths}.py` orchestrates lifecycle; uvicorn runs in a daemon thread (in-process, no `python.exe` subprocess inside the frozen bundle); Next.js standalone runs as a hidden `node server.js` child via `CREATE_NO_WINDOW`; both bind 127.0.0.1 with port auto-fallback. (2) **Standalone build** — `web/next.config.mjs` flipped to `output: 'standalone'`; `scripts/build_desktop.py` runs `next build` + copies `.next/static` and `public/` into the standalone tree; `make desktop` chains build + run. (3) **Lifecycle hardening** — Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) so every spawned PID dies with the launcher, even on hard-kill (eliminates stale-process failure mode entirely; `kill-stale.bat` deprecated for the desktop path); single-instance lock via `CreateMutexW` + `Local\\Diamond.OOTP.Desktop.SingleInstance`, second double-click sees `ERROR_ALREADY_EXISTS` and focuses the running window via `FindWindowW` + `SetForegroundWindow`. (4) **PyInstaller bundle** — `src/diamond/desktop/diamond.spec` is a one-folder spec (not `--onefile` — the standalone tree's many small files would add 2-3s per-launch unpack to TEMP); datas: web standalone tree → `web_standalone/`, asset folder → `desktop_assets/`; hidden imports cover all 23 API route modules + uvicorn dynamic imports + pywebview backends + pystray + PIL; `make desktop-package` → `dist/Diamond/Diamond.exe`. (5) **Polish** — single-window-morph (one window opens with splash HTML at final size, boot thread calls `window.load_url(main_url)` when sidecars ready — `load_url` is thread-safe in pywebview); WebView2 runtime probe before pywebview starts, missing → friendly `MessageBoxW` with install URL (Win10 edge case); tray icon (pystray, daemon thread): Show / Open Metabase / API docs / Quit; tray and splash both fail-soft. **Run modes**: `dev.bat` (engineering hot-reload — unchanged), `python -m diamond.desktop --dev` (iterating on launcher code while dev.bat runs), `make desktop` (production-path validation locally), `make desktop-package` (full bundle). **What stays unchanged**: `dev.bat` two-terminal workflow kept for engineering; Metabase Workshop launcher (D31) still opens in default browser; all API routes / schemas / theme system / dictionary / warehouse zero-touch. `docs/DESKTOP.md` covers architecture / build pipeline / troubleshooting / when-not-to-use; `docs/DECISIONS.md` D32 has the full reasoning vs Tauri / Electron / static-export Next.js. **Deferred to v2** (tracked in BACKLOG.md): code signing (SmartScreen friendliness), Inno Setup MSI installer, auto-update, bundled Node, Mac/Linux ports, minimize-to-tray. **2026-05-15 (evening) shipped the Metabase integration (D31)** — Diamond now has a self-hosted, save-aware Metabase as its full-BI workshop. Pattern A wiring: single Metabase Database connection follows the active save (every `POST /api/saves/active` PUTs new `database_file` + triggers `sync_schema`). Install at `~/.diamond/metabase/` (Metabase OSS 0.59.10 + DuckDB driver 1.5.2.0, bound to localhost:3001 via `metabase.bat /b` launcher). 5 sample cards + 1 dashboard built via REST API spike (proved AI-assisted dashboard workflow works: write MBQL/native-SQL spec, POST to `/api/card`, dashboard renders). Workshop tab at `/explore?mode=workshop` is a **launcher card** (NOT iframe — Metabase OSS sends `X-Frame-Options: DENY` + `frame-ancestors 'none'`; interactive embedding is paid Pro feature) — click opens Metabase full-screen in new tab. Three deep-link sub-cards (New question / Sample dashboard / Browse warehouse). New `GET /api/admin/metabase-status` for same-origin liveness probe. `src/diamond/api/metabase.py` coordination module (auth + cached session at `~/.diamond/metabase_session.txt` + `repoint_active_save()`); credentials at `~/.diamond/metabase_credentials.toml` (gitignored by virtue of being outside repo). Best-effort + silent-on-failure (Metabase down / no creds → save switch still succeeds). `docs/METABASE.md` covers install / ops / Pattern A / threat model / troubleshooting / AI workflow. Same-day corrections: port flip (3000→3001 to avoid Next.js collision), inline-async-child SSR fix in `/explore`, iframe→launcher pivot. **2026-05-15 (afternoon) shipped the capability wave (D30) — four slices** moving the platform from "trustworthy + data-complete" (post-D29 L_REF) to "visibly more capable": (A) **leverage stack** — new `f_player_season_leverage_batting` (32,767) + `_pitching` (32,338) materializing WPA from L0, LI from L0 (per-PA Tango = SUM(li)/SUM(bf), empirically decoded — Martinez 2.41 / Yesavage 1.04, matches MLB closer/starter ranges), RE24 multi-year from `lref_re288_table` joined to `f_pa_event` via window-function after-state, Clutch = WPA/LI per Tango. Wired to player page Advanced columns + leaderboards (6 new stats) + 4 KaTeX glossary entries. Eldridge 2029 WPA +5.81 / RE24 +49.4. (B) **Real OOTP team logos** across cockpit + standings + movements + leaderboards + player page — `GET /api/photos/teams/{team_id}.png?size=N` with size-snapping to OOTP variants (16/25/40/50/110/full); new `<TeamLogo>` component with abbr-pill fallback. (C) **Spray chart geometry swap** — `StadiumSprayChart` now sources OOTP-canonical 7-segment geometry from `/api/parks` (`lref_pt_ballparks`) via an adapter to the renderer's 5-point spline; hand-coded `web/lib/stadiums.ts` retained for cosmetic feature flair (Green Monster, ivy, etc.); Fenway dead-CF wall corrected from 17→9 ft. (D) **Real HoF plaques on /history/hof** — `GET /api/photos/hof/{bbref_id}.png` streams from install `hof/`; `GET /api/photos/hof` manifest of plaques on disk; `HofPlayer.bbref_id` resolved via name + birth-year JOIN against `history_lahman_people`; horizontal-scroll plaque gallery above the inductees table with deep-links to `/player/{id}` (7/8 plaques deep-link in this save). Phase 2 closed 2026-05-05; analytical layer + real-history backfill closed 2026-05-06; UI scaffold + player Stats tab landed 2026-05-07; 2026-05-08 shipped the IA backbone (D17), theme system (D18), movement ledger, real landing page, and in-app Quit / dev.bat launcher; 2026-05-09 shipped the roster page + L3 SIERA + a Statcast cohort + full dump-CSV vs L0 audit. **2026-05-10 shipped three player-page slices in one day** — combined bWAR / pWAR (OOTP-canonical, IE-A-tier reconciled), per-position fielding view (Defensive Profile section), and service-time / arb clock (Service & Status card). 2026-05-11 shipped the standings page — first real content on the `/league` tab. **2026-05-12 shipped five situational-stack slices** plus an end-of-day maintenance fix: (1) batter situational splits on the player page; (2) **multi-year `f_pa_event`** — closes the prior-year coverage gap by reading L0 directly with cross-dump dedup keyed on (game_id, season_year); discovered **OOTP recycles `game_id` across seasons**, PK promoted to (year, game_id, batter_id, pa_in_game_seq). f_pa_event 877k → 5.1M rows, Statcast cohort tables 3,305/3,692 → 20,800/21,513; (3) pitcher situational splits with inverted color logic; (4) bases / platoon splits with side-aware labels and switch-hitter resolution; (5) counts (first pitch / two strikes / full count) + spray (pull / center / oppo) splits. **14 splits per (year, level)** total. Empirically verified along the way that `hit_xy` is **batter-relative** (mean hit_xy on HRs ≈71 for both LHB and RHB — same pull-side band for both hands), correcting earlier DATA_NOTES claim. Crochet 2027 RISP 2-out **.316 OPS allowed** (elite); Devers 2029 Pull 12 HR / Center 15 HR / Oppo 0 HR (27 total). Five-tab nav (Club / League / World / History / Explore); dark mode is the default. **End-of-day maintenance pass (D20)** — Lahman 1871-2019 + BREF 2020-2025 league aggregates UNIONed into `_lg_constants_advanced` so OOTP-imported pre-2026 player-seasons (Bonds, Mantle, Trout, Pedro, etc.) now resolve real wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR. f_player_season_advanced_batting 30k → **244,183 rows**; spot-checks Bonds 2001 OPS+ 257 (BBR 259), Pujols 2003 OPS+ 189 (BBR 189 — exact), Trout 2018 OPS+ 198 (real 198 — exact). **2026-05-12 (continued) — History tab fully drained + Pressure board shipped.** All five History stubs (Records + Awards + HoF + Streaks + Draft) plus the Pressure board (`/pressure`) — the GM-decision "who *should* move" companion to `/movements`. Records: `GET /api/records?scope=&discipline=&category=&era=` UNIONs save + Lahman + BREF + merged + Statcast leaderboards. Awards: `GET /api/awards?league_id=&award_id=&era=` returns career trophy-count holders (Ohtani / Bonds 7 MVPs, Maddux 18 GG). HoF: `GET /api/hof?view=` toggles between Inductees (285) and Candidates (top-25 non-inducted by career WAR — Bonds 146.6 / Clemens 142.6 / Pete Rose 123.0). Streaks: `GET /api/streaks?streak_id=&scope=` for 21 streak types × 2 scopes (Szykowny 56-game hit streak ties DiMaggio). Draft: `GET /api/draft?year=` returns the full ~600-pick class grouped by outcome bucket (MLB Regulars → Callups → Still Developing → Traded → Released → Retired); Sox 2026 spotlights Skelton 4.124 (3.6 WAR find) + Jackson Flora 1.12 LAA (4.4 WAR class leader). Color-coded chips, player-page deep-links, forgiving fallbacks across all five History pages. Pressure: `GET /api/pressure?year=&limit=` returns per-level promotion candidates (top OPS+/ERA+) + pressure cases (bottom) for the org tree. 2029 spotlights Caleb Durbin 183 OPS+ at AAA / 97 at MLB ("stop yo-yo'ing him") + Garcia/Rodriguez/White as AAA call-up candidates while Narvaez 75 / Anthony 94 / Langeliers 94 sit on the MLB pressure list. **2026-05-13 shipped five slices + an IA shuffle**: (1) **Custom leaderboards** at `/league/leaderboards` — TanStack Table with 32 stats across batting / pitching / Statcast, URL-driven picker, heat-scale on plus-stat / WAR columns; (2) **Spray + EV-LA charts inline on the player page** with `@observablehq/plot` + hand-rolled polar-fan SVG (D23 commits to Observable Plot for cohort viz, deferring Vega-Lite + WebGL until JSON-spec authoring or full-league cohort scale); (3) **Historical park factors (D22)** — pre-2020 MLB OPS+/ERA+ now use Lahman BPF/PPF via a `_park_factor_resolved` view + 30-row OOTP↔Lahman franchID crosswalk. Bonds 2001 OPS+ 257→267 (BBR 259), Pujols 2003 189→193 (BBR 189), Trout 2018 198→201 (BBR 198), Coors 1995 BPF 1.29; (4) **AI overlay (D14)** — `diamond/ai/` package with keyring-backed key storage + Anthropic + OpenAI adapters via httpx (no SDK deps), `/api/ai/settings` + `/api/ai/summarize`, settings page at `/settings/ai`, "Summarize career" button on player page; (5) **Setup wizard (D3 v2)** — `/api/saves` + `/api/saves/active` for save discovery + active-save switcher with persistence to `~/.diamond/active_save.toml`; UI at `/settings/save` with cards for each save under the OOTP saves root, "needs ingest" badge for saves without a warehouse. Settings landing at `/settings` now linked from header (⚙ icon). **End-of-day IA shuffle**: `/explore` is now JUST the **Chart Builder workshop** (pick X/Y/color from the 32-stat catalog, filter, render via Plot.dot scatter or Plot.rectY histogram; cross-table joins handled transparently). Per-player charts moved inline to the player page; league-wide tools (leaderboards + compare) moved to `/league/*`. Permanent 308 redirects keep old URLs working. Also added a `kill-stale.bat` recovery file at repo root + wired `dev.bat` to call it as a self-heal step (clears zombie processes on :3000 / :8000 from a crashed prior session). **2026-05-13 (continued, evening)**: per-save scope (D3 v2.1) — `~/.diamond/save_configs.toml` per-save audit_team_id + league_ids; static 30-team `mlb_teams.py` catalog; `diamond ingest --save NAME` flag; division-grouped picker UI on `/settings/save`; legacy-default bootstrap migration. Photo cache (D24) — flipped from `max-age=86400, immutable` to ETag + Last-Modified revalidation with `Cache-Control: no-cache`; new photos appear instantly when OOTP regenerates instead of after 24h browser cache. Auto-ingest at launch — `dev.bat` chains `diamond ingest --all` before uvicorn binds; `GET /api/admin/dump-status` + `POST /api/admin/ingest` + header `↻ Refresh` button (`RefreshButton.tsx`) for mid-session pickup, polls every 60s with badge when pending; `diamond status` CLI for terminal introspection. **LSEG-Workspace density refactor (D25)** — full-width layout (drops `max-w-6xl`); compact sticky header; `useElementWidth` hook drives responsive Plot charts (EvLaScatter + ChartBuilder fill containers, StadiumSprayChart caps at 720px); page-headers across 9 main pages collapsed from `text-3xl space-y-8` → `text-xl space-y-4` LSEG-uniform pattern. **Major architectural finding (D26)** — `<docs>/Out of the Park Developments/OOTP Baseball 27/` parent folder is a goldmine of reference data we'd been ignoring: `database/pt_ballparks.txt` (240 MLB+minors parks with 7-segment dimensions + LH/RH split park factors), `database/era_ballparks.txt` (3,105 rows × 155 years 1871-2025 historical park factors with handedness splits), `database/era_stats.txt` (82-col historical league averages per era), `stats/Master.csv` (24,747-row OOTP↔Lahman crosswalk including `lahmanID`/`BBrefMiLBid`/`retroID` — replaces our Chadwick crosswalk), `stats/MiLBMaster.csv` (29MB minor-league master), `database/db_structure_complete_ootp21_*.txt` (canonical schema docs), 1,829 logos in `logos/` (`.oi` files are PNGs — magic bytes confirmed) including per-era variants, 343 ballcaps, full uniform asset set. **D26 commits to an `L_REF` reference layer** sitting alongside L0-L3, ingesting from this parent folder once and joining into existing tables. **2026-05-13 evening also produced a meticulous deep-dive of the SAVE folder** (`<save>/<save_name>.lg/`) which surfaced `temp/text_data.sqlite3` (188MB SQLite, 4 years retained, contains `league_news` 16,718 / `team_news` 43,206 / `league_transactions` 149,769 / `team_transactions` 350,169 / `player_history` 314,678 / `league_injuries` 63,065 / draft logs / etc.) as a potential future augmentation source. Empirically determined that `news/html/box_scores/*.html` (18,982 files) and `replays/*.rpl` (6,481 files) are **EPHEMERAL — wiped each season as game_id resets**; do NOT depend on them. **D28 pins**: dumps remain primary; SQLite-backed `L_NEWS` layer is deferred until UX need pulls it in (would augment movements with OOTP's authoritative `transaction_type`, add player career bio timeline as new capability, add cockpit news ticker as new capability); ephemeral box-score-HTML and replay sources are deliberately ignored; `messages/` folder dropped per user preference. **2026-05-13 deep-dive expanded the L_REF scope (D27)** — `misc/` ships OOTP's canonical analytical lookup tables (`xwoba_table.txt`, `xba_table.txt`, `xslg_table.txt`, `re288_table.txt`, `wpa_table.txt`, `li_table.txt`, `xiso_table.txt`) which are the EXACT (LA, EV) → xwOBA / RE288 / WPA / LI tables OOTP itself uses at sim time; reading them directly guarantees our numbers match the in-game UI exactly. Also discovered `database/era_modifiers.txt` (per-year talent multipliers), `database/era_fielding.txt` (per-position FLD baselines), `database/total_modifiers.txt`, `database/financials.txt` (salary-bracket engine), `database/major_league_baseball.json` (authoritative league rules), `hof/index.json` + 8+ real HoF plaque PNGs, `colors/*.xml` (per-team brand palettes), `tables/*` (OOTP's saved column-layouts per view), `database/db_structure_ootp27_csv.txt` (version-current schema doc, replacing the ootp21 fallback we'd been using). **D27 pins L_REF as per-save, frozen at first ingest, opt-in refresh** (`diamond ingest --refresh-lref`) — mirrors OOTP's own engine convention of capturing reference data into the save at creation and ignoring subsequent install-folder edits. **2026-05-14 shipped L_REF Slice 1** — new `src/diamond/schema/l_ref.py` ingest module reads from `<docs>/Out of the Park Developments/OOTP Baseball 27/{misc,database,stats}/` into 27 per-save `lref_*` tables (575,587 rows total) with first-ingest freeze + SHA1 provenance: misc/ analytical lookup tables (`lref_xwoba_table` 106 LA-rows × 61 EV-cols, `lref_xba_table`, `lref_xslg_table`, `lref_xiso_table` 6-zone, `lref_re288_table` 24×12, `lref_li_table` 432, `lref_wpa_table` 480, `lref_pi_table` 3); database/ baselines + park factors (`lref_pt_ballparks` 240, `lref_era_ballparks` 3,105 with LH/RH splits, `lref_era_stats` 156 years 1870-2025 × 82 cols, `lref_era_stats_minors` 2,335 × 47 cols, `lref_era_modifiers`/`_fielding`/`_total_modifiers` 153-155, `lref_financials` 156, `lref_weather` 513, `lref_default_players` 12,854); stats/ crosswalks (`lref_master` 24,746 rows OOTP↔Lahman replacing Chadwick, `lref_milb_master` 212,325, `lref_teams_history` 3,142, `lref_milb_leagues`/`_milb_teams`, `lref_eos_rosters`/`_od_rosters` ~100k, `lref_uni_numbers` 86k, `lref_series_post` 411). Provenance lives in `_diamond_settings.lref.{frozen_at,source_root,ootp_version,table_count,files_json}`; `compute_lref_diff()` SHA1-compares each spec vs frozen snapshot; `diamond ingest --refresh-lref` re-ingests changed files only and implies a full L1+L2 rebuild. Reference doesn't drift mid-save (Bonds 2001 OPS+ won't shift between sessions). **2026-05-14 also shipped L_REF Slice 2 (calc-parity swap)** — two new fact tables `f_player_season_xstats_batting` (20,787 rows) + `_pitching` (21,504 rows) materialize OOTP-canonical xwOBA / xBA / xSLG per BIP via 1D linear interpolation of `lref_xwoba_table` / `lref_xba_table` / `lref_xslg_table` (LA × EV grids). Implementation: `_xwoba_lookup` / `_xba_lookup` / `_xslg_lookup` long-form views via DuckDB `UNPIVOT`; `_f_pa_event_xstats` per-BIP interpolation view (LA is integer in the OOTP at-bat dump so no LA-axis interp needed); season aggregations keyed on `batter_id` / `pitcher_id`. Wired into `PlayerAdvancedBattingRow` / `PlayerAdvancedPitchingRow` schemas with NULL-safe LEFT JOIN; player page Advanced columns now show `wOBA | xwOBA` side-by-side. `xwOBA` / `xBA` / `xSLG` added to leaderboards stat catalog + 3 glossary entries with KaTeX formulas. Verified: 2029 MLB top xwOBA leaders Henderson .315 / Okamoto .309 / Nimmala .302; Devers actual wOBA .320-.355 vs xwOBA-BIP .264-.288 (gap = K/BB/HBP exclusion, expected); Crochet allowed-xwOBA .277 → .266 → .236 → .237 across 2026-2029 (pairs with FIP trajectory).

**2026-05-14 also shipped L_REF Slices 3 + 4 + 5 + 6 (data layer) — closing the L_REF analytical wave (D29 marks the rollout outcome).** Slice 3 (era park factors with LH/RH splits): `_park_factor_resolved` swapped from `history_lahman_teams` to `lref_era_ballparks` (3,105 rows 1871-2025) with handedness columns `bat_park_avg_lh/rh`, `pit_park_avg_lh/rh`; batter handedness blend in builder (bats=L → LH PF, R → RH PF, S → 60/40 blend per Tango); Bonds 2001 OPS+ 267→262 (BBR 259), Walker 1999 OPS+ 215→191, modern 2026-2029 invariant. Slice 4 (era_stats source swap): collapsed Lahman+BREF UNION into single `lref_era_stats` source (1870-2025, 156 rows × 82 cols); same numerical answer (Bonds 2001 / Pujols 2003 / Trout 2018 within ±1%); soft-skip flipped to `lref_era_loaded`. Slice 5 (MiLB pre-save baselines — closes deferred backlog): `_lg_constants_advanced_imported` extended with 11 MiLB leagues × 60-124 yrs each via `lref_era_stats_minors`; pre-2026 MiLB player-seasons went from `—` everywhere to **84,000 newly-resolved player-seasons** (88k MLB-only → 172k MLB+MiLB with non-null wOBA); real historical AAA legends resolve (Joe Lis 1972 IL wRC+ 289, McCovey 1959 PCL 284, Trout 2012 PCL 190); PCL 2012 lg_obp .343 vs IL .329 properly differentiated. Slice 6 data layer: `/api/parks` returns all 240 modern ballparks from `lref_pt_ballparks` with 7-segment outfield geometry + LH/RH split factors per stat; frontend `StadiumSprayChart` swap deferred to Slice 6 v2 (renderer geometry refactor).

**L_REF rollout outcome (per D29)**:
- **Pre-save advanced stats are now end-to-end OOTP-canonical** — every reference value feeding wOBA / wRC+ / OPS+ / FIP / ERA+ comes from L_REF (frozen with the save per D27): `lref_era_stats` for MLB baselines, `lref_era_stats_minors` for MiLB, `lref_era_ballparks` for park factors with handedness, `lref_xwoba_table` + siblings for per-BIP x-stat estimates.
- **No external-fetch dependency for advanced-stat calculation**. Lahman/BREF still used by per-player record / award / HoF leaderboards (different consumers).
- **Slice 7 skipped** — `lref_master` lacks `mlb_id` / `BBrefMLBid` so it can't replace Chadwick for current `mlb_id → bbref_id` consumers; Master.csv complements but doesn't replace.
- **Slice 10 partially blocked** — `colors/*.xml` is uniform-asset metadata, NOT hex palettes as D26 implied; no parseable brand-color data in the install folder.
- **Slices 8 / 9 / 6-frontend deferred** — pure cosmetic; tracked in BACKLOG.md.

The reconciliation harness (`reconcile.py`) stays in the codebase as a permanent post-ingest regression check (Decision D8). The reconciliation harness (`reconcile.py`) stays in the codebase as a permanent post-ingest regression check (Decision D8).

## Setup & commands

```bash
pip install -e ".[dev]"            # editable install + pytest/ruff
diamond --help                     # list CLI commands
```

### Two-process dev workflow (D16)

Diamond ships as **FastAPI on :8000 + Next.js on :3000**. You always want both running in separate terminals so you can read each one's logs.

```bash
# Terminal 1 — backend (FastAPI + uvicorn --reload)
make api

# Terminal 2 — frontend (Next.js dev server)
make web

# Windows one-shot launcher — spawns both in their own windows + opens the browser.
# Self-heals stale processes on :3000 / :8000 + auto-ingests new dumps.
dev.bat

# After Pydantic schema changes — regenerate web/lib/types/api.ts
make types

# End-to-end warehouse build + invariant check (~60s)
make smoke        # or: scripts/smoke_warehouse.py
```

`make api` exports `PYTHONIOENCODING=utf-8` (set once at the top of the Makefile) so Rich box-drawing + dictionary unicode glyphs render in cmd. The Makefile is the single source of truth for per-server launchers; the prior `api.bat` / `web.bat` / `kill-stale.bat` files were deleted in D34 cleanup (2026-05-16).

### Native desktop shell (D32)

Diamond ships as a native Windows app — single `Diamond.exe`, no browser, no flapping cmd windows, clean shutdown via Windows Job Object. Use this path for **production user experience**; `dev.bat` is for engineering hot-reload.

```bash
make install-desktop               # one-time: PySide6, pystray, Pillow, PyInstaller, psutil
python -m diamond.desktop --dev    # iterating on launcher/tray code while dev.bat runs
make desktop                       # production-path validation locally (next build + open native window)
make desktop-package               # full bundle → dist/Diamond/Diamond.exe
```

The launcher (`src/diamond/desktop/launcher.py`) follows a **single-window-morph** pattern: one `QApplication` + `QMainWindow` + `QWebEngineView` opens with splash HTML at final size; a boot thread emits a Qt signal carrying the URL once both sidecars are ready (uvicorn in-thread + Next.js standalone subprocess), and the slot on the GUI thread calls `view.load(QUrl(...))`. Qt auto-marshals across threads via the meta-object system. Job Object guarantees children die with the launcher; named mutex enforces single-instance. PySide6's QtWebEngine bundles its own Chromium so end-users don't need WebView2 installed. See `docs/DESKTOP.md` for the full architecture.

### CLI commands (audit + analytical surface)

```bash
diamond ingest                     # ingest the latest dump → L0…L3 warehouse build
diamond ingest --all               # ingest every dump in <save>/dump/ in chronological order
diamond ingest --rebuild-only      # rebuild L1+L2+L3 from existing L0 (cheap; ~30s)
diamond ingest --save NAME         # operate on a non-active save (with .lg suffix)
diamond migrate-dump-dates         # one-shot: rewrite dump_date columns to end-of-month (D36)
diamond status                     # show ingest gap (pending dumps) for a save
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
                              movements, standings, admin, recent (Phase 4b
                              Tier D rolling windows), trajectory (Phase 4b
                              Tier B per-dump trajectory)
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
    l2_ootp.py              D40 Phase 4a #2 — OOTP-cache passthrough facts:
                            f_team_season_{batting,pitching,fielding}_ootp,
                            f_player_stint_{batting,pitching,fielding}_ootp,
                            f_league_season_{pitching,fielding}_ootp,
                            f_player_value_current, v_player_ratings_by_side.
                            Each builder asserts orphan columns via
                            _assert_columns_present (loud failure on
                            OOTP version-bump column drops).
    l2_game_grain.py        Phase 4b Tier A — per-(player, year, game) fact
                            tables sourced from `l0_players_game_*`. Two
                            tables: f_player_game_batting (1.1M Padres),
                            f_player_game_pitching (355K). Cross-dump dedup
                            via ROW_NUMBER PARTITION BY natural key ORDER BY
                            dump_date DESC; JOIN to deduped l0_games for
                            date. ORDER BY (player_id, date) for sequential
                            scans. Unblocks rolling windows + Phase 5 Almanac.
    l2_history.py           Phase 4b Tier B — per-dump SCD2 history snapshots
                            sourced from L0 directly (L1 events collapse to
                            MAX(dump_date)). Three tables:
                            f_player_season_batting_history (15M rows),
                            f_player_season_pitching_history (8M),
                            f_player_career_history (3M). Cross-stint dedup
                            at (player, year, team, league, level, split,
                            stint, dump_date) grain before GROUP BY collapses
                            to per-season rollup. Same team-scope filter as
                            the D40-fix career events.
    invariants.py           Phase 4b D40 watchdog — comparator over L2_OOTP
                            (OOTP-cached) vs Diamond-derived aggregates.
                            Stores per-(team, year, level, metric) drift
                            into `_diamond_invariants` with green/amber/red
                            status. 9 invariants (team AVG/OBP/SLG/ERA/WHIP
                            /K9/BB9 + PA/HR event counts). 99.8%→100% green
                            on Padres post the 2026-05-14 career-event scope
                            fix. Auto-runs at end of rebuild_l1_l2.
    l_ref.py                D27 — per-save reference layer frozen at first
                            ingest. 27 lref_* tables from the OOTP install
                            folder (`misc/`, `database/`, `stats/`).
    l_ie.py                 D41-routing — per-save L_IE display layer sourced
                            from `<save>/import_export/*_organization_-_roster_*.csv`.
                            21 lie_* tables (DROP-and-rebuild per refresh,
                            unlike L_REF which is frozen). Three unified
                            views v_lie_player_{batting,pitching,fielding}_display
                            parse OOTP display strings to typed numerics
                            ready to COALESCE in API CTEs. Wired into
                            `_fetch_advanced_batting` + `_fetch_advanced_pitching`
                            via single-stint org-roster + latest-year
                            eligibility predicate.
    l3.py                   trade attribution / movements / draft / records / awards / streaks
    l3_advanced.py          per-(player, year, league, level) advanced-stats fact tables
                            (sabermetric: woba/wraa/wrc/wrc+/ops+/owar/**bwar**;
                             fip/siera/era+/pwar/**p_war**/**p_ra9_war**)
                            + Statcast cohort tables (f_player_season_statcast_batting +
                            _pitching: bip/max_ev_p90/avg_ev/hh%/brl%/ss%, BIP ≥ 30)
                            + x-stats (f_player_season_xstats_batting +
                            _pitching: xba/xslg/xwoba via L_REF interpolation
                            + POW-aware per-player calibration on batting).
    build.py                orchestrator + admin (_diamond_ingests, _diamond_settings)
  dictionary/               D15 stat dictionary (60 entries — single source of truth for labels)
    __init__.py             Stat dataclass + CATEGORIES tuple
    _stats.py               canonical entries grouped by category
  desktop/                  D32 native desktop shell — PySide6 + QtWebEngine
    launcher.py             argv parse + lifecycle orchestration (single-window-morph)
    sidecar.py              uvicorn-thread + Next.js subprocess + port probes
    paths.py                source-vs-frozen path resolution (PyInstaller)
    win_jobobject.py        ctypes Job Object (KILL_ON_JOB_CLOSE)
    single_instance.py      Win32 named mutex + FindWindow/SetForeground
    splash.py               splash HTML loader (assets/splash.html)
    tray.py                 pystray icon + menu (Show / Metabase / API docs / Quit)
    diamond.spec            PyInstaller one-folder spec
    assets/splash.html      dark-themed cold-start splash matching D18
    __main__.py             python -m diamond.desktop entry
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
                            Header pill (Phase 4b D40 2026-05-14): "Drift NN.N%"
                            shows watchdog overall status (green/amber/red);
                            consumes /api/admin/invariants.
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
    RecentFormPanel.tsx     Phase 4b Tier D — "Recent form" panel above
                            the Stats tab year-by-year tables. Renders both
                            batting + pitching tables stacked, one row per
                            window (7d / 15d / 30d). Localized date-range
                            display. "No games in window" empty state.
                            Consumes /api/players/{id}/recent.
    RosterClient.tsx        client component — three filter pills (Level/Role/Hand) + three-mode
                            stat toggle (Basic/Advanced/Contact); dense Bref-style tables
    FormulaBlock.tsx        KaTeX wrapper with parse-fail fallback
    ThemeSwitcher.tsx       client component — light/dark/neutral/cb dropdown, localStorage-persisted
    AISidebar.tsx           D33 — floating AI launcher + slide-out chat panel (470 LOC)
    PagePayloadProvider.tsx D33 follow-up — React Context for pages to publish data to the AI sidebar
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

**API surface today** (37 endpoints — D34 removed `/api/admin/shutdown` 2026-05-16; D35 added `/api/ai/chat/stream`; Phase 4b 2026-05-14 added `/api/players/{id}/recent`, `/api/players/{id}/trajectory`, `/api/admin/invariants`): `/api/health`, `/api/save`, `/api/cockpit`, `/api/glossary`, `/api/glossary/{id}`, `/api/players/{id}` (also returns per-position fielding cube + service-time/roster-status block + situational-batting splits + active contract block + xwOBA-BIP / xBA-BIP / xSLG-BIP per advanced row — D29 Slice 2), `/api/players/{id}/batted_balls?year=&level_id=` (BIP events for spray + EV-LA), `/api/roster`, `/api/movements?year=YYYY[&include_pending=1]`, `/api/standings?league_id=&year=`, `/api/records?scope=&discipline=&category=&era=&limit=`, `/api/awards?league_id=&award_id=&era=&limit=`, `/api/hof?view=&limit=`, `/api/streaks?streak_id=&scope=&limit=`, `/api/draft?year=`, `/api/pressure?year=&limit=`, `/api/compare?ids=`, `/api/leaderboards/options`, `/api/leaderboards?stat=&year=&level_id=&league_id=&pa_min=&limit=` (xwOBA / xBA / xSLG added to catalog), `/api/chart-builder?x=&y=&color=&year=&level_id=&league_id=&qualifier_min=&limit=`, **`/api/parks`** (240 modern ballparks from lref_pt_ballparks with 7-segment geometry + LH/RH split factors), `/api/saves`, `POST /api/saves/active`, `GET/POST /api/saves/{name}/config` (per-save audit_team_id + scope persistence — D3 v2.1), `/api/ai/settings`, `POST /api/ai/settings`, `POST /api/ai/summarize`, `/api/photos/players/{id}.png` (revalidation-cached, D24), **`/api/photos/teams/{team_id}.png?size=N`** (D30 Slice B — size-snaps to OOTP variant 16/25/40/50/110/full), **`/api/photos/hof`** (D30 Slice D — manifest of plaques on disk), **`/api/photos/hof/{bbref_id}.png`** (D30 Slice D — streams from install hof/), `GET /api/admin/dump-status`, **`GET /api/admin/metabase-status`** (D31 — same-origin liveness probe for Workshop tab; returns running / configured / active_save_db / message), `POST /api/admin/ingest` (auto-detects + ingests new dumps mid-session), **`POST /api/ai/chat`** (D33 — synchronous chat with tool loop), **`POST /api/ai/chat/stream`** (D35 Tier C — `text/event-stream` SSE variant of `/api/ai/chat`; emits `text_delta` / `tool_use` / `tool_result` / `iteration` / `done` events), **`GET /api/players/{id}/recent?windows=7,15,30`** (Phase 4b Tier D — aggregated batting + pitching lines over each calendar-day window, anchored to player's most recent regular-season game; consumes `f_player_game_*`), **`GET /api/players/{id}/trajectory`** (Phase 4b Tier B — career + latest-season per-dump trajectory points with rate stats computed server-side from counting columns; consumes `f_player_career_history` + `f_player_season_*_history`), **`GET /api/admin/invariants`** (Phase 4b D40 — overall + per-metric watchdog rollup + top-20 failures sorted by |delta|; powers the cockpit drift pill).

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

L2_OOTP             D40 Phase 4a #2 (2026-05-10) — 9 OOTP-cache passthrough
                    fact tables + 1 view exposing the previously-orphan
                    OOTP-cached rate stats as named columns. See
                    `schema/l2_ootp.py` for the full inventory. Feeds
                    the D40 invariants watchdog as its dump-value source.

L2_game_grain       Phase 4b Tier A (2026-05-14) — 2 game-grain fact tables:
                      f_player_game_batting  PK (player_id, year, game_id),
                                              ~1.1M rows on Padres / 430K Sox
                                              smoke, 18 stat cols incl PA/AB/H/
                                              HR/RBI/BB/K + dims + canonical date
                      f_player_game_pitching PK same shape, ~355K Padres /
                                              134K smoke, 25 cols (outs/BF/H/ER/
                                              BB/K/HR+ GS/W/L/SV/BS/HLD)
                    Cross-dump dedup via ROW_NUMBER ORDER BY dump_date DESC.
                    JOIN to deduped l0_games for canonical date.
                    ORDER BY (player_id, date) in CTAS — DuckDB physically
                    sorts the table on disk for sequential scan speed.
                    Game-grain fielding deferred (no L0 source).

L2_history          Phase 4b Tier B (2026-05-14) — 3 per-dump SCD2 history
                    tables sourced from L0 directly (L1 events collapse
                    to MAX(dump_date)):
                      f_player_season_batting_history  PK (player_id, year,
                            league_id, level_id, split_id, dump_date)
                            ~15M rows on Padres (29 dumps × 600K player-seasons)
                      f_player_season_pitching_history same shape, ~8M rows
                      f_player_career_history          PK (player_id, dump_date)
                            ~3M rows (career rollups per dump)
                    Cross-stint dedup at the (player, year, team, league,
                    level, split, stint, dump_date) grain before GROUP BY
                    collapses to per-season rollup. Same team-scope filter
                    as the D40 fix. Powers /api/players/{id}/trajectory and
                    future sparkline UI consumers. ~100s rebuild penalty.
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
                       materialized from f_pa_event),
                       **f_player_season_xstats_batting + _pitching**
                       (Phase 4a-ext-1 + Phase 4b POW-aware calibration on
                       batting: xba/xslg via L_REF (LA, EV) interpolation
                       with per-player POW correction `0.00823 + 0.00054·(POW-50)`
                       for xba and `0.01527 + 0.00115·(POW-50)` for xslg;
                       year-aware POW lookup via `players_ratings_snapshot`),
                       **f_player_season_leverage_batting + _pitching**
                       (WPA + RE24 + LI + Clutch from L0 + lref_re288_table)

_diamond_invariants Phase 4b D40 (2026-05-14) — warehouse drift watchdog,
                    one row per (team, year, level, metric) per dump_date
                    storing the OOTP-cached vs Diamond-derived comparison.
                    9 active invariants on Padres yield 100.0% green (4,553
                    / 4,554; 1 informational red on Boston 2026 MLB is
                    OOTP's own L0-vs-team_history quirk).
History (one-time) lahman / bref / statcast / mlbapi / chadwick crosswalk
L_REF (Slice 1 shipped 2026-05-14, D26+D27) — 27 tables / 575,587 rows
                  per-save reference data, frozen at first ingest
                  (write-once for save lifecycle; refresh via
                  `diamond ingest --refresh-lref` with SHA1 diff preview).
                  Implementation in `src/diamond/schema/l_ref.py`;
                  provenance in `_diamond_settings.lref.{frozen_at,
                  source_root, ootp_version, table_count, files_json}`.
                  Ingested from
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
L_IE (Slice 1 shipped 2026-05-14, D41 routing layer) — 21 tables / 5,649 rows
                  per-save IE display values from
                  `<save>/import_export/*_organization_-_roster_*.csv`.
                  Org-agnostic suffix discovery (matches both Sox +
                  Padres prefix conventions). DROP-and-rebuild on every
                  warehouse refresh (NOT frozen like L_REF — these are
                  point-in-time snapshots of OOTP UI exports).
                  Implementation in `src/diamond/schema/l_ie.py`;
                  provenance in `_diamond_settings.l_ie.{last_ingest_ts,
                  source_dir, table_count, files_json, missing_json}`.
                  21 lie_* tables (one per import_export CSV):
                    lie_default, lie_popularity_info,
                    lie_personality___morale, lie_financial_info,
                    lie_batting_stats_{1,2}, lie_batting_superstats_{1,2},
                    lie_batting_ratings, lie_batting_potential,
                    lie_pitching_stats_{1,2}, lie_pitching_superstats_{1,2},
                    lie_pitching_ratings, lie_pitching_potential,
                    lie_individual_pitch_ratings, _potential,
                    lie_fielding_stats, lie_fielding_ratings,
                    lie_position_ratings.
                  Plus 3 unified views with parsed numerics
                  (TRY_CAST off raw VARCHAR display strings, ready
                  to COALESCE in API CTEs):
                    v_lie_player_batting_display  — 38 cols
                    v_lie_player_pitching_display — 26 cols
                    v_lie_player_fielding_display — 19 cols.
                  Wired into `_fetch_advanced_batting` +
                  `_fetch_advanced_pitching`: COALESCE swap-in for
                  single-stint org-roster players in the latest year.
                  View-existence gated by `_view_exists` for
                  L_IE-less warehouses.
```

The audit layer (Phase 1) is **scaffolding**. Advanced stats now run against the warehouse via `f_player_season_advanced_*`; the formulas in `src/diamond/advanced/` remain canonical for the audit harness + ad-hoc Polars/SQL paths.

### Configuration

- `src/diamond/config.py` defines `SaveConfig` (paths + scoped league IDs) and the singleton `BUILDING_THE_GREEN_MONSTER` for the active save (15 league IDs: MLB org tree + DSL + AFL).
- The OOTP saves root is hardcoded to `C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games`. Per save, the layout is `<save>/dump/dump_<YYYY>_<MM>/csv/*.csv` (monthly snapshots) and `<save>/import_export/*.csv` (the OOTP-generated reference roster CSVs we reconcile against). Per D2 the warehouse lives at `<save>/diamond/diamond.duckdb`.
- Per Decision D3, scope is hardcoded for v1 but a save-setup picker is a hard v2 requirement — keep the scoping mechanism in `SaveConfig`, not inline. **D3 v2.1 (2026-05-13)** lands per-save audit_team_id + league_ids in `~/.diamond/save_configs.toml`; `build_save_config(save_name)` constructs the live SaveConfig from persisted state, with bootstrap migration for the legacy `BUILDING_THE_GREEN_MONSTER` default.
- **OOTP parent-folder reference data (D26 + D27)** — `<docs>/Out of the Park Developments/OOTP Baseball 27/` contains ~500MB of static reference data spanning analytical lookup tables (`misc/xwoba_table.txt` + 6 sibling tables — OOTP's canonical (LA, EV)/RE288/WPA/LI math), historical baselines (`database/era_stats.txt` 82-col league avgs, `era_stats_minors.txt`, `era_modifiers.txt`, `era_fielding.txt`), authoritative park data (`pt_ballparks.txt` + `era_ballparks.txt` with handedness splits — beats hand-coded `web/lib/stadiums.ts` and Lahman BPF), crosswalks (`stats/Master.csv` — OOTP↔Lahman, replaces Chadwick), engine config (`major_league_baseball.json` — authoritative league rules; `financials.txt` — salary brackets), schema docs (`database/db_structure_ootp27_csv.txt` — version-current; we'd been working from ootp21), real HoF plaques (`hof/index.json` + 8+ PNGs), per-team brand colors (`colors/*.xml`), and 1,829 logos in `logos/` (`.oi` files are PNGs — magic bytes confirmed). v2 architecture introduces an **`L_REF` ingest layer** sitting alongside L0-L3. **Per D27, L_REF is per-save and frozen at first ingest** — `diamond ingest` snapshots reference data into `<save>/diamond/diamond.duckdb` once, then ignores subsequent install-folder edits unless the user explicitly opts into `diamond ingest --refresh-lref`. This mirrors OOTP's own engine convention (save reference data is captured at save creation; mid-version patches don't retroactively change running saves) and makes "why did Bonds 2001 OPS+ shift between yesterday and today?" a non-question. Treat the parent folder as **read-only canon**; never write into it.

### Reconciliation patterns (`audit/reconcile.py`)

**Save-agnostic since D38.** `diamond reconcile --save NAME --ie-dir PATH --source warehouse` runs against any save's warehouse with any folder of IE control CSVs. Filenames match the org-agnostic suffix `_organization_-_roster_*.csv` so Sox and Padres files resolve via the same FileSpec defs. Padres recon CSVs live at `docs/helpful_files/recon/Padres/` (270 players × 21 files, dated 7/31/2028) — permanent second test target.

When adding a new `FileSpec`:

- **Don't filter by `team_id`.** IE roster files show each player's *full season* totals (including stints on prior orgs and short-season stops). The standard pattern is `WHERE year = 2029 AND split_id = 1` — no team filter.
- Fielding stats use `split_id = 0` (no platoon split for fielding).
- Player ratings (`scouted_ratings`) need `WHERE scouting_team_id = 4` — this is **NOT** an audit_team_id; the L1 view at `_connect_warehouse` stamps a constant `4` regardless of save (D12 already filtered the view to audit_team_id, so the constant is just satisfying the hardcoded WHERE). Don't try to use the actual audit_team_id here — that's a bug-attractor.
- Use `overall_rating` / `talent_rating` (already 20-80) — **never** the raw `overall` / `talent` fields (0-200 internal scale). Per Decision D6.
- IP convention: `FLOOR(outs/3) + (outs%3)*0.1` (e.g., 517 outs → 172.1, not 172.4).
- Tier each column: A=direct dump field, B=trivial calc, C=needs league constants, D=modeled (xstats), E=at-bat aggregation, F=cannot replicate (per D5 or string-formatted display), G=needs scale conversion or integer→string mapping.
- The matcher (`_is_match`) normalizes IE display formats: `"-"` → null, `"9.1%"` → `9.1`, `"$28 800 000"` → `28800000`, `"1 (auto.)"` → `1`. Don't fight these in derivation SQL — let the matcher handle them.
- Add new dump CSVs to `_connect()`; that's where every reconcile job picks up its views.
- After any L3 formula change, re-run reconcile against BOTH Sox AND Padres before shipping (per D38 retrospective — single-instance testing hides assumptions).

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
- **`dump_date` is end-of-month** (D36, 2026-05-16). `dump_YYYY_MM` is exported when OOTP advances *into* MM+1, so its data represents stats through the LAST day of MM (e.g. `dump_2028_07` = stats through 2028-07-31, `dump_2028_11` = stats through 2028-11-30 after the WS). `dump_name_to_date()` returns `date(year, month, last_day_of_month)` via `calendar.monthrange` — leap years handled. Pre-D36 ingests landed dump_date on the 1st of the month; existing warehouses must run `diamond migrate-dump-dates [--save NAME]` once to migrate (idempotent via `_diamond_settings.dump_date_convention='end_of_month'` setting marker; not auto-run because a full migration on a large warehouse takes 10-15 minutes — opt-in only).
- **VARCHAR-vs-BIGINT defense in scope filters** (D36, 2026-05-16). DuckDB's `read_csv_auto` may park a numeric-looking column as VARCHAR when adjacent column variance confuses inference (observed first on The Fathers' `l0_trade_history.team_id_*` + `l0_league_playoff_fixtures.{league_id, team_id*}`, all string-quoted ints `'10'`, `'307'`). All scope filters in `l1_event.py` (`_SCOPE_PLAYER` / `_SCOPE_TEAM` / `_SCOPE_LEAGUE_HARDCODED_15` / `_SCOPE_TRADE`) wrap LHS in `TRY_CAST(... AS BIGINT)`; `f_trade_participant` builder TRY_CASTs every team_id, player_id (in UNNEST), message_id, and `date` (→ DATE). Same pattern in any future L1/L3 builder that filters on a foreign key from L0.
- **OOTP-canonical wOBA formula** (D38, 2026-05-17). Base linear weights × PA denominator: `(0.69·uBB + 0.72·HBP + 0.89·1B + 1.27·2B + 1.62·3B + 2.10·HR) / PA`. NOT the FanGraphs canonical `(AB + uBB + SF + HBP)` denominator with lg-OBP-scaled weights. The formulas converge for modern MLB hitters (SH=0); they diverge by .015-.020 for minor leaguers / pitchers batting with sac bunts. Lives in `l3_advanced.py:woba_calc` for production + `reconcile.py:BATTING_DERIVED_CTE` for audit. `lg_woba` in `_lg_constants_advanced_native` / `_imported` is `base_lg_woba` (base weights × lg_pa denom), no longer = `lg_obp`. The scaled `w_*` columns in lg_constants are retained for backward compat but no longer fed to player_woba. After any wOBA-formula touch, rebuild L3 + re-run reconcile against both saves.
- **Single-save testing hides assumptions** (D38 retrospective). The codebase was tested entirely against Sox for 6+ weeks; ~80% of the D36/D37/D38 bugs were latent in Sox the whole time and only surfaced when Padres exposed them (mid-season opening, SH>0 minor leaguers, VARCHAR inference, day-off date display, no `fetch-history`). The Padres save is now a permanent second test target — recon CSV folder at `docs/helpful_files/recon/Padres/` is a 270-player × 21-file ground-truth corpus. Re-run reconciliation after every L3 formula change. PRs that touch warehouse derivations should document: "verified on Sox + Padres warehouses."
- DSL teams: the Red Sox have one FCL + two DSL teams; org-level rollups must include all three.
- Park factors: **halved** for OPS+ / wRC+ (`1 + (avg-1)/2`), **80%** for ERA+ / pit_WAR (`1 + (avg-1)*0.8`). Audit-decoded; verified Crochet 2029 ERA+ 127 vs IE 127 (Fenway).
- **OOTP supplies WAR directly** as `players_career_*.war` / `.ra9war` (A-tier reconciled to IE since 2026-05-04). Aggregated into `f_player_season_*.war` + `.ra9war`, then SUMed into `f_player_season_advanced_batting.b_war` + `f_player_season_advanced_pitching.p_war` / `.p_ra9_war`. Surfaced on roster Advanced + player page Advanced. The custom `o_war` (offense-only, wRAA-based) + `pit_war` (FIP-only, flat-1.13-replacement) are NOT the canonical IE-reconciled values — they're inspectable alternatives kept for transparency. When users ask "what's player X's WAR?", the answer is `b_war` / `p_war`.
- League constants are per `(league_id, year, level_id)` — never roll up across levels. AAA wOBA uses AAA constants, not MLB's. (D11)
- League history coverage in this save is **2026-2029**. Pre-2026 MLB player rows (level_id=1, league_id=203) get baselines from `_lg_constants_advanced_imported` which **as of D29 (Slice 4) reads from `lref_era_stats`** (1870-2025, OOTP-canonical, 156 rows × 82 cols) — superseded the prior D20 Lahman+BREF UNION. Pre-2026 **minor-league rows now also resolve advanced stats** (D29 Slice 5) via `lref_era_stats_minors` covering 11 MiLB leagues × 60-124 yrs each (IL/PCL AAA, EL/SL/TL AA, NWL/SAL/MWL/CAL/CAR A+/A, FSL); ~84k newly-resolved pre-2026 MiLB player-seasons since 2026-05-14. Levels 5-8 (Short-Season A / Complex / DSL / AFL) still render `—` — no era_stats_minors coverage. Park factors for pre-2026 **as of D29 (Slice 3) come from `lref_era_ballparks`** with LH/RH handedness splits applied per `players_current.bats` (bats=L → LH PF, R → RH PF, S → 60/40 blend per Tango); modern save 2026-2029 falls through to `parks.avg` (engine doesn't carry handedness for save years).
- **Statcast EV scale runs ~5 mph below real Statcast.** OOTP league-avg EV ~83 mph vs real ~88-89; save's top-end avg-EV stars sit ~5-7 mph below their real counterparts. HARD_HIT_PCT scales proportionally lower (save Judge 34% vs real Judge ~65%). When `f_record_player` UNIONs save EV records with `history_statcast_*`, the source column distinguishes the two scales — don't compare them numerically without converting.
- **`max_ev` in `f_player_season_statcast_batting/_pitching` is the 90th-percentile EV**, not the absolute peak — Statcast convention; absolute peak is dominated by single-event noise.
- **`players_pitching.csv` is in the dump but not in L0.** All rating columns are zeroed in this save because scouting mode is enabled. Defensive ingest fix only; no actionable data lost. See DATA_NOTES.md "players_pitching.csv" section.
- `audit_output/` is gitignored. Reports are regenerable from CLI; commit the *generators*, not the outputs.
- `.env` exists locally and is gitignored — GitHub push protection has blocked it before. Don't `git add -A` blindly.
- `docs/screenshots/` is gitignored — user-local context, not part of the repo's permanent record.
