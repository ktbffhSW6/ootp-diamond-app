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
- [ ] **Build league constants module** — `league_constants` table, computed from `league_history_*` totals + park factors from `parks.csv`. Per league-year:
  - linear weights (wOBA, wRAA, wRC, wRC+)
  - FIP constant (cFIP)
  - lgERA, lgOPS (for ERA+/OPS+)
  - park factors (avg, hr, etc.)
  - Bill James RC factor
  - Unlocks the 6 C-tier reconciliation holdouts AND Tier 3 advanced stats.
- [ ] **Finish reconciliation of remaining 16 `import_export` files**:
  - [ ] `batting_potential`
  - [ ] `batting_superstats_1` (Statcast — EV, LA, BAR, xBA/xSLG/xwOBA)
  - [ ] `batting_superstats_2` (mostly F-tier — plate discipline)
  - [ ] `pitching_stats_2`
  - [ ] `pitching_potential`
  - [ ] `pitching_ratings`
  - [ ] `pitching_superstats_1`
  - [ ] `pitching_superstats_2`
  - [ ] `fielding_ratings`
  - [ ] `individual_pitch_ratings`
  - [ ] `individual_pitch_potential`
  - [ ] `position_ratings`
  - [ ] `default` (roster overview)
  - [ ] `financial_info`
  - [ ] `popularity_info`
  - [ ] `personality___morale`

### Medium

- [ ] Investigate the **DEF rating formula** in `batting_ratings` (only 29% match with `MAX(fielding_rating_pos2..9)`)
- [ ] Investigate small rounding edge cases:
  - [ ] OPS at 79% match (OBP+SLG sum precision)
  - [ ] HR/9, K/9 at 91-95% (likely IP convention difference: true innings vs displayed `172.1`)
  - [ ] Pitching WAR at 84% (only 16 mismatches — likely multi-org players)
- [ ] Investigate why **`league_history_all_star`** has no 2029 entries
- [ ] Verify HOF induction year is recoverable through `players_awards` (cross-reference with `players.inducted`)
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
