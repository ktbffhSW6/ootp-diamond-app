# Warehouse Schema

> **Status: design signed off 2026-05-05.** This is the working design for the
> 5-layer DuckDB warehouse (Phase 2 / item 2). All open questions resolved
> (see the "Open questions" section near the bottom for resolution history).
> DDL (item 3) builds against this spec. Future structural changes get
> appended here, not retroactively edited — keep the original design legible
> for "why did we do it that way" investigations.

---

## TL;DR — the five layers

| Layer | Purpose | Source | Built when | Lifecycle |
|---|---|---|---|---|
| **L0 — raw** | Per-dump landing of every scoped CSV, untyped/unfiltered, tagged with `dump_date` for provenance | OOTP CSVs in `dump/dump_YYYY_MM/csv/` | On every `diamond ingest` | Append-only per dump |
| **L1 — conformed** | Cleaned, typed, scoped to SaveConfig league_ids; canonical entity tables | L0 | After L0 lands | Event tables UPSERT, state tables snapshot-append, reference tables replace-latest |
| **L2 — facts** | Star-shaped fact tables at well-defined grains (player-season, team-season, PA-event) | L1 | After L1 | Full rebuild — DROP/CREATE |
| **L3 — derived** | Sabermetric stats, league constants, park factors, `player_movements`, awards rollups | L2 + L1 | After L2 | Full rebuild — DROP/CREATE |
| **L4 — views** | User-facing query surface: standings, leaders, draft analyzer, HOF tracker, franchise rollups | L2 + L3 | Always-on (SQL views) | No materialization |

Each save gets one DuckDB at `<save>/diamond/diamond.duckdb` (D2). All five
layers live inside it. L0 is the only layer that's a pure provenance archive
— L1-L3 are deterministic functions of L0, so they can always be rebuilt
from scratch.

---

## Data classification

Before naming tables we need to be honest about what kind of data each CSV is.
The dump's 70 files split cleanly into three groups, and each group needs a
different storage strategy.

### Event tables — append-only, one canonical version

Rows accumulate but never disappear or change retroactively. Mid-season dumps
have a strict prefix of November's row set. **Strategy:** L1 dedupes to one
row per natural key, preferring the latest dump's version (which is always
≥ any earlier dump for that key).

- `games.csv`, `games_score.csv`
- `players_at_bat_batting_stats.csv` — the per-PA log (D7 says this is our
  primary derivation source)
- `players_career_batting_stats.csv`, `players_career_pitching_stats.csv`,
  `players_career_fielding_stats.csv`
- `players_individual_batting_stats.csv`
- `players_game_batting.csv`, `players_game_pitching_stats.csv`
- `players_awards.csv`, `players_league_leader.csv`, `players_streak.csv`
- `players_injury_history.csv`, `players_salary_history.csv`
- `team_history.csv`, `team_history_*.csv`, `team_history_record.csv`
- `league_history.csv`, `league_history_*_stats.csv`, `league_history_all_star.csv`
- `league_events.csv`
- `league_playoff_fixtures.csv`, `league_playoffs.csv`
- `trade_history.csv`
- `human_manager_history.csv`, `human_manager_history_*.csv` — user's GM career
- ~~`players_batting.csv`, `players_pitching.csv`, `players_fielding.csv`~~ —
  **resolved (`[OPEN-1]`, 2026-05-05): these are NOT events.** Spot-check showed
  `players_batting` has only `running_ratings_*` (4 of 42 cols) populated; the
  `batting_ratings_*` cols are all zero. `players_pitching` is **completely
  empty** (0 of 67 rating cols populated). `players_fielding` has 27 useful
  cols (per-position experience + per-position rating + potential). Decision
  for the schema: **don't ingest `players_pitching` at all**; merge the 4
  running_ratings cols from `players_batting` into the players snapshot;
  ingest `players_fielding` as a state-snapshot (per-position experience and
  ratings change as players develop). See "State-snapshot tables" below.

### State-snapshot tables — every dump matters

