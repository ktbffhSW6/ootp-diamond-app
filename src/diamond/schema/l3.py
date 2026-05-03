"""L3 derived tables — model-driven analytical surfaces built on L1 + L2.

This module currently exposes only `player_movements` (Phase 2 / item 7).
Future L3 builders that will live here:

  - park_factors                    — halved-park-factor materialization
  - f_player_season_advanced_*      — wOBA / wRC+ / FIP / SIERA per season
  - streak_history                  — decoded streak rows with names
  - f_record_*                      — career / season / franchise records
  - f_award_career / f_award_franchise

Build pattern: L3 tables are full DROP/CREATE on every ingest (cheap; the
warehouse fits in memory). They depend on L1 / L2 already being current.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# player_movements
# ─────────────────────────────────────────────────────────────────────────────


def _build_player_movements(con: duckdb.DuckDBPyConnection) -> int:
    """Derive `player_movements` from snapshot diffs + draft data.

    Two sources are emitted:

      1. **snapshot_diff**: compare consecutive (player_id, dump_date) rows
         of `players_snapshot`; emit a row each time `team_id` or `retired`
         changes. Movement types: first_appearance | team_change | signed |
         released | retired | unretired.

      2. **draft**: one row per player whose `draft_team_id > 0`, recorded
         at the first dump_date we saw them. Captures both pre-save
         imported draftees (HoF members, historical legends) and in-save
         draft classes.

    Trade attribution is intentionally deferred — the trade_history.summary
    parser is on the audit carry-forward list. Once the parser exists,
    `player_movements` can be left-joined to `trade_event` to attribute
    `team_change` rows to specific trades.

    Level lookup: joins `teams` on `team_id` to read the `level` column,
    yielding `from_level_id` and `to_level_id` for downstream filtering
    (e.g., "show me all promotions to MLB").
    """
    con.execute("""
        CREATE OR REPLACE TABLE player_movements AS
        WITH ordered AS (
            -- One row per (player, dump) with prev-state cols for diffing
            SELECT
                player_id,
                dump_date,
                team_id,
                retired,
                LAG(team_id) OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS prev_team_id,
                LAG(retired) OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS prev_retired,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS row_num
            FROM players_snapshot
        ),
        diffs AS (
            -- Emit one row per actual transition. row_num=1 is "first time
            -- we ever saw this player" → first_appearance. Subsequent rows
            -- only emit if team_id or retired changed.
            SELECT
                player_id,
                dump_date AS dump_date_observed,
                prev_team_id AS from_team_id,
                team_id AS to_team_id,
                CASE
                    WHEN row_num = 1 THEN 'first_appearance'
                    WHEN prev_retired = 0 AND retired = 1 THEN 'retired'
                    WHEN prev_retired = 1 AND retired = 0 THEN 'unretired'
                    WHEN COALESCE(prev_team_id, 0) = 0 AND team_id > 0 THEN 'signed'
                    WHEN prev_team_id > 0 AND team_id = 0 THEN 'released'
                    WHEN prev_team_id != team_id THEN 'team_change'
                    ELSE NULL
                END AS movement_type
            FROM ordered
            WHERE row_num = 1
               OR COALESCE(prev_team_id, -1) != COALESCE(team_id, -1)
               OR COALESCE(prev_retired, -1) != COALESCE(retired, -1)
        ),
        snapshot_movements AS (
            SELECT
                d.player_id,
                d.dump_date_observed,
                d.movement_type,
                d.from_team_id,
                d.to_team_id,
                tf.level AS from_level_id,
                tt.level AS to_level_id,
                'snapshot_diff' AS source,
                CAST(NULL AS INTEGER) AS draft_year,
                CAST(NULL AS INTEGER) AS draft_round,
                CAST(NULL AS INTEGER) AS draft_overall_pick
            FROM diffs d
            LEFT JOIN teams tf ON tf.team_id = d.from_team_id
            LEFT JOIN teams tt ON tt.team_id = d.to_team_id
            WHERE d.movement_type IS NOT NULL
        ),
        draft_first_seen AS (
            -- For draft events, take each scoped player's earliest snapshot
            -- where draft_team_id is populated.  draft_year + draft_team_id
            -- are stamped per player and stable across dumps (drafts don't
            -- get rescinded in OOTP), so MIN(dump_date) is fine.
            SELECT
                player_id,
                MIN(dump_date) AS dump_date_observed,
                ANY_VALUE(draft_year)         AS draft_year,
                ANY_VALUE(draft_team_id)      AS draft_team_id,
                ANY_VALUE(draft_round)        AS draft_round,
                ANY_VALUE(draft_overall_pick) AS draft_overall_pick
            FROM players_snapshot
            WHERE draft_year > 0 AND draft_team_id > 0
            GROUP BY player_id
        ),
        draft_movements AS (
            SELECT
                d.player_id,
                d.dump_date_observed,
                'drafted' AS movement_type,
                CAST(NULL AS INTEGER) AS from_team_id,
                d.draft_team_id AS to_team_id,
                CAST(NULL AS INTEGER) AS from_level_id,
                tt.level AS to_level_id,
                'draft' AS source,
                d.draft_year,
                d.draft_round,
                d.draft_overall_pick
            FROM draft_first_seen d
            LEFT JOIN teams tt ON tt.team_id = d.draft_team_id
        )
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY player_id, dump_date_observed, source
            ) AS movement_id,
            *
        FROM (
            SELECT * FROM snapshot_movements
            UNION ALL
            SELECT * FROM draft_movements
        ) all_movements
    """)
    con.execute(
        "ALTER TABLE player_movements ADD PRIMARY KEY (movement_id)"
    )
    return con.execute("SELECT COUNT(*) FROM player_movements").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l3(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build all L3 derived tables. Currently only `player_movements`.

    Requires L1 (players_snapshot, teams) to be present.

    Returns dict of `{l3_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    n = _build_player_movements(con)
    rows["player_movements"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] player_movements                "
            f"[dim]{n:>10,} rows  PK=(movement_id)[/dim]"
        )

    return rows
