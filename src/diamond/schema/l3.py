"""L3 derived tables — model-driven analytical surfaces built on L1 + L2.

Currently exposes:

  - f_trade_participant   long-format trade roster, 1 row per (trade × player)
  - player_movements      timeline of every team change, attributed to trades
                          where applicable

Future L3 builders that will live here:

  - park_factors                    — halved-park-factor materialization
  - f_player_season_advanced_*      — wOBA / wRC+ / FIP / SIERA per season
  - streak_history                  — decoded streak rows with names
  - f_record_*                      — career / season / franchise records
  - f_award_career / f_award_franchise

Build pattern: L3 tables are full DROP/CREATE on every ingest (cheap; the
warehouse fits in memory). They depend on L1 / L2 already being current.

Build order matters: `f_trade_participant` must build before
`player_movements`, because the latter LEFT JOINs to it for trade attribution.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# f_trade_participant
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_trade_participant(con: duckdb.DuckDBPyConnection) -> int:
    """Long-format roster of every player who changed hands in a trade.

    `trade_event` stores each trade as one wide row with up to 10 player
    slots per side (`player_id_0_0..9`, `player_id_1_0..9`). This pivots
    that into one row per (trade × player), making downstream joins
    straightforward — particularly the `trade_id` attribution back into
    `player_movements`.

    Schema:
        trade_id     BIGINT  — `trade_event.message_id` (one per trade)
        trade_date   DATE
        player_id    BIGINT
        from_org_id  BIGINT  — MLB-level team the player was traded FROM
        to_org_id    BIGINT  — MLB-level team the player was traded TO
        side         INTEGER — 0 (was on team_id_0) or 1 (was on team_id_1)

    PK = (trade_id, player_id). Each player appears on at most one side
    of a given trade.

    Cash, draft picks, and IAFA cap are intentionally excluded — this is
    the *player*-participant surface. Add `f_trade_pick` etc. later if
    we ever want pick-flow analysis.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_trade_participant AS
        WITH side_0 AS (
            SELECT
                message_id  AS trade_id,
                date        AS trade_date,
                team_id_0   AS from_org_id,
                team_id_1   AS to_org_id,
                CAST(0 AS INTEGER) AS side,
                player_id
            FROM trade_event,
                 UNNEST([
                     player_id_0_0, player_id_0_1, player_id_0_2, player_id_0_3,
                     player_id_0_4, player_id_0_5, player_id_0_6, player_id_0_7,
                     player_id_0_8, player_id_0_9
                 ]) AS t(player_id)
            WHERE player_id > 0
        ),
        side_1 AS (
            SELECT
                message_id, date,
                team_id_1, team_id_0,
                CAST(1 AS INTEGER),
                player_id
            FROM trade_event,
                 UNNEST([
                     player_id_1_0, player_id_1_1, player_id_1_2, player_id_1_3,
                     player_id_1_4, player_id_1_5, player_id_1_6, player_id_1_7,
                     player_id_1_8, player_id_1_9
                 ]) AS t(player_id)
            WHERE player_id > 0
        )
        SELECT * FROM side_0
        UNION ALL
        SELECT * FROM side_1
    """)
    con.execute(
        "ALTER TABLE f_trade_participant ADD PRIMARY KEY (trade_id, player_id)"
    )
    return con.execute("SELECT COUNT(*) FROM f_trade_participant").fetchone()[0]


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

    Trade attribution: `team_change` rows are LEFT JOINed to
    `f_trade_participant` and stamped with a `trade_id` when the player +
    org-level from/to teams + a near-window date all line up. ~2.5% of
    `team_change` rows resolve to a trade (the rest are intra-org promotions
    / demotions); ~99.8% of trade participants get matched on the trade
    side. Three structural caveats:

      - Org match uses `parent_team_id` to roll AAA/AA/A/etc. teams up to
        their MLB parent, since trades are recorded at MLB-org level but
        the actual player snapshot may show a farm-team `team_id`.
      - Window is ±60 days around `dump_date_observed`. Dumps are labeled
        with the 1st of the month but capture end-of-month state, so a
        trade on the 30th typically shows up in the dump labeled the 1st
        of that same month.
      - `trade_id` is `NULL` for non-trade `team_change` rows
        (waiver claims, releases, intra-org moves).

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
        ),
        all_movements AS (
            SELECT * FROM snapshot_movements
            UNION ALL
            SELECT * FROM draft_movements
        ),
        -- Roll farm-team team_ids up to their MLB-org team_id for trade matching.
        -- A trade between Boston (4) and Cleveland (10) moves players whose
        -- snapshot may show them on Worcester (35, parent=4) or Akron etc.
        team_orgs AS (
            SELECT team_id,
                   COALESCE(NULLIF(parent_team_id, 0), team_id) AS org_id
            FROM teams
        ),
        -- LEFT JOIN team_change rows to f_trade_participant; pick the
        -- single best-matching trade (closest by date) when there's any
        -- ambiguity. Org-rolled from-team and to-team must both line up
        -- with the trade sides; observation must be within 60 days of
        -- the trade date (dumps label as 1st-of-month but capture
        -- end-of-month state, so a trade on the 30th of a month shows
        -- up in the dump labeled the 1st of that same month).
        attributed AS (
            SELECT
                m.*,
                tp.trade_id,
                ROW_NUMBER() OVER (
                    PARTITION BY m.player_id, m.dump_date_observed,
                                 m.from_team_id, m.to_team_id
                    ORDER BY ABS(tp.trade_date - m.dump_date_observed) NULLS LAST
                ) AS _rn
            FROM all_movements m
            LEFT JOIN team_orgs fo ON fo.team_id = m.from_team_id
            LEFT JOIN team_orgs t_ ON t_.team_id = m.to_team_id
            LEFT JOIN f_trade_participant tp
                   ON m.movement_type = 'team_change'
                  AND tp.player_id    = m.player_id
                  AND tp.from_org_id  = fo.org_id
                  AND tp.to_org_id    = t_.org_id
                  AND tp.trade_date BETWEEN m.dump_date_observed - INTERVAL '60' DAY
                                        AND m.dump_date_observed + INTERVAL '60' DAY
        )
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY player_id, dump_date_observed, source
            ) AS movement_id,
            player_id,
            dump_date_observed,
            movement_type,
            from_team_id,
            to_team_id,
            from_level_id,
            to_level_id,
            source,
            draft_year,
            draft_round,
            draft_overall_pick,
            trade_id
        FROM attributed
        WHERE _rn = 1
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
    """Build all L3 derived tables.

    Build order:
      1. f_trade_participant   (from trade_event)
      2. player_movements      (LEFT JOINs to f_trade_participant for trade_id)

    Requires L1 (players_snapshot, teams, trade_event) to be present.

    Returns dict of `{l3_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    n = _build_f_trade_participant(con)
    rows["f_trade_participant"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_trade_participant             "
            f"[dim]{n:>10,} rows  PK=(trade_id, player_id)[/dim]"
        )

    n = _build_player_movements(con)
    rows["player_movements"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] player_movements                "
            f"[dim]{n:>10,} rows  PK=(movement_id)[/dim]"
        )

    return rows
