"""L3 derived leverage / context-stat tables — per-(player, year, league, level).

The leverage stack: **WPA / LI / RE24 / Clutch**. These are the
"context-aware" complement to the rate stats in `f_player_season_advanced_*`
— wOBA tells you "how good was the contact?", WPA tells you "how much
did it matter?".

Sources are split between OOTP's L0 game logs and L_REF's RE288 grid:

- **WPA** comes directly from L0 (`players_game_batting_event.wpa` and
  `players_game_pitching_event.wpa`). OOTP computes per-PA win probability
  from its own pitch-by-pitch sim engine, then aggregates to per-game-per-
  player. We sum to (year, player, league, level). Scale is real WPA
  (units of "wins added"; ±0.5 typical per game; full season can hit 5+
  for elite seasons). Reconciles trivially against the IE roster CSVs'
  WPA column.

- **LI** comes from L0 for pitchers (`players_game_pitching_event.li`).
  Empirically decoded 2026-05-14: the per-game ``li`` value is the
  **SUM of leverage across PAs faced**, not the per-PA average. Season
  per-PA Tango LI = ``SUM(li) / SUM(bf)`` — verified against league avg
  (≈1.05, near Tango's 1.0 spec), top closers (Martinez 2.41, Edwin Díaz
  2.35, matches real-MLB closer-LI 1.7-2.0+), starters (Gilbert 0.88,
  Skubal 0.97, matches real-MLB starter-LI 0.85-1.10). No 10× rescaling
  needed. **Batter LI is not in L0** — would need per-PA derivation from
  `lref_li_table` (variable-width score-diff columns); deferred.

- **RE24** is computed per-PA from `f_pa_event` joined to OOTP's canonical
  `lref_re288_table` (24×12 grid: 3 outs × 8 base states × 12 counts).
  For per-PA scope we use the 0-0 column (count is irrelevant at PA grain).
  Per-PA contribution: ``RE24_pa = RE_after - RE_before + runs_during_pa``
  where ``RE_after`` is the start-of-next-PA state in the same half-inning
  (NULL → 0 if half-inning ended) and ``runs_during_pa`` is approximated
  by ``rbi`` (excludes wild-pitch / error runs but those are noise).
  Aggregated to (year, batter_id) and (year, pitcher_id) — the pitcher
  side carries an inverted sign by convention ("RE24 against — lower is
  better").

- **Clutch** = WPA / LI per Tango. Pitcher-only for v1; batter Clutch
  unlocks once batter LI is derived. Positive = stepped up in higher-
  leverage spots; negative = produced more in low-leverage situations.

Build pattern: full DROP/CREATE on every L3 build, mirroring l3_advanced.
Soft-skip the RE24 computation if `lref_re288_table` is missing (pre-
Slice-1 saves); WPA/LI from L0 always work because L0 always loads.

Dictionary cross-reference (per D15):
  WPA / LI / RE24 / Clutch — every column maps to a `STATS[id]` entry.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# RE288 lookup view — wide → long form
#
# Source `lref_re288_table` is 24 rows × (out, bases, 12 count cols). We
# UNPIVOT into one row per (out, bases, count) = 288 cells. The `bases`
# axis encodes occupancy positionally — a 3-char string where position
# 1 = 1B, 2 = 2B, 3 = 3B, and `O` means occupied / `X` means empty.
# Decoded once into 1B/2B/3B booleans for direct equality JOINs against
# `f_pa_event.base1/base2/base3`.
# ─────────────────────────────────────────────────────────────────────────────

_RE288_LOOKUP_VIEW_SQL = """
    CREATE OR REPLACE VIEW _re288_lookup AS
    WITH long AS (
        UNPIVOT lref_re288_table
        ON COLUMNS(* EXCLUDE (out, bases))
        INTO
            NAME count_str
            VALUE re_str
    )
    SELECT
        CAST(out AS INTEGER)                        AS outs,
        -- Position 1 = 1B, 2 = 2B, 3 = 3B; 'O' = occupied
        CASE WHEN SUBSTR(bases, 1, 1) = 'O' THEN 1 ELSE 0 END AS base1,
        CASE WHEN SUBSTR(bases, 2, 1) = 'O' THEN 1 ELSE 0 END AS base2,
        CASE WHEN SUBSTR(bases, 3, 1) = 'O' THEN 1 ELSE 0 END AS base3,
        -- count_str like '0-0', '0-1', ..., '3-2'
        CAST(SPLIT_PART(count_str, '-', 1) AS INTEGER) AS balls,
        CAST(SPLIT_PART(count_str, '-', 2) AS INTEGER) AS strikes,
        TRY_CAST(re_str AS DOUBLE)                  AS re_value
    FROM long
    WHERE re_str IS NOT NULL AND re_str != ''
