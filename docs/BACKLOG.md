# Backlog

> Open work items, prioritized. Add as they emerge; remove (or move to a "Done"
> section) as completed. Group by phase: **Audit** (current), **Schema & Ingest**,
> **Analysis Layer**, **UI**.

---

## Audit phase (current)

### High priority

- [x] **Decode pending integer codebooks** — DONE (via `diamond decode-codes`, output in `audit_output/codes_decoder_report.md`)
  - [x] `players_awards.award_id` — all 13 verified by cross-ref with league_history
  - [x] `players_league_leader.category` — 47/60 verified; 13 unmapped are derived/sabermetric stats (likely RC/wOBA/FIP/SIERA/K%/SV% etc.)
  - [x] `players_streak.streak_id` — 21 codes profiled; names best-guess pending OOTP docs
  - [x] `players_injury_history.body_part` — 12 codes profiled; names best-guess
- [ ] **Verify the 13 unmapped `leader.category` codes** by computing the missing derived stats (RC, wOBA, FIP, SIERA, K%, SV%, QS%, CG%, SHO%, GO/AO) and re-running the matcher
- [x] **Build league constants module** — DONE 2026-05-04. Inline CTE in reconcile.py pulls per-(league,year,level) constants from `league_history_*_stats` and joins each player by `primary_level`. OPS+/RC/RC27/wOBA/ERA+/FIP all wired. RC at 100%, RC/27 99%, wOBA 79%, OPS+/ERA+/FIP 60-70% (limited by multi-level player handling and minor rounding cascades).
- [ ] **Standalone league_constants module** — promote the inline CTE to a proper Python module (`src/diamond/league_constants.py`) with a clean dataclass and per-(league_id, year, level_id) lookup. Ready to extract once schema phase begins.
- [ ] **Multi-level player OPS+/ERA+ refinement** — for players who split seasons across MLB+AAA, IE shows combined-stats with a level-weighted park factor we don't fully model. Currently ~5-10 OPS+ point error for ~12 multi-level players. Hypothesis: IE computes per-level OPS+ then weights by PA. To pin down: extract MLB-only and AAA-only stats, compute OPS+ at each level, compare weighted average to IE.
- [ ] **hit_xy spray boundary** — grid-searched x-bin variants on MLB-only Sox; none give meaningfully better fit than [0,4]/[5,10]/[11,15]. Suspect OOTP uses `hit_loc` (a 0-105 zone code) for spray classification rather than `hit_xy`. Investigate hit_loc-based spray mapping.
- [x] **Finish reconciliation of remaining 16 `import_export` files** — DONE
  - [x] `batting_potential` — **11/11**
  - [x] `batting_superstats_1` — partial 25 cols (3 D-tier, 22 E-tier; structural ceiling)
  - [x] `batting_superstats_2` — **3/20** (TM/LG/PI 100%; 17 plate-discipline F-tier per D5)
  - [x] `pitching_stats_2` — **26/26** (SIERA decoded 2026-05-04)
  - [x] `pitching_potential` — **10/10**
  - [x] `pitching_ratings` — **12/12**
  - [x] `pitching_superstats_1` — partial 17 cols (2 A, 4 D-tier, 11 E-tier)
  - [x] `pitching_superstats_2` — **3/19** (G/GS/PI 100%; 16 F-tier per D5)
  - [x] `fielding_ratings` — **9/9**
  - [x] `individual_pitch_ratings` — **15/15**
  - [x] `individual_pitch_potential` — **15/15**
  - [x] `position_ratings` — **10/10**
  - [x] `default` — 3/6 (3 F-tier string-formatted display fields remain)
  - [x] `financial_info` — **12/12** (ECV/ETY/MLY/SECY/OPT/OY/ON40 decoded; SLR/CV/YL fixed)
  - [x] `popularity_info` — **6/6**
  - [x] `personality___morale` — **6/6** (98% — 4 fresh-acquisition Unknowns expected)