Reflect "what is true *as of this dump*". Different dumps have legitimately
different rows. **Strategy:** L1 keeps every snapshot, with `dump_date` as
part of the primary key. A `_current` view exposes just the latest.

- `players.csv` — bio + current team + ratings rollup. Diffing successive
  snapshots is how `player_movements` gets built.
- `players_scouted_ratings.csv` — per-(player, scouting_team) rating history.
  Per Decision D12, **only the user's-org-scouted rows are loaded** —
  `scouting_team_id = <user_org_team_id>` (currently `4` for the Sox).
  `scouting_team_id = 0` (the objective/true rating in the dump) is
  **explicitly dropped at the L0→L1 boundary** and never reachable from
  any L1+ table or view.
- `players_fielding.csv` — per-position fielding experience (`fielding_experience1..9`)
  and per-position rating (`fielding_rating_pos1..9`) + potential. The
  experience columns are unique to this file (not in `players_scouted_ratings`).
- `players_roster_status.csv` — DL/40-man/60-day/etc.
- `players_contract.csv`, `players_contract_extension.csv`
- `players_value.csv` — WAR snapshots
- `team_roster.csv`, `team_roster_staff.csv`
- `team_record.csv`, `team_relations.csv` (rivalries change)
- `team_batting_stats.csv`, `team_pitching_stats.csv`,
  `team_fielding_stats_stats.csv`, `team_bullpen_pitching_stats.csv`,
  `team_starting_pitching_stats.csv` — current-season totals (roll over
  Feb-Mar like everything else)
- `team_financials.csv`, `team_last_financials.csv`
- `projected_starting_pitchers.csv`
- `coaches.csv`

### Reference tables — replace-latest

Change rarely; we don't need history. **Strategy:** L1 keeps just the latest
dump's version; no `dump_date` in the key.

- `leagues.csv`, `sub_leagues.csv`, `divisions.csv`
- `teams.csv`, `parks.csv`
- `nations.csv`, `continents.csv`, `states.csv`, `cities.csv`
- `languages.csv`, `language_data.csv` — ingested as reference (resolved
  OPEN-2 2026-05-05). 40 + 374 rows total; trivial cost. Unlocks future
  clubhouse-cohesion / coach-language-match analyses without re-ingest.
  `language_data.csv` lands at L1 as `geo_languages` (clearer name).
- `team_affiliations.csv` — actually maybe state-snapshot (affiliations can shift)
- `human_managers.csv` — single row (the user)

---

## L0 — Raw landing

**One table per dump CSV, untyped except for what DuckDB infers.** Add two
admin columns to every L0 table:

```
dump_date    DATE       -- e.g. 2029-11-01, derived from dump_YYYY_MM folder name
ingest_ts    TIMESTAMP  -- when this row was loaded
```

**Naming**: `l0_<csv_basename>`, e.g. `l0_players_career_batting_stats`.

**Idempotency**: re-running `diamond ingest 2029_11` is a no-op. Implementation:
`DELETE FROM l0_<csv> WHERE dump_date = ?` then `INSERT FROM read_csv_auto(...)`
inside one transaction.

**Scope**: L0 is **unscoped** (resolved OPEN-3 2026-05-05). Every row from
every CSV lands. Filtering by SaveConfig league_ids happens at the L0→L1
boundary. Keeping L0 unfiltered means we can re-scope a save (per the v2
save-setup picker / D3) without re-ingesting any dumps — only L1+ rebuilds.
The exception baked into D12: `players_scouted_ratings.scouting_team_id = 0`
rows are dropped at L0→L1 (not at L0) so they're never reachable downstream
but stay in L0 for provenance.

---

## L1 — Conformed

Each entity gets one or more tables with explicit types, foreign keys, and
domain-friendly names. **Naming convention:**

| Suffix | Meaning |
|---|---|
| (none) | Reference table — current state, no history |
| `_event` | Append-only event log, deduped to one row per natural key |
| `_snapshot` | Per-dump state history, `dump_date` in PK |
| `_current` | View on the latest snapshot; no underlying table |

### Reference (replace-latest)

