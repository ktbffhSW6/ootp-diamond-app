# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read these first

The project keeps long-running engineering context in `docs/`. Always read at the start of a session:

- `docs/PROJECT_STATUS.md` — current phase, what works, what was last done, what's next.
- `docs/DECISIONS.md` — append-only log of architectural/scope decisions with rationale (D1-D10).
- `docs/DATA_NOTES.md` — empirical findings about the OOTP dump shape, codebooks, and IE display conventions.
- `docs/BACKLOG.md` — prioritized open work, grouped by phase (Audit → Schema/Ingest → Analysis → UI).

These files are the source of truth for "why" — favor updating them over leaving knowledge in chat.

**Hard constraint (Decision D10):** the project is in *audit phase*. No warehouse-schema or ingest-pipeline work begins until reconciliation is comprehensive. If asked to design tables or write DDL, push back and route the request to `docs/BACKLOG.md` instead.

## Setup & commands

```bash
pip install -e ".[dev]"            # editable install + pytest/ruff
diamond --help                     # list CLI commands

diamond decode                     # discover at-bat domain integer codebooks
diamond decode-codes               # discover awards/leaders/streaks/injuries codebooks
diamond reconcile                  # per-column compare IE roster CSVs vs dump derivations
diamond coverage                   # profile dump CSVs that support each user-facing feature
diamond advanced                   # compute Tier 1-5 advanced stats from at-bat data
```

All commands write a markdown report to `audit_output/` (gitignored). Each takes `--dump <name>` (defaults to latest) and `--output <path>` overrides.

There is no test suite yet — `pyproject.toml` declares `pytest` but no `tests/` exists. When adding code, validate by running the relevant CLI command and reading its `audit_output/` report.

### Windows / editable install gotcha

Hatchling's editable install can fail to register `src/` on Windows. If `import diamond` fails after `pip install -e .`, manually create `.venv/Lib/site-packages/diamond.pth` containing the absolute path to `src/`. The CLI also force-reconfigures stdout/stderr to UTF-8 on Windows (`src/diamond/cli.py`) so Rich box-drawing characters render — don't remove that block.

## Architecture

### Two top-level modules

- **`src/diamond/audit/`** — discovery and verification tools that read CSVs from a single OOTP dump and produce markdown reports. They never mutate the dump or write to a warehouse.
  - `decode.py` / `decode_codes.py` — empirically reverse-engineer integer codebooks by matching aggregate counts to known totals (e.g., "sum of all `result` values per game = total PA"). Verified codebooks become `IntEnum`s in `src/diamond/constants.py`.
  - `reconcile.py` — the core audit harness. Each `FileSpec` describes one IE roster CSV with its full column list and per-column SQL derivation; the runner joins IE values to derived values per `player_id` and scores each column (match% + sample mismatches + tier). See "Reconciliation patterns" below.
  - `coverage.py` — for each user-facing feature (standings/leaders/awards/HOF/...), profiles the supporting dump CSVs to confirm they have the data we need.
  - `advanced.py` — driver that runs the full advanced-stats stack and produces a top-N players report.

- **`src/diamond/advanced/`** — pure stat-computation library. Each module is one tier of derived stats; they share the `enriched_ab` view from `enriched.py` (a TEMP TABLE built from the per-PA at-bat log with derived flags: `bip_flag`, `risp_flag`, `late_close_flag`, `spray_category`, etc.). League-relative stats (wOBA, wRC+, OPS+, ERA+, FIP) consume `LeagueConstants` from `league_constants.py`.

The audit layer is **scaffolding for the warehouse**. Once schema/ingest is built, advanced stats will run against the warehouse instead of raw CSVs, but the formulas live in one place.

### Configuration

- `src/diamond/config.py` defines `SaveConfig` (paths + scoped league IDs) and the singleton `BUILDING_THE_GREEN_MONSTER` for the active save (15 league IDs: MLB org tree + DSL + AFL).
- The OOTP saves root is hardcoded to `C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games`. Per save, the layout is `<save>/dump/dump_<YYYY>_<MM>/csv/*.csv` (monthly snapshots) and `<save>/import_export/*.csv` (the OOTP-generated reference roster CSVs we reconcile against).
- Per Decision D3, scope is hardcoded for v1 but a save-setup picker is a hard v2 requirement — keep the scoping mechanism in `SaveConfig`, not inline.

### Reconciliation patterns (`audit/reconcile.py`)

When adding a new `FileSpec`:

- **Don't filter by `team_id`.** IE roster files show each player's *full season* totals (including stints on prior orgs and short-season stops). The standard pattern is `WHERE year = 2029 AND split_id = 1` — no team filter.
- Fielding stats use `split_id = 0` (no platoon split for fielding).
- Player ratings (`scouted_ratings`) need `WHERE scouting_team_id = 4 AND league_id = 203` to take the Red Sox's view of every player.
- Use `overall_rating` / `talent_rating` (already 20-80) — **never** the raw `overall` / `talent` fields (0-200 internal scale). Per Decision D6.
- IP convention: `FLOOR(outs/3) + (outs%3)*0.1` (e.g., 517 outs → 172.1, not 172.4).
- Tier each column: A=direct dump field, B=trivial calc, C=needs league constants, D=modeled (xstats), E=at-bat aggregation, F=cannot replicate (per D5 or string-formatted display), G=needs scale conversion or integer→string mapping.
- The matcher (`_is_match`) normalizes IE display formats: `"-"` → null, `"9.1%"` → `9.1`, `"$28 800 000"` → `28800000`, `"1 (auto.)"` → `1`. Don't fight these in derivation SQL — let the matcher handle them.
- Add new dump CSVs to `_connect()`; that's where every reconcile job picks up its views.

### Codebooks

`src/diamond/constants.py` is the canonical home for verified OOTP integer mappings. Don't introduce magic numbers in derivation SQL — reference the `IntEnum`. When `decode-codes` discovers a new mapping, add it to `constants.py` with a docstring noting how it was verified (exact aggregate match, cross-ref against another file, etc.).

## Conventions and gotchas

- The `players_at_bat_batting_stats` log has `result` codes 1=K, 2=BB, 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR, 10=HBP, 11=CI. BIP excludes sacrifices (`sac > 0`).
- `import_export` files are named with the team-org prefix (`boston_red_sox_organization_-_roster_*.csv`). They were generated by OOTP and exist alongside `dump/` in the save folder.
- The November dump (`dump_YYYY_11`) is the end-of-season snapshot — it's the canonical source for season-stat reconciliation. Earlier monthly dumps roll over at season start (Feb-Mar).
- DSL teams: the Red Sox have one FCL + two DSL teams; org-level rollups must include all three.
- `audit_output/` is gitignored. Reports are regenerable from CLI; commit the *generators*, not the outputs.
- `.env` exists locally and is gitignored — GitHub push protection has blocked it before. Don't `git add -A` blindly.
