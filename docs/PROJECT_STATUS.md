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
- **CLI commands**: `diamond decode`, `diamond reconcile`, `diamond coverage`, `diamond advanced`
- **Codebook decoder** ([src/diamond/audit/decode.py](src/diamond/audit/decode.py)) — empirically discovers OOTP integer-code meanings. Verified codebooks live in [src/diamond/constants.py](src/diamond/constants.py):
  - `GameType` (REGULAR_SEASON, SPRING, POSTSEASON, etc.)
  - `SplitId` (OVERALL, VS_LHP, VS_RHP, POSTSEASON)
  - `AtBatResult` (STRIKEOUT, WALK, GROUND_OUT, FLY_OUT, 1B, 2B, 3B, HR, HBP, CI) — verified by exact aggregate match (events sum to total PA)
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py)) — per-column comparison of `import_export` Red Sox roster CSVs against derivations from monthly dump CSVs. **90 of 97 columns reconcile (93%)** across 5 of 21 files.
- **Coverage audit** ([src/diamond/audit/coverage.py](src/diamond/audit/coverage.py)) — profiles dump CSVs supporting 11 user-facing features.
- **Advanced stats library** ([src/diamond/advanced/](src/diamond/advanced/)) — 5 tiers of modern advanced stats from at-bat data (~25 metrics):
  - `league_constants.py` — per-league-year linear weights, FIP const, lgERA (verified against real MLB norms)
  - `enriched.py` — reusable at-bat view with bip/risp/late-close/spray flags
  - `contact.py` — Tier 1: HardHit% buckets, SweetSpot%, Barrel% (Statcast formula), Squared%, EV by GB/LD/FB, Pull/Cent/Oppo, pitcher contact-quality allowed
  - `situational.py` — Tier 2: empirically-derived RE matrix, RE24 exposure, RISP/2-out/loaded splits, pinch/late-close, by-inning, leverage tiers, vs-pitcher H2H
  - `sabermetric.py` — Tier 3: wOBA, wRAA, wRC, wRC+, OPS+, ERA+, FIP, Power-Speed, Speed Score, isoP/isoD
  - `defensive.py` — Tier 4: RF/9, RF/G, Catcher Framing+, OF Assist Rate
  - `approach.py` — Tier 5: 2-strike performance, count-state splits, 4-pitch BB%, 3-pitch K%

## Most-recent change

Shipped the modern advanced stats library — all 5 tiers, derived from 1.2M at-bat events. League constants and Run Expectancy matrix derived empirically from this save's data. Headline players reconcile to expected real-MLB profiles (e.g., Aaron Judge, Cal Raleigh leading Barrel%).

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
1. **Decode the three pending codebooks** (`award_id`, `category`, `streak_id`) — same empirical approach as before; quick.
2. **Finish reconciliation of remaining 16 `import_export` files** — mechanical now.
3. **Add park factor integration** to OPS+/ERA+ (currently park-neutral). Park data already in `parks.csv` (avg, hr, etc.).
4. **Custom WAR** — combines wRAA + dWAR vs replacement-level baseline. Needs replacement-level definition.
5. **Move to schema & ingest phase** — design the L0-L4 warehouse layers and build the monthly-dump ingest pipeline. We have enough proof now that derivations work.

See [BACKLOG.md](BACKLOG.md) for the full list.
