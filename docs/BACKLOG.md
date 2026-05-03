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
- [ ] **Build league constants module** — *simpler than originally scoped*: `league_history_batting_stats` ships with **wOBA, RC, RC/27, ISO, OPS, BABIP, K%, BB%** pre-computed per league/year/level, and `league_history_pitching_stats` ships with **FIP, ERA, WHIP, WAR, RA9-WAR, K-BB%, H/9, K/9, BB/9, HR/9, KBB ratio** pre-computed. Park factors from `parks.csv`. So the module is mostly a *lookup* over league_history rows, not a recompute. Per league-year:
  - lgERA, lgOPS (for ERA+/OPS+) — direct from league_history
  - lgwOBA + linear-weights coefficients (for wRC+ scaling)
  - FIP constant (back out from league FIP value)
  - park factors (avg, hr, etc. — from `parks.csv`)
  - Unlocks the 6 C-tier reconciliation holdouts AND Tier 3 advanced stats.
- [x] **Finish reconciliation of remaining 16 `import_export` files** — DONE
  - [x] `batting_potential` — **11/11** (DEF decoded 2026-05-03)
  - [x] `batting_superstats_1` — 22/25 partial (E-tier, Statcast)
  - [x] `batting_superstats_2` — all F-tier per D5
  - [x] `pitching_stats_2` — 22/26 (RA/RSG/SIERA/pLi C-tier)
  - [x] `pitching_potential` — 8/10 (VELO + G/F G-tier)
  - [x] `pitching_ratings` — 10/12
  - [x] `pitching_superstats_1` — 13/17 partial (E-tier)
  - [x] `pitching_superstats_2` — all F-tier per D5
  - [x] `fielding_ratings` — 9/9 PERFECT
  - [x] `individual_pitch_ratings` — 14/15
  - [x] `individual_pitch_potential` — 14/15
  - [x] `position_ratings` — **10/10** (DEF decoded 2026-05-03)
  - [x] `default` — 3/6 (string-formatted display fields)
  - [x] `financial_info` — 2/12 (extension/option columns C-tier)
  - [x] `popularity_info` — **6/6** (Nat./Loc. Pop. + SctAcc decoded 2026-05-03)
  - [x] `personality___morale` — **6/6** (LEA/LOY/FIN/WE/INT bucketed 2026-05-03; 4 fresh-acquisition mismatches expected)
- [ ] **Build integer→string mapping layer** for remaining G-tier cells. DEF, popularity, personality, and SctAcc are all done as of 2026-05-03. Still outstanding:
  - VELO (1..N → "75-80 Mph", "80-85 Mph", ...) — pitching_ratings + pitching_potential + individual_pitch_*
  - G/F (1..N → "EX FB", "FB", "NTRL", "GB", "EX GB") — pitching_ratings/potential
  - Contract auto-renewal flag and dollar formatting (financial_info)
  - Personality "Type" archetype (Captain/Selfish/Humble/Sparkplug/etc.) — derived from 5 traits + scouting_accuracy
- [x] **OOTP EV-bucket cutoffs decoded** (2026-05-04). Soft `<75` / Avg `75-95` / Solid `>=95`. Soft% match jumped 0→60%, Avg% 4→67%, Solid% 7→77% across the full 220 population (9/9 perfect on MLB-only Sox).
- [x] **OOTP barrel formula decoded** (2026-05-04). Simple flat threshold `EV>=100 AND LA 10..42`, not Statcast's expanding cone. 4/9 exact, 6/9 within ±1 on MLB-only Sox.
- [x] **Regular-season filter** added to superstats CTEs (2026-05-04). `JOIN games g ON g.game_type=0`. Without this, spring training + postseason events inflate counts by 5-15%.
- [ ] **Switch superstats BIP denominator from at_bats to PCB** (`AB-K+SF+SH`). At_bats-derived BIP diverges from IE for minor-leaguers whose foreign-league data isn't in our scope. PCB-derived BIP matches IE exactly. Will lift BIP, BAR%, HHi%, Soft%, Avg%, Solid% for multi-level players.
- [ ] **Decode `pLi`** — career_pit.li doesn't behave as a sum/avg in any obvious way.
- [ ] **Decode `RA`** in pitching_stats_2 — small int, doesn't match raw `r` or per-9 RA.
- [ ] **Calibrate `hit_xy` spray boundaries** — basic decode landed 2026-05-03 (`x = floor(hit_xy/16)`, switch hitters use opposite of pitcher.throws). Naive bins (LF=[0,4]/CF=[5,10]/RF=[11,15]) under-count Pull% by ~5–10pp consistently. Either OOTP's x-bin boundaries are different, or `hit_loc` weighs into the spray classification. Investigate: for a known IE Pull% (e.g., Eric Coles 44.1%), grid-search x-boundaries to find the cut that matches, then cross-validate.

### Medium

- [x] **DEF rating formula** — DONE (2026-05-03). Formula is `fielding_rating_pos[player.position]` (primary-position rating, not max). 220/220 exact match across batting_ratings, batting_potential, position_ratings.
- [x] **Broaden ratings-CTE audit population** — DONE (2026-05-03). Dropped `league_id=203` from the 7 CTEs that filtered on it (6 ratings CTEs + DEFAULT_DERIVED_CTE). Audit population went from 24 → 220 IE rows (9.2x); every previously-100% rating column held up at 100%, surfacing one single-player edge case (`Shea Sprague` PIT=2 vs derived=3, 219/220 — see new follow-up).
- [ ] Investigate `Shea Sprague` PIT mismatch (only 1/220 in `individual_pitch_ratings`): IE shows 2 but the player has 3 non-zero pitch ratings (FB=45, CH=40, SL=35). Threshold-based hypothesis (count pitches >= T) doesn't fit either — no T improves match. Likely an OOTP-internal "developed pitch" flag we can't see from the rating fields alone.
- [ ] Investigate small rounding edge cases:
  - [ ] OPS at 79% match (OBP+SLG sum precision)
  - [ ] HR/9, K/9 at 91-95% (likely IP convention difference: true innings vs displayed `172.1`)
  - [ ] Pitching WAR at 84% (only 16 mismatches — likely multi-org players)
- [x] **All-Star 2029 gap** — confirmed by helpful_files cross-ref: `league_history_all_star` is written at year-end / postseason rollup. The 2029 absence in a Nov dump is expected behavior (file appears once the season closes); not a formula bug.
- [x] **HOF induction year** — DONE: `players.inducted` (year, 0=not inducted) and `players.hall_of_fame` (0/1 flag) are direct columns. No cross-reference with `players_awards` needed.
- [ ] Decode the `<entity:type#id>` tag format in `trade_history.summary` for structured parsing

## Schema & ingest phase (next)

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