```
leagues          (league_id PK, name, level_id, parent_league_id, ...)
sub_leagues      (sub_league_id PK, league_id FK, name)
divisions        (division_id PK, sub_league_id FK, name)
teams            (team_id PK, league_id FK, sub_league_id FK, division_id FK,
                  org_team_id FK, level_id, name, abbr, park_id FK, ...)
parks            (park_id PK, name, avg, avg_l, avg_r, hr, hr_l, hr_r, ...)
nations          (nation_id PK, continent_id FK, name, ...)
continents       (continent_id PK, name)
states           (state_id PK, nation_id FK, name)
cities           (city_id PK, state_id FK / nation_id FK, name)
languages        (language_id PK, name)                  -- 40 rows
geo_languages    (parent_table, parent_id, language_id) PK + percentage
                                                          -- renamed from language_data.csv;
                                                          -- nation/city → language demographic mix
human_manager    (one row — the user)
```

### Event tables (UPSERT on natural key)

Each gets a synthetic-or-natural PK and `dump_date_first_seen` /
`dump_date_last_seen` to track provenance.

```
games_event              (game_id PK)
at_bats_event            (game_id, player_id, pa_in_game_seq) PK
                          -- pa_in_game_seq = ROW_NUMBER() OVER (PARTITION BY game_id, player_id
                          --                                     ORDER BY l0.file_seq) at L1 build.
                          -- The CSV is grouped by batter; within (game, batter) file order is
                          -- chronological. Game-timeline chronology is intentionally NOT computed
                          -- here — no current analysis needs it. See OPEN-4 resolution.
career_batting_event     (player_id, year, team_id, level_id, league_id, split_id) PK
career_pitching_event    (same shape)
career_fielding_event    (player_id, year, team_id, level_id, league_id, split_id, position) PK
awards_event             (player_id, year, award_id) PK
leader_event             (player_id, year, league_id, category) PK
streak_event             (player_id, league_id, streak_id, started,
                          COALESCE(ended, '9999-12-31')) PK
                          -- COALESCE handles active streaks (ended IS NULL).
                          -- 476 boundary-dups in (player_id, league_id, streak_id, started)
                          -- alone come from ended-streak + new-active-streak sharing the
                          -- transition date. UPSERT lifecycle: row appears with has_ended=0
                          -- and ticks `value` upward across dumps; eventually has_ended
                          -- flips to 1 with `ended` populated. See OPEN-5 resolution.
injury_event             (player_id, injury_id) PK or (player_id, start_date)
salary_history_event     (player_id, year, ...) PK
trade_event              (trade_id PK)
team_history_event       (team_id, year) PK
team_history_*_stats     (team_id, year, [split]) PK
league_history_*_stats   (league_id, year, level_id, [sub_league_id]) PK
playoff_fixtures_event   (year, league_id, round, game_no) PK
playoffs_event           (year, league_id) PK
```

For November-canonical season stat tables (`career_*_stats`, `team_history_*`,
`league_history_*`), L1's UPSERT picks the latest dump's row. Mid-season
dumps overwrite their own values cleanly when November lands.

### State-snapshot tables (`dump_date` in PK)

```
players_snapshot            (player_id, dump_date) PK + bio + team + ratings rollup
players_ratings_snapshot    (player_id, scouting_team_id, dump_date) PK + 20-80 ratings
roster_status_snapshot      (player_id, dump_date) PK
contract_snapshot           (player_id, dump_date) PK
contract_extension_snapshot (player_id, dump_date) PK
player_value_snapshot       (player_id, dump_date) PK + WAR
team_roster_snapshot        (team_id, player_id, dump_date) PK
team_staff_snapshot         (team_id, role, dump_date) PK
team_record_snapshot        (team_id, dump_date) PK
team_financials_snapshot    (team_id, dump_date) PK
projected_rotation_snapshot (team_id, slot, dump_date) PK
coaches_snapshot            (coach_id, dump_date) PK
team_affiliations_snapshot  (parent_team_id, affiliate_team_id, dump_date) PK
```

### Convenience views (no materialization)

