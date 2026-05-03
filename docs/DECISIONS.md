# Decisions Log

> Architectural, scope, and design decisions with their rationale. Append-only
> history — when a decision is reversed, add a new entry rather than editing
> the old one. Each entry: **date**, **decision**, **why**, **alternatives
> considered**.

---

## D1 — Stack: Python 3.14 + DuckDB + Polars + Typer

**Date**: 2026-05-02
**Decision**: Build Diamond on Python 3 with DuckDB as the warehouse engine, Polars for ingest, Typer for the CLI, Rich for console output.
**Why**: DuckDB handles 100MB CSVs and 5M+ at-bats trivially, gives us SQL natively, runs as a single file portable across machines, and supports `ATTACH` for cross-save analysis later. Polars is fast on the ingest hot path. Typer + Rich give us an ergonomic CLI without web infrastructure overhead.
**Alternatives considered**: Postgres + SQLAlchemy (too much overhead for v1; can layer later if a multi-user web UI becomes needed). SQLite (DuckDB is purpose-built for OLAP/analytics workloads on this data shape).

## D2 — One DuckDB per OOTP save (not a shared multi-save DB)

**Date**: 2026-05-02
**Decision**: Each OOTP save gets its own DuckDB file in `<save>/diamond/diamond.duckdb`, alongside the `dump/` and `import_export/` folders OOTP itself writes.
**Why**: Clean isolation, no `save_id` FK pollution everywhere, each save is fully portable. Cross-save analysis still works via DuckDB's `ATTACH`.
**Alternatives considered**: Single shared DB with `save_id` on every table.

## D3 — Strict league scope for v1, with save-setup picker as a hard v2 requirement

**Date**: 2026-05-02
**Decision**: For "Building the Green Monster" (v1), hardcode scope to MLB + affiliated minors + DSL + AFL (15 league_ids). v2 must include a save-setup UI that scans the earliest dump's `leagues.csv` and lets the user pick.
**Why**: User's current focus is the Red Sox franchise — strict scope cuts ingest volume dramatically (10-20K relevant players vs 148K world). Future saves may include foreign leagues / KBO / indy / fictional leagues, so the scoping mechanism must be configurable, not hardcoded.
**Alternatives considered**: World-wide ingest with query-time filtering (more flexible but ~10× the storage and more I/O on every analysis).

## D4 — Strict player scope (configurable per save)