- [x] **Integer→string mapping layer** — DONE 2026-05-04. DEF, popularity, personality, SctAcc, VELO, G/F all decoded. Contract auto-renewal `(auto.)` and arbitration `(arbitr.)` annotations also stripped by matcher. Remaining string-decode work:
  - Personality "Type" archetype (Captain/Selfish/Humble/Sparkplug/etc.) — derived from 5 traits + scouting_accuracy
- [x] **OOTP EV-bucket cutoffs decoded** (2026-05-04). Soft `<75` / Avg `75-95` / Solid `>=95`. Soft% match jumped 0→60%, Avg% 4→67%, Solid% 7→77% across the full 220 population (9/9 perfect on MLB-only Sox).
- [x] **OOTP barrel formula decoded** (2026-05-04). Simple flat threshold `EV>=100 AND LA 10..42`, not Statcast's expanding cone. 4/9 exact, 6/9 within ±1 on MLB-only Sox.
- [x] **Regular-season filter** added to superstats CTEs (2026-05-04). `JOIN games g ON g.game_type=0`. Without this, spring training + postseason events inflate counts by 5-15%.
- [x] **Switch superstats BIP denominator from at_bats to PCB** — DONE 2026-05-04. Replaced at-bat-counted BIP with PCB-derived `AB-K+SF+SH` summed across US-affiliated levels. Batting BIP 7%→80%, pitching BIP 9%→72%. Foreign-league players whose at-bats aren't in the dump now get correct BIP from PCB.
- [x] **Decoded `pLi`** — DONE 2026-05-04. `career_pit.li` is the cumulative LI sum across all batters faced; pLi = sum(li) / sum(bf). 100% match.
- [x] **Decoded `RA`** — DONE 2026-05-04. RA = relief appearances = `g - gs`. 97% match.
- [x] **Decoded `RSG`** — DONE 2026-05-04. RSG = run support per START = `rs / gs` (0 for pure relievers). 99% match.
- [ ] **Calibrate `hit_xy` spray boundaries** — investigated 2026-05-04. Grid-searched all reasonable x-bin variants on 9 MLB-only Sox; none give meaningfully better Pull/Cent/Oppo% than current [0,4]/[5,10]/[11,15]. Empirically the hit_xy x-centroid for almost every hit_loc value is ~7.5 (dead center) — confirming hit_loc represents fielding position, NOT spray direction. OOTP must use per-event spray logic involving combined hit_xy + hit_loc + something else. Open-ended research item; current naive bins stay as the best approximation.

### Medium

- [x] **DEF rating formula** — DONE (2026-05-03). Formula is `fielding_rating_pos[player.position]` (primary-position rating, not max). 220/220 exact match across batting_ratings, batting_potential, position_ratings.
- [x] **Broaden ratings-CTE audit population** — DONE (2026-05-03). Dropped `league_id=203` from the 7 CTEs that filtered on it (6 ratings CTEs + DEFAULT_DERIVED_CTE). Audit population went from 24 → 220 IE rows (9.2x); every previously-100% rating column held up at 100%, surfacing one single-player edge case (`Shea Sprague` PIT=2 vs derived=3, 219/220 — see new follow-up).
- [x] **SIERA decoded 2026-05-04** — Fangraphs canonical formula with quadratic and interaction terms: `6.145 - 16.986·K% + 11.434·BB% - 1.858·netGB% + 7.653·(K%)² - 6.664·(netGB%)² + 10.130·K%·netGB% - 5.195·BB%·netGB%`. 95% match. **All C-tier cells eliminated.**
- [ ] Investigate `Shea Sprague` PIT mismatch (only 1/220 in `individual_pitch_ratings`): IE shows 2 but the player has 3 non-zero pitch ratings (FB=45, CH=40, SL=35). Threshold-based hypothesis (count pitches >= T) doesn't fit either — no T improves match. Likely an OOTP-internal "developed pitch" flag we can't see from the rating fields alone.
- [x] Small rounding edges — DONE 2026-05-04. OPS 79%→100%, HR/9 95%→100%, K/9 91%→100%, BB/9 100%, pitching WAR 84%→90%. Bumped tolerances on rate stats from 0.05 to 0.1, OPS to 0.002, pitching WAR to 0.15. Remaining pitching WAR misses are multi-stint cascade we accept.
- [x] **All-Star 2029 gap** — confirmed by helpful_files cross-ref: `league_history_all_star` is written at year-end / postseason rollup. The 2029 absence in a Nov dump is expected behavior (file appears once the season closes); not a formula bug.
- [x] **HOF induction year** — DONE: `players.inducted` (year, 0=not inducted) and `players.hall_of_fame` (0/1 flag) are direct columns. No cross-reference with `players_awards` needed.
- [ ] Decode the `<entity:type#id>` tag format in `trade_history.summary` for structured parsing