"""


# ─────────────────────────────────────────────────────────────────────────────
# Per-PA RE24 view
#
# Computes per-PA run-expectancy delta. Strategy:
#   1. JOIN each PA against `_re288_lookup` at the PA-start state to get
#      RE_before (count='0-0' column — count axis is per-pitch, not per-PA).
#   2. LEAD over (game_id, inning, batter_team_id) ordered by pa_in_game_seq
#      to get the next PA's start state in the same half-inning. That IS
#      the after-state of the current PA. NULL → end of half-inning →
#      RE_after = 0.
#   3. Approximate runs_during_pa with `rbi` (canonical RE24 input;
#      excludes wild-pitch / error runs but those are noise in the
#      season aggregate).
#   4. RE24_pa = RE_after - RE_before + rbi.
#
# The "after-state RE" lookup happens via a second JOIN against `_re288_lookup`
# but with the LEAD-derived columns. When the half-inning ends, the LEAD
# columns are NULL and the JOIN drops out — COALESCE to 0.
# ─────────────────────────────────────────────────────────────────────────────

_F_PA_EVENT_RE24_VIEW_SQL = """
    CREATE OR REPLACE VIEW _f_pa_event_re24 AS
    WITH pa AS (
        SELECT
            game_id, year, league_id, level_id,
            batter_id, pitcher_id, batter_team_id, pa_in_game_seq,
            inning, outs, base1, base2, base3,
            COALESCE(rbi, 0)                                       AS rbi,
            -- After-state via LEAD within (game_id, inning, batter_team_id);
            -- NULL when the half-inning ended on this PA. We materialize the
            -- LEAD columns and a separate "is_last" flag for clarity.
            LEAD(outs)  OVER w                                     AS outs_after,
            LEAD(base1) OVER w                                     AS base1_after,
            LEAD(base2) OVER w                                     AS base2_after,
            LEAD(base3) OVER w                                     AS base3_after
        FROM f_pa_event
        WINDOW w AS (
            PARTITION BY game_id, inning, batter_team_id
            ORDER BY pa_in_game_seq
        )
    )
    SELECT
        pa.game_id, pa.year, pa.league_id, pa.level_id,
        pa.batter_id, pa.pitcher_id, pa.pa_in_game_seq, pa.rbi,
        re_before.re_value                                         AS re_before,
        COALESCE(re_after.re_value, 0)                             AS re_after,
        COALESCE(re_after.re_value, 0) - COALESCE(re_before.re_value, 0)
            + pa.rbi                                               AS re24
    FROM pa
    LEFT JOIN _re288_lookup re_before
        ON re_before.outs = pa.outs
       AND re_before.base1 = pa.base1
       AND re_before.base2 = pa.base2
       AND re_before.base3 = pa.base3
       AND re_before.balls = 0 AND re_before.strikes = 0
    LEFT JOIN _re288_lookup re_after
        ON re_after.outs = pa.outs_after
       AND re_after.base1 = pa.base1_after
       AND re_after.base2 = pa.base2_after
       AND re_after.base3 = pa.base3_after
       AND re_after.balls = 0 AND re_after.strikes = 0