```
players_current              -- latest dump's row per player_id
players_ratings_current      -- latest, joined to scouting_team_id=4 by default
roster_status_current
contract_current
team_roster_current
team_record_current
...
```

### Scoping (D3/D4)

A side table `_scoped_players` gets rebuilt at L0→L1 time:

```
_scoped_players (player_id PK, first_seen_dump DATE, last_seen_dump DATE)
```

Population rule (D4 — once-in-scope, always-in-scope): any player who appears
in any dump on a team whose `league_id` is in `SaveConfig.scoped_league_ids`
stays. Derived from L0's `players` snapshots across all 44 dumps.

L1 event/state tables filter on `_scoped_players` so we don't drag 148K
world-bios through downstream layers.

---

## L2 — Facts

Star-shaped, one row per unit-of-analysis, ready for filtering and rollup.
All built deterministically from L1 — full rebuild on every ingest.

```
f_player_season_batting   (player_id, year, league_id, level_id, team_id, split_id) PK
                           + counting stats only (G, PA, AB, H, 2B, 3B, HR, BB, IBB, HP, K,
                             SH, SF, CI, GDP, R, RBI, SB, CS, ...)
                           + WAR (raw, summed across stints)
                           + dump_date (canonical Nov-dump source)

f_player_season_pitching  (same shape; counting stats only — IP outs, ER, HA, HRA,
                           BB, K, HP, BF, GB, FB, ...)

f_player_season_fielding  (player_id, year, league_id, level_id, team_id, position, split_id) PK
                          + per-position counting + ZR/FRM/ARM

f_player_career           (player_id) PK + cross-level COUNTING-only rollup per D11

f_team_season             (team_id, year) PK + W/L/RS/RA/run-diff/Pythag + standings position

f_league_season           (league_id, year, level_id) PK + league totals (the source for league_constants)

f_pa_event                (game_id, inning, half, ab_seq) PK [confirm at OPEN-4]
                          + batter_id, pitcher_id, year, league_id, level_id, team_id, opp_team_id,
                            result, hit_loc, hit_xy, balls/strikes count, base/out state, EV, LA,
                            risp_flag, late_close_flag, bip_flag — at-bat fact at the
                            granularity D7 needs

f_award_event             (player_id, year, award_id) — same as L1.awards but with team_id pre-joined

f_movement_event          [computed in L3 — see below]
```

**Multi-level players (D11)**: `f_player_season_batting` keeps separate rows
per `(player_id, year, level_id)`. Counting stats can be summed across rows;
rate stats and sabermetrics live in L3 and are computed per row only.

---

## L3 — Derived

The "value-add" layer. Every table here is a deterministic transform of L2 +
L1 reference data. Full rebuild on every ingest.

```
league_constants             (league_id, year, level_id) PK + 28 columns
                              (current sketch in src/diamond/league_constants.py;
                               this materialization replaces the SQL view)

park_factors                 (park_id, year) PK + avg, avg_l, avg_r, hr, hr_l, hr_r,
                              halved_avg = 1 + (avg - 1) / 2 (for OPS+ convention)

f_player_season_advanced     (player_id, year, league_id, level_id) PK
                              + AVG, OBP, SLG, OPS, ISO, BABIP, BB%, K%
                              + wOBA, wRAA, wRC, wRC+
                              + OPS+, ERA+, FIP, SIERA, RC, RC/27
                              + RF/9 (fielding), RE24 exposure, etc.
                              [the formulas already live in src/diamond/advanced/*]

player_movements             (player_id, dump_date_observed, movement_type, from_team_id,
                              to_team_id, from_level_id, to_level_id, source) PK?
                              Built from:
                                (1) successive players_snapshot diffs (team_id changes,
                                    level_id transitions, retired flag turning on)
                                (2) trade_history.summary parse (where the entity
                                    tags <player:type#id> can be read — a parser is
                                    on the audit carry-forward list)
                                (3) draft picks (from players.draft_* fields)

f_award_career               (player_id, award_id) + count, years_won list

f_award_franchise            (team_id, award_id) + count

streak_history               (player_id, streak_type, start_date, end_date,
                              length, value) — decoded from players_streak.csv

f_record_player              (player_id, record_category, value, year)
                              -- max-agg over career stats (per BACKLOG)

f_record_team                (team_id, record_category, value, year)
f_record_league              (league_id, record_category, value, year)
```

