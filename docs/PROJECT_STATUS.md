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
- **CLI commands**: `diamond decode`, `diamond decode-codes`, `diamond reconcile`, `diamond coverage`, `diamond advanced`
- **Codebook decoder** ([src/diamond/audit/decode.py](src/diamond/audit/decode.py) + [decode_codes.py](src/diamond/audit/decode_codes.py)) — empirically discovers OOTP integer-code meanings. Verified codebooks live in [src/diamond/constants.py](src/diamond/constants.py):
  - **First pass** (at-bat domain): `GameType`, `SplitId`, `AtBatResult` — all verified by exact aggregate match
  - **Second pass** (awards/leaders/streaks/injuries): `AwardId` (13 codes, cross-ref'd with league_history), `LeaderCategory` (47 of 60 cleanly matched), `StreakId` (21 codes profiled), `BodyPart` (12 codes profiled)
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py)) — per-column comparison of `import_export` Red Sox roster CSVs against derivations from monthly dump CSVs. **90 of 97 columns reconcile (93%)** across 5 of 21 files.
- **Coverage audit** ([src/diamond/audit/coverage.py](src/diamond/audit/coverage.py)) — profiles dump CSVs supporting 11 user-facing features (standings, playoffs, awards, leaders, streaks, HOF, movements, records, all-stars, league history, injuries).
- **Advanced stats library** ([src/diamond/advanced/](src/diamond/advanced/)) — 5 tiers of modern advanced stats from at-bat data (~25 metrics):
  - `league_constants.py` — per-league-year linear weights, FIP const, lgERA (verified against real MLB norms)
  - `enriched.py` — reusable at-bat view with bip/risp/late-close/spray flags
  - `contact.py` — Tier 1: HardHit% buckets, SweetSpot%, Barrel% (Statcast formula), Squared%, EV by GB/LD/FB, Pull/Cent/Oppo, pitcher contact-quality allowed
  - `situational.py` — Tier 2: empirically-derived RE matrix, RE24 exposure, RISP/2-out/loaded splits, pinch/late-close, by-inning, leverage tiers, vs-pitcher H2H
  - `sabermetric.py` — Tier 3: wOBA, wRAA, wRC, wRC+, OPS+, ERA+, FIP, Power-Speed, Speed Score, isoP/isoD
  - `defensive.py` — Tier 4: RF/9, RF/G, Catcher Framing+, OF Assist Rate
  - `approach.py` — Tier 5: 2-strike performance, count-state splits, 4-pitch BB%, 3-pitch K%

## Most-recent change

Decoded the four pending integer codebooks. `award_id` (all 13 verified), `leader.category` (47/60 verified — remaining 13 are derived sabermetric stats), `streak_id` (21 profiled), `body_part` (12 profiled). All added to `src/diamond/constants.py` as IntEnums. `audit_output/codes_decoder_report.md` has full details.

## Reconciliation status (most recent run)

Files audited: 5 of 21 (`batting_stats_1`, `batting_stats_2`, `pitching_stats_1`, `fielding_stats`, `batting_ratings`).

| File | Match | Notes |
|---|---|---|
| `batting_stats_1` | 23/24 | only `OPS+` outstanding (needs league constants) |
| `batting_stats_2` | 15/18 | RC, RC/27, wOBA need league constants |
| `pitching_stats_1` | 23/25 | ERA+, FIP need league constants |
| `fielding_stats` | 12/12 | **perfect** |
| `batting_ratings` | 17/18 | all 16 batting skill ratings 100% on 20-80 scale; only DEF formula outstanding |

Latest reports (audit_output/ — gitignored, regenerate with the CLI commands):
- [decoder_report.md](audit_output/decoder_report.md) — `diamond decode`
- [codes_decoder_report.md](audit_output/codes_decoder_report.md) — `diamond decode-codes`
- [reconciliation_report.md](audit_output/reconciliation_report.md) — `diamond reconcile`
- [coverage_report.md](audit_output/coverage_report.md) — `diamond coverage`
- [advanced_stats_report.md](audit_output/advanced_stats_report.md) — `diamond advanced`

## What's next (per user direction)

User has chosen to **finish the audit phase before any schema/ingest design**.
Audit completion order from [BACKLOG.md](BACKLOG.md):

1. **NEXT**: Reconcile the remaining **16 `import_export` files** — mechanical now that the framework exists. Will surface remaining quirks (potential ratings, individual pitch types, position ratings, financial info, popularity, personality/morale).
2. Investigate the **DEF rating formula** (last G-tier hole)
3. Resolve small rounding edges (OPS 79%, HR/9 95%, K/9 91%, pitching WAR 84%) — confirm not derivation bugs
4. Investigate the **All-Star 2029 gap** + verify HOF induction year via awards
5. Decode `<entity:type#id>` tags in `trade_history.summary` for structured movement parsing
6. Bonus: verify the 13 unmapped `LeaderCategory` codes by computing the missing sabermetric stats (RC, wOBA, FIP, SIERA, K%, SV%, QS%, CG%, SHO%, GO/AO) and re-running the matcher

After full reconciliation: schema design + ingest pipeline (per the L0-L4 layers sketch from earlier sessions).
