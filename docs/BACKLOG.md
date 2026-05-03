# Backlog

> Open work items, prioritized. Add as they emerge; remove (or move to a "Done"
> section) as completed. Group by phase: **Audit** (current), **Schema & Ingest**,
> **Analysis Layer**, **UI**.

---

## Audit phase (current)

### High priority

- [ ] **Decode pending integer codebooks** — same empirical approach as the result/split decoder
  - [ ] `players_awards.award_id` (13 values: MVP, CY, RoY, MoY, GG, SS, AS, HOF, etc.)
  - [ ] `players_league_leader.category` (60 values: HR, AVG, K, ERA, etc.)
  - [ ] `players_streak.streak_id` (21 values: hit, OB, HR, K, GP, etc.)
  - [ ] `players_injury_history.body_part` (integer)
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

- [ ] Build the **modern advanced stats library** (see DATA_NOTES.md "Tier 1-5"):
  - Tier 1: Hard Hit %, Sweet Spot %, Barrel %, Squared-up % (custom EV/LA cutoffs)
  - Tier 2: RE24, situational splits, leverage tiers, performance vs specific pitchers (the killer-app tier)
  - Tier 3: wRC, wRC+, wRAA, custom WAR (needs league constants)
  - Tier 4: Range Factor, Catcher Framing+, OF Assist Rate
  - Tier 5: 2-strike BA, even-count vs behind-in-count splits (limited but useful)
- [ ] Build expected-stats model (xBA, xSLG, xwOBA) calibrated from at-bat data

## UI phase (later)

- [ ] **Save-setup picker UI** (v2 hard requirement) — scans earliest dump's `leagues.csv` and lets user select scope. Per [DECISIONS.md D3](DECISIONS.md).
- [ ] Bref/Fangraphs/Savant-style web frontend (FastAPI + Next.js)
- [ ] Player movement timeline visualizer
- [ ] Custom time-frame query interface

## Future / nice-to-have

- [ ] Cross-save analysis support (using DuckDB `ATTACH`)
- [ ] Per-save scope picker for non-MLB worlds (foreign leagues, fictional)