**Date**: 2026-05-02
**Decision**: Only ingest players who appear in scoped leagues. Once in scope, stay in scope through retirement (so we don't lose franchise narrative if a Red Sox prospect later signs in KBO).
**Why**: Avoids ingesting stats for 148K world-wide players when most are irrelevant. Keeping in-scope-once players forever preserves storyline continuity.
**Alternatives considered**: World-bio-only mode (ingest all player bios, only stats for scoped players) — kept as a future option.

## D5 — Skip plate-discipline metrics (Z%, SW%, RV-*)

**Date**: 2026-05-02
**Decision**: Don't attempt to replicate Z%, SW%, ZC%, OC%, ZS%, OS%, CL%, WH%, CH%, CTC%, FF%, BR%, OFF%, RV-FB, RV-BR, RV-OFF, RV from the import_export files.
**Why**: These need per-pitch zone/type data that OOTP never exports. Only the per-PA terminal `balls`/`strikes` count is in the dump. Approximation would be lossy and misleading.
**Alternatives considered**: Pull from `import_export` when the user generates it for their own org (Red Sox-only at present), null elsewhere — rejected for simplicity in v1.

## D6 — Player ratings on the 20-80 scouting scale

**Date**: 2026-05-02
**Decision**: All player ratings and potentials surfaced in our app are on the 20-80 scale.
**Why**: User preference; matches Baseball America / Fangraphs convention.
**How to apply**: For skill ratings (CON, GAP, POW, EYE, etc.), the dump's `players_scouted_ratings` columns are already on 20-80 — pass through directly. For OVR/POT, use `overall_rating` / `talent_rating` (already 20-80) — NOT `overall` / `talent` (which are on a 0-200 internal scale).

## D7 — Granular at-bat data as primary source for stat derivations

**Date**: 2026-05-02
**Decision**: Where possible, derive stats from `players_at_bat_batting_stats.csv` (per-PA event log) rather than from career-stats season rollups.
**Why**: Enables custom time-frame queries ("last 12 games", "last 45 games", "RISP performance over the last month") and any situational split a user wants. Career-stats become a validation target, not the primary source.
**How to apply**: Capture at-bat data from the `dump_YYYY_11` end-of-season snapshot (the file rolls over at season start in Feb-Mar). For multi-year analysis, stitch together the November dumps from each year.

## D8 — Reconciliation harness as a permanent codebase fixture

**Date**: 2026-05-02
**Decision**: Keep `src/diamond/audit/reconcile.py` permanently — run it after every monthly ingest as a regression check.
**Why**: Without continuous reconciliation against the OOTP-generated `import_export` files, derivation drift would be silent. Every column we derive must have a corresponding view that ties back to OOTP's own numbers.
**Alternatives considered**: Throwaway audit script — rejected because we need ongoing regression coverage.

## D9 — Persistent docs/ logs replace session-scoped TodoWrite

**Date**: 2026-05-02
**Decision**: Project context lives in `docs/PROJECT_STATUS.md`, `docs/DECISIONS.md`, `docs/DATA_NOTES.md`, `docs/BACKLOG.md`. These are committed to the repo and updated as work progresses.
**Why**: TodoWrite is session-scoped and not visible to the user. Long-running engineering project across many sessions needs a persistent, version-controlled record of state, decisions, and discoveries.
**How to apply**: Read PROJECT_STATUS at session start. Append to DECISIONS / DATA_NOTES as new ones emerge. Keep BACKLOG current.

## D10 — Audit-first: complete reconciliation before any schema/ingest design

**Date**: 2026-05-02
**Decision**: Finish the full audit phase (all 21 import_export files reconciled, all integer codebooks decoded, all data quirks documented) BEFORE designing the warehouse schema or building the ingest pipeline. No schema/DDL work begins until reconciliation is comprehensive.
**Why**: User explicit instruction — "Let's make sure that the data scope is crystal clear and we have everything reconciled before we start building anything including schema." Schema decisions baked in before reconciliation can lock in the wrong assumptions; the cost of a redesign once tables exist (and contain data from 44 monthly dumps) is much higher than finishing the audit.
**How to apply**: Resist the temptation to start schema work even when "we have enough proof now that derivations work." Direct any schema design ideas to BACKLOG instead. Continue audit work in priority order: reconcile remaining 16 import_export files → DEF formula → rounding edges → AS gap → trade summary parsing.

## D11 — League constants: per-league per-level, no AL/NL split, separate per international league

**Date**: 2026-05-04
**Decision**: League constants for sabermetric stats (wRC+, wRAA, FIP, OPS+, ERA+, etc.) are keyed on `(league_id, year, level_id)`. Within US MLB, AL and NL are aggregated into a single MLB row (no split). International leagues at the same nominal level (NPB, KBO, KFL at MLB-equivalent level) live in their own constants universes and are never aggregated with US MLB. Cross-level aggregation for a single player is never done — a player who splits a season between MLB and AAA shows two stat lines (one per level), each with sabermetrics computed against that level's constants. Only pure counting stats (career HR, total IP) can be summed across levels for rollups.
**Why**: Mimics modern public-stats convention (Fangraphs, Baseball Reference for the modern era): one MLB-wide league baseline, level-specific context for non-MLB players, and per-league-line stats for cross-level players. Empirically verified the AL/NL choice is a no-op in this save (universal DH since 2022 → AL OBP=.3155 vs NL OBP=.3151, OPS+ comes out identical to the integer either way), so we take the simpler/cleaner unified-MLB convention. Treating international leagues as separate universes prevents nonsensical comparisons (a Hanshin Tigers player's wRC+ being compared to Aaron Judge's).
**How to apply**:
- The `league_constants` table is keyed `(league_id, year, level_id)`. For OOTP MLB (`league_id=203`), aggregate across the per-sub_league rows (the dump stores AL and NL as separate rows with `team_id=12` and `team_id=25` respectively in `league_history_*_stats`).
- For NPB / KBO / KFL etc., each `league_id` keeps its own constants — no cross-league aggregation.
- Sabermetric derivations join `players_career_*_stats` to `league_constants` on `(level_id, year)` per row (and league_id for international), so a player's MLB rows use MLB constants and his AAA rows use AAA constants automatically.
- Career rollups across levels are restricted to pure counts (HR, IP, games). Rate-context stats (wRC+, ERA+, etc.) are reported per-level only.
- MLB-equivalent translations (e.g., AAA→MLB conversion factors à la KATOH/Davenport) are explicitly **out of scope** for the constants module — they're a separate analysis-layer transformation that consumers can apply if desired.
**Alternatives considered**:
- AL/NL split per BBR convention — rejected because empirically no-op in this save and adds complexity without precision gain.
- Aggregate international leagues with US-MLB at the same level_id — rejected because the run environments are unrelated; would distort everyone.
- Compute one season-aggregate sabermetric across a player's mixed-level rows — rejected because the underlying scales differ between levels (AAA wOBA scale ≠ MLB wOBA scale), making the aggregate statistically meaningless.
