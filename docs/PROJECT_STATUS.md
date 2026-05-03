# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-02 (in-game year 2029)

---

## One-line summary

Diamond is in **audit phase** — we're confirming what data we can reliably
extract from OOTP monthly dumps before designing the warehouse schema and
building the ingest pipeline.

## What works today

- **Project skeleton**: Python 3.14 + DuckDB + Polars + Typer, package at `src/diamond/`, editable install via `pip install -e .[dev]`
- **CLI commands**: `diamond decode`, `diamond reconcile`, `diamond coverage`
- **Codebook decoder** ([src/diamond/audit/decode.py](src/diamond/audit/decode.py)) — empirically discovers OOTP integer-code meanings. Verified codebooks live in [src/diamond/constants.py](src/diamond/constants.py):
  - `GameType` (REGULAR_SEASON, SPRING, POSTSEASON, etc.)
  - `SplitId` (OVERALL, VS_LHP, VS_RHP, POSTSEASON)
  - `AtBatResult` (STRIKEOUT, WALK, GROUND_OUT, FLY_OUT, 1B, 2B, 3B, HR, HBP, CI) — verified by exact aggregate match (events sum to total PA)
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py)) — per-column comparison of `import_export` Red Sox roster CSVs against derivations from monthly dump CSVs. **90 of 97 columns reconcile (93%)** across 5 of 21 files.
- **Coverage audit** ([src/diamond/audit/coverage.py](src/diamond/audit/coverage.py)) — profiles dump CSVs supporting 11 user-facing features (standings, playoffs, awards, leaders, streaks, HOF, movements, records, all-stars, league history, injuries).

## Most-recent change

Built the coverage audit; confirmed all listed features are well-supported by direct dump tables. Found three new integer codebooks pending decoding (`award_id`, `players_league_leader.category`, `players_streak.streak_id`).

## Reconciliation status (most recent run)

Files audited: 5 of 21 (`batting_stats_1`, `batting_stats_2`, `pitching_stats_1`, `fielding_stats`, `batting_ratings`).

| File | Match | Notes |
|---|---|---|
| `batting_stats_1` | 23/24 | only `OPS+` outstanding (needs league constants) |
| `batting_stats_2` | 15/18 | RC, RC/27, wOBA need league constants |
| `pitching_stats_1` | 23/25 | ERA+, FIP need league constants |
| `fielding_stats` | 12/12 | **perfect** |
| `batting_ratings` | 17/18 | all 16 batting skill ratings 100% on 20-80 scale; only DEF formula outstanding |

Latest reports: [audit_output/reconciliation_report.md](audit_output/reconciliation_report.md), [audit_output/coverage_report.md](audit_output/coverage_report.md), [audit_output/decoder_report.md](audit_output/decoder_report.md).

## What's most likely next

Pick one of:
1. Decode the three pending codebooks (`award_id`, `category`, `streak_id`) — same empirical approach as before; quick.
2. Build the **league constants** module (linear weights, FIP constant, lgERA, park factors per league-year) — unlocks the 6 C-tier holdouts AND the Tier 3 advanced stats.
3. Finish reconciliation of the remaining 16 `import_export` files — mechanical now that the framework exists.
4. Investigate the DEF rating formula (last G-tier outstanding).

See [BACKLOG.md](BACKLOG.md) for the full list.