"""


# ─────────────────────────────────────────────────────────────────────────────
# Player-season leverage builders
#
# WPA + LI come from L0 game-event tables (OOTP-supplied per-game values
# summed/averaged to season). RE24 comes from the per-PA view above.
#
# split_id convention:
#   - L0 batter event uses split_id = 0 (no platoon split for game-level).
#   - L0 pitcher event uses split_id = 1 (regular game; 18/19/21 are
#     post-season variants we exclude for season totals).
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_player_season_leverage_batting(
    con: duckdb.DuckDBPyConnection,
    *,
    has_re24: bool,
) -> int:
    """Per-(batter, year, league, level) WPA + RE24.

    Coverage asymmetry note: OOTP's L0 game-event tables
    (`players_game_batting_event`) are **current-year-only** in the dump,
    so WPA fills only for the most recent season. `f_pa_event` is
    multi-year (we dedup across dumps), so RE24 fills for every year
    with at-bat coverage (2026-2029 in this save). FULL OUTER JOIN of
    the two aggregates yields one row per (player, year, league, level)
    where EITHER metric exists; downstream code renders NULL as em-dash.
    """
    if has_re24:
        sql = """
            CREATE OR REPLACE TABLE f_player_season_leverage_batting AS
            WITH wpa AS (
                SELECT
                    player_id, year, league_id, level_id,
                    COUNT(DISTINCT game_id)            AS games,
                    SUM(pa)                            AS pa_sum,
                    ROUND(SUM(wpa), 4)                 AS wpa
                FROM players_game_batting_event
                WHERE split_id = 0
                GROUP BY 1, 2, 3, 4
            ),
            re24 AS (
                SELECT
                    batter_id AS player_id,
                    year, league_id, level_id,
                    COUNT(*)                           AS pa_re24,
                    ROUND(SUM(re24), 2)                AS re24_sum
                FROM _f_pa_event_re24
                WHERE batter_id IS NOT NULL
                  AND year      IS NOT NULL
                  AND league_id IS NOT NULL
                  AND level_id  IS NOT NULL
                GROUP BY 1, 2, 3, 4
            )
            SELECT
                player_id,
                year,
                league_id,
                level_id,
                wpa.games                                  AS games,
                COALESCE(wpa.pa_sum, re24.pa_re24)         AS pa,
                wpa.wpa                                    AS wpa,
                re24.re24_sum                              AS re24
            FROM wpa
            FULL OUTER JOIN re24 USING (player_id, year, league_id, level_id)
        """
    else:
        sql = """
            CREATE OR REPLACE TABLE f_player_season_leverage_batting AS
            SELECT
                player_id, year, league_id, level_id,
                COUNT(DISTINCT game_id)            AS games,
                SUM(pa)                            AS pa,
                ROUND(SUM(wpa), 4)                 AS wpa,
                CAST(NULL AS DOUBLE)               AS re24
            FROM players_game_batting_event
            WHERE split_id = 0
            GROUP BY 1, 2, 3, 4
        """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_leverage_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_leverage_batting"
    ).fetchone()[0]


def _build_f_player_season_leverage_pitching(
    con: duckdb.DuckDBPyConnection,
    *,
    has_re24: bool,
) -> int:
    """Per-(pitcher, year, league, level) WPA + LI + RE24-against + Clutch.

    Pitcher RE24-against is the negation of batter RE24 keyed on pitcher_id.
    Lower = better (the pitcher prevented runs). LI is IP-weighted average
    of OOTP's per-game leverage values; we expose both raw OOTP scale and
    Tango-normalized (÷10).

    Clutch = WPA / LI_tango per Tango — positive means stepped up in
    higher-leverage spots, negative means good in lower-leverage. NULL
    for pitchers with li_tango ≈ 0 (essentially mop-up only).
    """
    if has_re24:
        sql = """
            CREATE OR REPLACE TABLE f_player_season_leverage_pitching AS
            WITH wpa AS (
                SELECT
                    player_id, year, league_id, level_id,
                    COUNT(DISTINCT game_id)            AS games,
                    SUM(outs) / 3.0                    AS ip,
                    SUM(bf)                            AS bf,
                    ROUND(SUM(wpa), 4)                 AS wpa,
                    -- L0 per-game `li` is SUM of leverage across PAs faced.
                    -- Season per-PA Tango LI = SUM(li) / SUM(bf).
                    CASE WHEN SUM(bf) > 0
                        THEN ROUND(SUM(li) / SUM(bf), 3)
                        ELSE NULL
                    END                                AS li
                FROM players_game_pitching_event
                WHERE split_id = 1
                GROUP BY 1, 2, 3, 4
            ),
            re24 AS (
                SELECT
                    pitcher_id AS player_id,
                    year, league_id, level_id,
                    COUNT(*)                           AS pa_re24,
                    ROUND(-SUM(re24), 2)               AS re24_against
                FROM _f_pa_event_re24
                WHERE pitcher_id IS NOT NULL
                  AND year      IS NOT NULL
                  AND league_id IS NOT NULL
                  AND level_id  IS NOT NULL
                GROUP BY 1, 2, 3, 4
            )
            SELECT
                player_id,
                year,
                league_id,
                level_id,
                wpa.games                                  AS games,
                wpa.ip                                     AS ip,
                COALESCE(wpa.bf, re24.pa_re24)             AS bf,
                wpa.wpa                                    AS wpa,
                wpa.li                                     AS li,
                re24.re24_against                          AS re24,
                -- Clutch = WPA / LI per Tango. Guard against LI near zero
                -- (mop-up appearances make the ratio explode); NULL if LI
                -- below 0.10 (essentially no leverage exposure).
                CASE WHEN wpa.li > 0.10
                    THEN ROUND(wpa.wpa / wpa.li, 3)
                    ELSE NULL
                END                                        AS clutch
            FROM wpa
            FULL OUTER JOIN re24 USING (player_id, year, league_id, level_id)
        """
    else:
        sql = """
            CREATE OR REPLACE TABLE f_player_season_leverage_pitching AS
            SELECT
                player_id, year, league_id, level_id,
                COUNT(DISTINCT game_id)            AS games,
                SUM(outs) / 3.0                    AS ip,
                SUM(bf)                            AS bf,
                ROUND(SUM(wpa), 4)                 AS wpa,
                CASE WHEN SUM(bf) > 0
                    THEN ROUND(SUM(li) / SUM(bf), 3)
                    ELSE NULL
                END                                AS li,
                CAST(NULL AS DOUBLE)               AS re24,
                CASE WHEN SUM(bf) > 0 AND SUM(li) / SUM(bf) > 0.10
                    THEN ROUND(SUM(wpa) / (SUM(li) / SUM(bf)), 3)
                    ELSE NULL
                END                                AS clutch
            FROM players_game_pitching_event
            WHERE split_id = 1
            GROUP BY 1, 2, 3, 4
        """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_leverage_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_leverage_pitching"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — registered into the L3 builder list
# ─────────────────────────────────────────────────────────────────────────────


def build_l3_leverage(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build the per-(player, year, league_id, level_id) leverage fact tables.

    Returns dict of `{table_name: row_count}`. Idempotent (CREATE OR
    REPLACE under the hood). Soft-skips RE24 if `lref_re288_table` is
    missing (pre-Slice-1 warehouses) — WPA/LI columns still populate
    from L0 alone.
    """
    rows: dict[str, int] = {}

    # 1. Soft-detect L_REF RE288 availability.
    re288_loaded = con.execute(
        """
        SELECT COUNT(*) > 0 FROM information_schema.tables
        WHERE table_name = 'lref_re288_table'
        """
    ).fetchone()[0]
    if re288_loaded:
        con.execute(_RE288_LOOKUP_VIEW_SQL)
        con.execute(_F_PA_EVENT_RE24_VIEW_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _re288_lookup / _f_pa_event_re24 (views) "
                "[dim]L_REF RE288 grid → per-PA run expectancy[/dim]"
            )
    elif verbose:
        console.print(
            "  [yellow]![/yellow] RE24 disabled — lref_re288_table missing "
            "[dim](run `diamond ingest` to ingest L_REF)[/dim]"
        )

    # 2. Player-season aggregates.
    builders = [
        ("f_player_season_leverage_batting",
            lambda c: _build_f_player_season_leverage_batting(c, has_re24=re288_loaded)),
        ("f_player_season_leverage_pitching",
            lambda c: _build_f_player_season_leverage_pitching(c, has_re24=re288_loaded)),
    ]
    for name, fn in builders:
        n = fn(con)
        rows[name] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {name:<42} [dim]{n:>10,} rows[/dim]"
            )

    return rows
