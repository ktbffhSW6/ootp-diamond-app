"""L2 game-grain fact tables (Phase 4b Tier A, D40).

Per-(player, year, game) batting + pitching stat lines, sourced from
OOTP's monthly cumulative game logs and JOINed to a deduplicated game
header for per-game date denormalization.

Unblocks: rolling windows (last 7 / 15 / 30), calendar heatmaps, streak
engine, Phase 5 stretch comparator.

Tables built
------------

f_player_game_batting     PK (player_id, year, game_id)
                          One row per scoped batter game appearance,
                          full counting line (PA / AB / H / 2B / 3B / HR /
                          R / RBI / BB / K / HBP / SF / SH / SB / CS / GIDP),
                          plus level_id / league_id / team_id / position /
                          date. ~7.8M L0 rows → ~250K post-dedup (cumulative
                          dumps collapse to latest snapshot per game).

f_player_game_pitching    PK (player_id, year, game_id)
                          One row per scoped pitcher game appearance,
                          full counting line (IP outs / BF / H / R / ER /
                          BB / K / HR allowed / WP / HBP / W / L / S / BS /
                          HLD / GS), plus level_id / league_id / team_id /
                          date. split_id=1 filter (overall — not per-platoon).

Dedup pattern
-------------

OOTP records the same game-row in every monthly dump containing that
game's date — so a March game appears in March, April, May, ... up to
29 dumps in the Padres save. The latest dump's row is canonical. We
dedupe by `ROW_NUMBER() OVER (PARTITION BY natural_key ORDER BY
dump_date DESC) = 1`, same pattern as `f_pa_event` (D17 / 2026-05-12).

PK design
---------

`(year, game_id, player_id)` is the natural key. `year` is required in
the key because OOTP recycles `game_id` across seasons (verified in the
f_pa_event D17 finding). For pitching, `split_id=1` is enforced in the
ingest filter.

Date denormalization
--------------------

`date DATE` is JOINed in from a deduplicated `l0_games` CTE. The L1
`games_event` view is scoped to a 1.3-year window + a single
dump_date — too narrow for game-grain facts spanning 2026-2028. We
read directly from L0 with our own dedup.

Scope
-----

The L0 game tables include every league (DSL, MLB, MiLB, foreign winter,
etc.). We don't filter to org-roster — game-grain queries should be
able to look at any player's game log, including trade-partner stars
or call-ups not currently on the org. Per-team queries downstream
filter by team_id; rolling-window queries filter by player_id.

Idempotency
-----------

DROP + CREATE pattern. Cheap to rebuild — the dedup CTE runs in DuckDB
window functions in <10s on the Padres warehouse.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


def _build_f_player_game_batting(con: duckdb.DuckDBPyConnection) -> int:
    """One row per (player_id, year, game_id) — full batting line.

    Sourced from `l0_players_game_batting` filtered to `split_id=0` (the
    overall game-line, no platoon split for game-grain). Dedupes across
    dumps via ROW_NUMBER + latest dump_date. JOINs to a deduplicated
    `l0_games` CTE for `date`.

    DuckDB native ORDER BY in CTAS physically sorts the new table by
    `(player_id, date)` — sequential scans for player-game-log queries
    return contiguous storage rows.
    """
    sql = """
        DROP TABLE IF EXISTS f_player_game_batting;
        CREATE TABLE f_player_game_batting AS
        WITH games_dedup AS (
            -- Latest-dump row per (year, game_id). game_id recycles across
            -- years so the partition key must include year.
            SELECT
                game_id,
                EXTRACT(YEAR FROM date)::INT AS year,
                date,
                league_id,
                game_type,
                home_team,
                away_team,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, EXTRACT(YEAR FROM date)
                    ORDER BY dump_date DESC
                ) AS rn
            FROM l0_games
            QUALIFY rn = 1
        ),
        bat_dedup AS (
            -- Latest-dump row per (player_id, year, game_id, split_id=0).
            -- split_id is 0 throughout the table (game-grain has no platoon).
            SELECT
                player_id,
                year,
                game_id,
                team_id,
                league_id,
                level_id,
                position,
                pa, ab, h, d, t, hr,
                r, rbi, bb, k, hp, sb, cs,
                pitches_seen,
                dump_date,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, year, game_id
                    ORDER BY dump_date DESC
                ) AS rn
            FROM l0_players_game_batting
            WHERE split_id = 0
            QUALIFY rn = 1
        )
        SELECT
            b.player_id,
            b.year,
            b.game_id,
            g.date,
            b.team_id,
            b.league_id,
            b.level_id,
            CAST(g.game_type AS INTEGER)              AS game_type,
            CAST(b.position  AS INTEGER)              AS position,
            CAST(b.pa            AS INTEGER)          AS pa,
            CAST(b.ab            AS INTEGER)          AS ab,
            CAST(b.h             AS INTEGER)          AS h,
            CAST(b.d             AS INTEGER)          AS d,
            CAST(b.t             AS INTEGER)          AS t,
            CAST(b.hr            AS INTEGER)          AS hr,
            CAST(b.r             AS INTEGER)          AS r,
            CAST(b.rbi           AS INTEGER)          AS rbi,
            CAST(b.bb            AS INTEGER)          AS bb,
            CAST(b.k             AS INTEGER)          AS k,
            CAST(b.hp            AS INTEGER)          AS hbp,
            CAST(b.sb            AS INTEGER)          AS sb,
            CAST(b.cs            AS INTEGER)          AS cs,
            CAST(b.pitches_seen  AS INTEGER)          AS pitches_seen,
            b.dump_date                               AS source_dump_date
        FROM bat_dedup b
        JOIN games_dedup g
          ON g.game_id = b.game_id AND g.year = b.year
        ORDER BY b.player_id, g.date
    """
    con.execute(sql)
    con.execute(
        "ALTER TABLE f_player_game_batting "
        "ADD PRIMARY KEY (player_id, year, game_id)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_game_batting"
    ).fetchone()[0]


def _build_f_player_game_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """One row per (player_id, year, game_id) — full pitching line.

    Sourced from `l0_players_game_pitching_stats` filtered to
    `split_id=1` (overall pitching — the others are vs-LHP / vs-RHP
    breakdowns and per-pitch counts). Dedupes across dumps + JOINs to
    deduplicated `l0_games` for `date`.

    IP is stored as outs (integer) — display computation
    (`outs/3 + (outs%3)*0.1`) happens in the API layer per D11.
    """
    sql = """
        DROP TABLE IF EXISTS f_player_game_pitching;
        CREATE TABLE f_player_game_pitching AS
        WITH games_dedup AS (
            SELECT
                game_id,
                EXTRACT(YEAR FROM date)::INT AS year,
                date,
                league_id,
                game_type,
                home_team,
                away_team,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, EXTRACT(YEAR FROM date)
                    ORDER BY dump_date DESC
                ) AS rn
            FROM l0_games
            QUALIFY rn = 1
        ),
        pit_dedup AS (
            SELECT
                player_id,
                year,
                game_id,
                team_id,
                league_id,
                level_id,
                ip                            AS outs,
                bf, ab, ha AS h, rs AS r, er,
                bb, k, hra AS hr_allowed,
                wp, hp AS hbp_against,
                gb, fb, pi AS pitches_thrown,
                gs, w, l, s AS sv, bs, hld,
                dump_date,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, year, game_id
                    ORDER BY dump_date DESC
                ) AS rn
            FROM l0_players_game_pitching_stats
            WHERE split_id = 1
            QUALIFY rn = 1
        )
        SELECT
            p.player_id,
            p.year,
            p.game_id,
            g.date,
            p.team_id,
            p.league_id,
            p.level_id,
            CAST(g.game_type AS INTEGER)                   AS game_type,
            CAST(p.outs            AS INTEGER)             AS outs,
            CAST(p.bf              AS INTEGER)             AS bf,
            CAST(p.ab              AS INTEGER)             AS ab,
            CAST(p.h               AS INTEGER)             AS h,
            CAST(p.r               AS INTEGER)             AS r,
            CAST(p.er              AS INTEGER)             AS er,
            CAST(p.bb              AS INTEGER)             AS bb,
            CAST(p.k               AS INTEGER)             AS k,
            CAST(p.hr_allowed      AS INTEGER)             AS hr_allowed,
            CAST(p.wp              AS INTEGER)             AS wp,
            CAST(p.hbp_against     AS INTEGER)             AS hbp_against,
            CAST(p.gb              AS INTEGER)             AS gb,
            CAST(p.fb              AS INTEGER)             AS fb,
            CAST(p.pitches_thrown  AS INTEGER)             AS pitches_thrown,
            CAST(p.gs              AS INTEGER)             AS gs,
            CAST(p.w               AS INTEGER)             AS w,
            CAST(p.l               AS INTEGER)             AS l,
            CAST(p.sv              AS INTEGER)             AS sv,
            CAST(p.bs              AS INTEGER)             AS bs,
            CAST(p.hld             AS INTEGER)             AS hld,
            p.dump_date                                    AS source_dump_date
        FROM pit_dedup p
        JOIN games_dedup g
          ON g.game_id = p.game_id AND g.year = p.year
        ORDER BY p.player_id, g.date
    """
    con.execute(sql)
    con.execute(
        "ALTER TABLE f_player_game_pitching "
        "ADD PRIMARY KEY (player_id, year, game_id)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_game_pitching"
    ).fetchone()[0]


def build_l2_game_grain(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build the game-grain fact tables. Idempotent (DROP+CREATE).

    Returns ``{table_name: row_count}``.
    """
    out: dict[str, int] = {}
    for name, builder in (
        ("f_player_game_batting",  _build_f_player_game_batting),
        ("f_player_game_pitching", _build_f_player_game_pitching),
    ):
        n = builder(con)
        out[name] = n
        if verbose:
            console.print(f"  [green]✓[/green] {name:<35} [dim]{n:>10,} rows[/dim]")
    return out