**`[OPEN-6]`** Should `f_player_season_advanced` be one wide table or split
batting / pitching / fielding into three? Wide is easier to query, splits
match L2's split. Lean: split, mirror L2.

---

## L4 — Views

User-facing API. SQL views — never materialized unless perf demands it.
Each view is a thin SELECT joining L2 + L3 + L1 reference.

```
v_standings                       -- per (year, league_id) team standings
v_leaders_batting                 -- per (year, league_id, category) top-N
v_leaders_pitching
v_award_winners                   -- by year / by category / by franchise
v_hall_of_fame                    -- inducted players + path-to-induction (awards/career)
v_active_streaks                  -- longest-active per category
v_franchise_history               -- per team_id, season-by-season
v_draft_class                     -- per (draft_year, team_id) — for the draft analyzer
v_draft_class_outcomes            -- v_draft_class + WAR-through-N + current level/team
v_player_career                   -- one row per player, career counting + best-season pointers
v_player_movements                -- normalized timeline (signed → traded → released etc.)
v_player_timeline                 -- per (player_id) every event in order
v_xref_*                          -- crosswalks: league_id → league name, etc.
```

L4 is the layer the future Bref/Fangraphs-style web frontend hits. Today the
CLI's `diamond coverage` and `diamond advanced` commands shift to consuming
L4 once it exists.

---

## Cross-cutting concerns

### Reconciliation (D8)

Today `reconcile.py` reads CSVs directly. After ingest lands:

1. Phase 2 / item 6: rewrite `reconcile.py` to read from L1 instead of raw
   CSVs. Same `FileSpec` layer, same per-column derivations, but views like
   `career_bat` resolve to L1.`career_batting_event` and the at-bat log
   resolves to L2.`f_pa_event`.
2. Run after every `diamond ingest` as a regression check.
3. Reports still go to `audit_output/`.

This means the L1 schema needs to expose the same column names that the
existing FileSpecs reference (`career_bat`, `career_pit`, `career_field`,
`at_bats`, etc.) — most cleanly via aliasing views in L1.

### Multi-dump idempotency

Re-running `diamond ingest 2029_11` is a no-op. `diamond ingest --all`
walks every dump folder under `<save>/dump/` and processes them in date
order, skipping any whose `dump_date` already exists at L0 with a matching
ingest checksum. **`[OPEN-7]`** Use a `dump_ingests` admin table with
checksum + ts, or just check L0 row counts? Lean: admin table.

### Scope changes (future v2 picker per D3)

If the user re-scopes the save (adds KBO say), L0 stays as-is (it was always
unfiltered for reference + filtered-by-current-scope for events/state per
OPEN-3). The fix is: rebuild `_scoped_players` with the new scope, then
DROP/CREATE L1 (event+state, where they reference _scoped_players), L2, L3.
No re-ingest needed if OPEN-3 lands on "L0 unfiltered for everything".
That's a strong argument for unfiltered L0 — worth the extra disk.

---

## Ingest flow (target shape)

```
diamond ingest <dump_date>      # one dump
diamond ingest --all            # every dump folder under <save>/dump/, in date order
diamond ingest --rebuild        # drop L1/L2/L3, rebuild from L0 (no re-ingest of CSVs)
```

Per-dump flow:

```
1. Load CSVs into L0 (transactional, idempotent on dump_date)
2. Recompute _scoped_players from union of all L0 players snapshots
3. Upsert/append into L1 (event tables UPSERT, state tables append snapshot,
   reference tables replace-latest)
4. DROP/CREATE L2
5. DROP/CREATE L3
6. (item 6) Run reconcile.py against L1; emit audit_output/reconciliation_report.md
```

Steps 4-5 are cheap because DuckDB on this dataset fits comfortably in
memory; full rebuild is simpler than incremental and removes a whole class
of drift bugs.