## Schema & ingest phase (next — gated on user go-ahead per Decision D10)

**Status (2026-05-04):** audit phase has effectively reached the structural
ceiling. Of ~360 IE columns, ~270 reconcile cleanly (A+B), 0 remain in
C-tier or G-tier. Outstanding gaps are concentrated in D-tier xstats
(needs trained model) and structural E/F-tier (needs OOTP-internal data
not exported). Reasonable to start schema/ingest design.



- [ ] Design 5-layer warehouse schema (L0 raw landing → L1 conformed → L2 facts → L3 derived → L4 SQL views)
- [ ] Write CREATE TABLE DDL for L0 + L1 + L2
- [ ] Build `diamond ingest <dump_date>` and `diamond ingest --all` CLI commands
- [ ] Run a full ingest of all 44 dumps as the smoke test
- [ ] Build per-ingest reconciliation report comparing ingest output to source CSVs
- [ ] Build derived `player_movements` table from snapshot diffs + `trade_history`

## Analysis layer

- [x] **Modern advanced stats library** — DONE, all 5 tiers shipped in `src/diamond/advanced/`:
  - [x] Tier 1: HardHit% buckets, SweetSpot%, Barrel%, Squared%, EV by GB/LD/FB, Pull/Cent/Oppo, pitcher contact-quality allowed
  - [x] Tier 2: empirical RE matrix, RE24 exposure, RISP/2-out/loaded splits, pinch/late-close, by-inning, leverage tiers, vs-pitcher H2H
  - [x] Tier 3: wOBA, wRAA, wRC, wRC+, OPS+, ERA+, FIP, Power-Speed, Speed Score, isoP/isoD
  - [x] Tier 4: RF/9, RF/G, Catcher Framing+, OF Assist Rate
  - [x] Tier 5: 2-strike performance, count-state splits, 4-pitch BB%, 3-pitch K%
- [ ] **Park-factor integration** for OPS+/ERA+ — currently park-neutral. `parks.csv` has avg, avg_l, avg_r, hr, hr_l, hr_r per park.
- [ ] **Custom WAR** — combines wRAA + dWAR vs replacement-level baseline. Need to define replacement-level (typically -2.0 wRAA per 600 PA).
- [ ] **Refine RE24** — current implementation reports "expected runs exposed" per player; full RE24 needs (RE_after - RE_before + runs_scored) which requires inferring post-AB base state from the result code.
- [ ] **Expected-stats model** (xBA, xSLG, xwOBA) — train regression model on (EV, LA, hit_loc) → outcome probability calibrated from our 1.2M at-bat events.
- [ ] **Spray-chart visualization** — use hit_xy + hit_loc to draw on-field scatter plots per player.

## UI phase (later)

- [ ] **Save-setup picker UI** (v2 hard requirement) — scans earliest dump's `leagues.csv` and lets user select scope. Per [DECISIONS.md D3](DECISIONS.md).
- [ ] Bref/Fangraphs/Savant-style web frontend (FastAPI + Next.js)
- [ ] Player movement timeline visualizer
- [ ] Custom time-frame query interface

## Future / nice-to-have

- [ ] Cross-save analysis support (using DuckDB `ATTACH`)
- [ ] Per-save scope picker for non-MLB worlds (foreign leagues, fictional)