---

## Open questions (all resolved 2026-05-05)

> History kept inline below for traceability. Resolutions feed into DDL (item 3).

1. ~~**`[OPEN-1]`** Are `players_batting.csv`/`players_pitching.csv`/`players_fielding.csv`
   actually running-totals state or duplicates of `players_career_*`?~~
   **Resolved 2026-05-05**: neither — they're rating snapshots, mostly
   empty in this save. Skip `players_pitching` entirely. Pull the 4
   running_ratings cols from `players_batting` into the players snapshot.
   Ingest `players_fielding` as a state-snapshot for per-position experience
   + ratings.
2. ~~**`[OPEN-2]`** Skip `languages.csv` / `language_data.csv` ingest?~~
   **Resolved 2026-05-05**: ingest as reference. 40 + 374 rows; storage cost
   negligible; supports future clubhouse-cohesion / coach-language-match
   analyses without re-ingest. `language_data.csv` lands as `geo_languages`
   for naming clarity.
3. ~~**`[OPEN-3]`** L0 unfiltered or apply SaveConfig filter at L0?~~
   **Resolved 2026-05-05**: unfiltered. Disk is cheap, re-scope is free
   (rebuild L1+ only, no re-ingest). Note D12 exception:
   `scouting_team_id=0` rows DO land in L0 (provenance) but are dropped at
   the L0→L1 boundary so they can't reach the product.
4. ~~**`[OPEN-4]`** Confirm primary key for `players_at_bat_batting_stats`.~~
   **Resolved 2026-05-05**: no natural PK exists. The closest natural composite
   `(game_id, inning, outs, balls, strikes, player_id, opponent_player_id)`
   still has 6 dups in 1.3M rows. Synthesize at L1 using
   `(game_id, player_id, pa_in_game_seq)` where pa_in_game_seq comes from
   `ROW_NUMBER() OVER (PARTITION BY game_id, player_id ORDER BY l0.file_seq)`.
   Requires L0 to stamp a `file_seq INTEGER` per row at load time. CSV is
   grouped by batter (file rows 1730-1733 = player 60's four PAs of one game,
   then 20669-20672 = player 1825's four PAs of the same game), so global
   file order is NOT chronological game-timeline (23% of consecutive
   same-game rows show inning decrease in file order) — but within
   `(game_id, player_id)` file order IS chronological, which is what we need.
5. ~~**`[OPEN-5]`** Streak rows — is `(player_id, streak_id, start_date)` unique?~~
   **Resolved 2026-05-05**: `(player_id, league_id, streak_id, started)` has
   476 dups in 316K rows (mostly `streak_id=21` boundary collisions where an
   ended streak and a new active streak share the transition date).
   `(player_id, league_id, streak_id, started, COALESCE(ended, '9999-12-31'))`
   is fully unique → use as PK. Single table (not split active/ended) because
   the same logical streak appears across dumps with monotonically updating
   `value` and eventually flips `has_ended` from 0 → 1.
6. ~~**`[OPEN-6]`** `f_player_season_advanced` — wide or split?~~
   **Resolved 2026-05-05**: split into
   `f_player_season_advanced_batting` / `_pitching` / `_fielding`, mirroring
   L2's grain. Wide-table semantics get awkward fast — a pitcher has no
   batting wOBA, a position player has no FIP, so a unified table is either
   80% NULLs or two-rows-per-player-per-season with a `discriminator`
   column that consumers must remember to filter on. Split tables make the
   grain self-evident and join patterns mirror L2 exactly.
7. ~~**`[OPEN-7]`** Idempotency mechanism — admin table or L0 row-count?~~
   **Resolved 2026-05-05**: admin table `_diamond_ingests` keyed on
   `(dump_date)` with columns `(ingest_ts, csv_checksum_blob, status,
   rows_inserted, rows_per_table_json)`. Row-count alone is fragile (same
   count after corruption, partial writes, encoding-flip); a checksum on
   the input CSVs catches actual content drift. The admin table also gives
   us a place to log per-dump ingest stats for debugging. Underscore
   prefix marks it as warehouse-machinery, separate from analytic tables.
8. ~~**`[OPEN-8]`** Naming convention.~~
   **Resolved 2026-05-05**: prefix by **shape**, not by layer. Concretely:
   - `l0_<csv_basename>` — raw landing tables only.
   - L1 — entity-natural names with semantic suffix:
     `_event` (UPSERT'd append-only), `_snapshot` (per-dump state),
     `_current` (latest-snapshot view). No prefix.
   - `f_*` — fact-shaped tables (one row per analytical grain), at **either
     L2 or L3**: `f_player_season_batting` (L2), `f_player_season_advanced_batting`
     (L3), `f_award_career` (L3). The `f_` says "fact-grain"; layer is
     determined by build order in the ingest pipeline, not by prefix.
   - **No prefix** for L3 reference-shaped or movement-event tables:
     `league_constants`, `park_factors`, `player_movements`, `streak_history`.
     These are dimension- or event-shaped, not fact-shaped, so `f_` would
     mislead.
   - `v_*` — L4 query-time views.
   - `_*` (leading underscore) — warehouse machinery (`_diamond_ingests`,
     `__scoped_players`).

   Rationale: shape is what query-writers care about (am I about to filter
   a fact or look up a dimension?). Layer is documentation. Grep `l0_` /
   `f_` / `v_` / `_` to enumerate by category cleanly.
9. ~~**`[OPEN-9]`** L4 view namespace.~~
   **Resolved 2026-05-05**: single flat `v_*` namespace. Domain-splitting
   forces categorization decisions that often have multiple right answers
   (`v_draft_class_outcomes` is player-grain but team-organized — which
   subnamespace?). The dominant entity already falls out of the table name
   itself (`v_player_*`, `v_team_*`, `v_franchise_*` patterns emerge
   organically without enforcing a directory structure). Flat keeps the
   `v_` prefix as the single "user-facing API surface" signal.
10. ~~**`[OPEN-10]`** Should `at_bats_event` and `f_pa_event` be the same table?~~
    **Resolved 2026-05-05** (knock-on of OPEN-4): keep them separate. L1
    `at_bats_event` holds the typed/scoped raw event keyed on
    `(game_id, player_id, pa_in_game_seq)`. L2 `f_pa_event` adds the
    dimensional flatten (year, league_id, level_id, team_id, opp_team_id —
    requires joins to `games` and `players` snapshot) plus the derived flags
    (`bip_flag`, `risp_flag`, `late_close_flag`, `spray_category`) that
    today live in `src/diamond/advanced/enriched.py`. Real transformation,
    worth two layers.

---

## Summary diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ L0  raw landing — l0_<csv_name>, partitioned by dump_date       │
│                  (per-dump UPSERT, idempotent, full provenance) │
└────────────────┬────────────────────────────────────────────────┘
                 │  scope filter (D3/D4) via _scoped_players
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ L1  conformed — typed, scoped, deduped                          │
│    reference tables  (replace-latest)                           │
│    *_event tables    (UPSERT on natural key, prefer Nov dump)   │
│    *_snapshot tables (append per dump_date)                     │
│    *_current views   (latest dump_date)                         │
└────────────────┬────────────────────────────────────────────────┘
                 │  full rebuild
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ L2  facts —  f_player_season_batting / pitching / fielding      │
│              f_team_season, f_league_season                     │
│              f_pa_event (PA-grain at-bat fact)                  │
│              f_award_event                                      │
└────────────────┬────────────────────────────────────────────────┘
                 │  full rebuild
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ L3  derived — league_constants, park_factors,                   │
│               f_player_season_advanced (wOBA/wRC+/FIP/SIERA),   │
│               player_movements, streak_history, record tables   │
└────────────────┬────────────────────────────────────────────────┘
                 │  query-time only (SQL views)
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ L4  views — v_standings, v_leaders_*, v_award_winners,          │
│             v_hall_of_fame, v_draft_class_outcomes, v_player_*  │
└─────────────────────────────────────────────────────────────────┘
```
