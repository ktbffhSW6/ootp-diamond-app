"""L2 facts — analytical-grain fact tables built from L1.

Each L2 table answers one well-defined question at one well-defined grain:

  f_player_season_batting    one row per (player, year, level, league, split, team)
  f_player_season_pitching   same shape
  f_player_season_fielding   + position
  f_player_career            one row per player — counting stats only (D11)

  f_team_season              one row per (team, year)
  f_league_season            one row per (league, year, level) — equivalent to
                             the league_constants view but materialized

  f_pa_event                 one row per PA, with dimensional flatten
                             (year, league_id, level_id, opp_team_id pre-joined)

  f_award_event              one row per (player, year, award_id, ...) with
                             league/team context for queries.

Aggregation strategy: L1 event tables for career stats have OOTP-source dups
within their natural key (per Phase C investigation). L2 collapses those by
SUMming all stat cols when grouped by the natural key. This is the same
aggregation pattern reconcile.py uses in the audit (`SUM(g) AS g, SUM(pa) AS
pa, ...`) — verified-correct against IE files for current-save players.

DuckDB's `COLUMNS(* EXCLUDE)` macro lets us SUM every non-key column in one
expression instead of writing out 30+ explicit SUMs per table.

Per Decision D11 — multi-level players keep separate rows per
`(player_id, year, level_id)`. `f_player_career` is the only place we sum
across levels, and it's restricted to pure counting stats (HR, IP, games)
where cross-level addition is meaningful.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Player-season facts (3 split-by-stat-type tables per OPEN-6)
# ─────────────────────────────────────────────────────────────────────────────


# Counting-stat column lists per source — used both for SUM aggregation and
# (informationally) to document what each fact carries.
_BATTING_NON_KEY_COLS = (
    # natural key: (player_id, year, league_id, level_id, split_id, team_id)
    # all other columns get SUM'd. game_id / position / stint / dump_date /
    # file_seq are excluded because they're either bookkeeping or dim-keys
    # we already aggregated away.
    "game_id, position, stint, dump_date, file_seq"
)
_PITCHING_NON_KEY_COLS = "game_id, stint, dump_date, file_seq"
_FIELDING_NON_KEY_COLS = "dump_date, file_seq"  # position stays — it's part of the key


def _build_f_player_season_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, level, league, split, team) batting counting stats."""
    con.execute(f"""
        CREATE OR REPLACE TABLE f_player_season_batting AS
        SELECT
            player_id, year, league_id, level_id, split_id, team_id,
            SUM(COLUMNS(* EXCLUDE (
                player_id, year, league_id, level_id, split_id, team_id,
                {_BATTING_NON_KEY_COLS}
            )))
        FROM players_career_batting_event
        GROUP BY player_id, year, league_id, level_id, split_id, team_id
    """)
    con.execute("""
        ALTER TABLE f_player_season_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id, split_id, team_id)
    """)
    return con.execute("SELECT COUNT(*) FROM f_player_season_batting").fetchone()[0]


def _build_f_player_season_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, level, league, split, team) pitching counting stats."""
    con.execute(f"""
        CREATE OR REPLACE TABLE f_player_season_pitching AS
        SELECT
            player_id, year, league_id, level_id, split_id, team_id,
            SUM(COLUMNS(* EXCLUDE (
                player_id, year, league_id, level_id, split_id, team_id,
                {_PITCHING_NON_KEY_COLS}
            )))
        FROM players_career_pitching_event
        GROUP BY player_id, year, league_id, level_id, split_id, team_id
    """)
    con.execute("""
        ALTER TABLE f_player_season_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id, split_id, team_id)
    """)
    return con.execute("SELECT COUNT(*) FROM f_player_season_pitching").fetchone()[0]


def _build_f_player_season_fielding(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, level, league, split, team, position) fielding counts."""
    con.execute(f"""
        CREATE OR REPLACE TABLE f_player_season_fielding AS
        SELECT
            player_id, year, league_id, level_id, split_id, team_id, position,
            SUM(COLUMNS(* EXCLUDE (
                player_id, year, league_id, level_id, split_id, team_id, position,
                {_FIELDING_NON_KEY_COLS}
            )))
        FROM players_career_fielding_event
        GROUP BY player_id, year, league_id, level_id, split_id, team_id, position
    """)
    con.execute("""
        ALTER TABLE f_player_season_fielding
        ADD PRIMARY KEY (player_id, year, league_id, level_id, split_id, team_id, position)
    """)
    return con.execute("SELECT COUNT(*) FROM f_player_season_fielding").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Player career rollup (D11 — counting stats only)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_player_career(con: duckdb.DuckDBPyConnection) -> int:
    """One row per player with cross-level COUNTING-stat totals (D11).

    Joins batting + pitching + fielding career totals. Rate stats and
    sabermetrics are L3 only; this table answers "career home runs" / "career
    games pitched" — questions that don't depend on context.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_player_career AS
        WITH bat AS (
            SELECT player_id,
                   SUM(g)   AS bat_g,    SUM(pa)  AS bat_pa,  SUM(ab) AS bat_ab,
                   SUM(h)   AS bat_h,    SUM(d)   AS bat_d,   SUM(t)  AS bat_t,
                   SUM(hr)  AS bat_hr,   SUM(r)   AS bat_r,   SUM(rbi) AS bat_rbi,
                   SUM(bb)  AS bat_bb,   SUM(k)   AS bat_k,
                   SUM(sb)  AS bat_sb,   SUM(cs)  AS bat_cs,
                   SUM(hp)  AS bat_hp,   SUM(sf)  AS bat_sf,  SUM(sh) AS bat_sh
            FROM f_player_season_batting
            WHERE split_id = 1   -- overall split only; sub-splits would double-count
            GROUP BY player_id
        ),
        pit AS (
            SELECT player_id,
                   SUM(g)   AS pit_g,    SUM(gs)  AS pit_gs,  SUM(outs) AS pit_outs,
                   SUM(w)   AS pit_w,    SUM(l)   AS pit_l,   SUM(s)    AS pit_sv,
                   SUM(k)   AS pit_k,    SUM(bb)  AS pit_bb,  SUM(ha)   AS pit_ha,
                   SUM(hra) AS pit_hra,  SUM(er)  AS pit_er,  SUM(bf)   AS pit_bf,
                   SUM(qs)  AS pit_qs,   SUM(cg)  AS pit_cg,  SUM(sho)  AS pit_sho,
                   SUM(hld) AS pit_hld
            FROM f_player_season_pitching
            WHERE split_id = 1
            GROUP BY player_id
        ),
        fld AS (
            SELECT player_id,
                   SUM(g)  AS fld_g,  SUM(gs) AS fld_gs,
                   SUM(po) AS fld_po, SUM(a)  AS fld_a,  SUM(e) AS fld_e,
                   SUM(dp) AS fld_dp
            FROM f_player_season_fielding
            WHERE split_id = 0   -- fielding has no platoon split; aggregate id 0
            GROUP BY player_id
        ),
        all_pids AS (
            SELECT player_id FROM bat
            UNION
            SELECT player_id FROM pit
            UNION
            SELECT player_id FROM fld
        )
        SELECT a.player_id,
               bat.* EXCLUDE (player_id),
               pit.* EXCLUDE (player_id),
               fld.* EXCLUDE (player_id)
        FROM all_pids a
        LEFT JOIN bat USING (player_id)
        LEFT JOIN pit USING (player_id)
        LEFT JOIN fld USING (player_id)
    """)
    con.execute("ALTER TABLE f_player_career ADD PRIMARY KEY (player_id)")
    return con.execute("SELECT COUNT(*) FROM f_player_career").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Team and league season facts
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_team_season(con: duckdb.DuckDBPyConnection) -> int:
    """Team-season totals — the standings layer.

    Pulls from team_history_event (which has W/L/RS/RA/playoff_position from
    OOTP) and joins team_history_record_event for any extra fields. PK is
    (team_id, year).
    """
    # team_history_event has natural PK at L1, so admin cols were already
    # excluded — pass through directly.
    con.execute("""
        CREATE OR REPLACE TABLE f_team_season AS
        SELECT * FROM team_history_event
    """)
    con.execute(
        "ALTER TABLE f_team_season ADD PRIMARY KEY (team_id, year)"
    )
    return con.execute("SELECT COUNT(*) FROM f_team_season").fetchone()[0]


def _build_f_league_season(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(league, year, level) totals — materialization of league_constants.

    Aggregates league_history_batting_event and league_history_pitching_event
    via SUM over (league_id, year, level_id) per D11. This is exactly what
    src/diamond/league_constants.py computes via SQL views; the L2 fact
    materializes the result so consumers don't repeat the aggregation.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_league_season AS
        WITH bat AS (
            SELECT league_id, year, level_id,
                   SUM(pa) AS lg_pa, SUM(ab) AS lg_ab, SUM(h) AS lg_h,
                   SUM(d)  AS lg_d,  SUM(t)  AS lg_t,  SUM(hr) AS lg_hr,
                   SUM(bb) AS lg_bb, SUM(hp) AS lg_hp, SUM(sf) AS lg_sf,
                   SUM(sh) AS lg_sh, SUM(k)  AS lg_k,
                   SUM(sb) AS lg_sb, SUM(cs) AS lg_cs,
                   ROUND((SUM(h) + SUM(bb) + SUM(hp))::DOUBLE
                       / NULLIF(SUM(ab) + SUM(bb) + SUM(hp) + SUM(sf), 0), 4) AS lg_obp,
                   ROUND(SUM(tb)::DOUBLE / NULLIF(SUM(ab), 0), 4) AS lg_slg
            FROM league_history_batting_event
            GROUP BY league_id, year, level_id
        ),
        pit AS (
            SELECT league_id, year, level_id,
                   ROUND(SUM(er)::DOUBLE * 9.0
                       / NULLIF(SUM(ip) + SUM(ipf)/3.0, 0), 3) AS lg_era,
                   SUM(ha)  AS lg_ha,  SUM(hra) AS lg_hra,
                   SUM(bb)  AS lg_pit_bb, SUM(hp) AS lg_pit_hp,
                   SUM(k)   AS lg_pit_k,  SUM(ab) AS lg_pit_ab,
                   SUM(bf)  AS lg_bf,
                   SUM(ip) + SUM(ipf)/3.0 AS lg_ip
            FROM league_history_pitching_event
            GROUP BY league_id, year, level_id
        )
        SELECT
            COALESCE(b.league_id, p.league_id) AS league_id,
            COALESCE(b.year, p.year)           AS year,
            COALESCE(b.level_id, p.level_id)   AS level_id,
            b.* EXCLUDE (league_id, year, level_id),
            p.* EXCLUDE (league_id, year, level_id)
        FROM bat b
        FULL OUTER JOIN pit p USING (league_id, year, level_id)
    """)
    con.execute(
        "ALTER TABLE f_league_season ADD PRIMARY KEY (league_id, year, level_id)"
    )
    return con.execute("SELECT COUNT(*) FROM f_league_season").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# PA-grain fact (the at-bat layer with dim flatten)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_pa_event(con: duckdb.DuckDBPyConnection) -> int:
    """Multi-year PA-grain fact, sourced from L0 with cross-dump dedup.

    PK = (year, game_id, batter_id, pa_in_game_seq).

    Why year is part of the PK: OOTP recycles ``game_id`` across seasons.
    Empirically, the integer 10001 is one game in dumps 2026-08 →
    2027-02 (67 PA rows), and a different game in dumps 2027-09 →
    2028-02 (73 rows). Within a single season ``game_id`` is unique;
    ``year`` (extracted from games.date) disambiguates the seasons.

    Cross-dump dedup: OOTP overwrites ``players_at_bat_batting_stats.csv``
    and ``games.csv`` at season rollover (Feb-Mar dump = spring training
    only). L0 retains every previously-ingested dump's rows by
    ``dump_date``, so historical seasons remain reachable; we just have
    to dedup. For each (game_id, season_year) we pick the latest
    ``dump_date`` that observed at-bats for it — that's the canonical
    scope for the game's PA log.

    Why this bypasses L1: ``at_bats_event`` and ``games_event`` are
    intentionally single-dump (latest). Reconcile.py needs that for
    per-dump comparison against IE roster CSVs. ``f_pa_event`` instead
    reaches back into L0 directly so the analytical layer can ask
    multi-year questions (situational splits, multi-year statcast
    cohorts, etc.). The two layers serve different audiences.

    Scope: filtered to scoped leagues via ``leagues`` (which is
    scope-trimmed at L1 build).
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_pa_event AS
        WITH ab_year AS (
            -- Pair each at-bat row with the games row from the SAME dump.
            -- (Both CSVs reset together at rollover, so same-dump JOIN is
            -- the only safe pairing.) Filter to scoped leagues here so
            -- subsequent stages aggregate over a smaller set.
            SELECT
                ab.dump_date,
                ab.game_id,
                ab.player_id,
                ab.opponent_player_id,
                ab.team_id,
                ab.inning, ab.outs,
                ab.balls, ab.strikes,
                ab.base1, ab.base2, ab.base3,
                ab."Close",
                ab.pinch, ab.run_diff, ab.spot,
                ab.result, ab.sac,
                ab.sb, ab.cs, ab.rbi, ab.r,
                ab.hit_loc, ab.hit_xy,
                ab.exit_velo, ab.launch_angle, ab.sprint_speed,
                ab.file_seq,
                EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) AS season_year,
                g.league_id,
                g.home_team, g.away_team, g.game_type
            FROM l0_players_at_bat_batting_stats ab
            JOIN l0_games g
                 ON g.game_id = ab.game_id
                AND g.dump_date = ab.dump_date
            WHERE g.league_id IN (SELECT league_id FROM leagues)
        ),
        canonical_dump AS (
            -- For each (game_id, season_year), pick the latest dump_date
            -- that observed it. After the Nov dump, the rows are stable;
            -- early-spring dumps trim the prior year's data, so MAX always
            -- gives us the fullest snapshot.
            SELECT game_id, season_year,
                   MAX(dump_date) AS canonical_dump_date
            FROM ab_year
            GROUP BY game_id, season_year
        ),
        canonical AS (
            SELECT aby.*
            FROM ab_year aby
            JOIN canonical_dump cd
                 ON cd.game_id            = aby.game_id
                AND cd.season_year        = aby.season_year
                AND cd.canonical_dump_date = aby.dump_date
        ),
        with_seq AS (
            -- Synthesize pa_in_game_seq within each (year, game, batter)
            -- group, ordered by file_seq (per OPEN-4 resolution — the
            -- CSV's row order is chronological within each batter's
            -- in-game PA list).
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY season_year, game_id, player_id
                    ORDER BY file_seq
                ) AS pa_in_game_seq
            FROM canonical
        )
        SELECT
            cab.game_id,
            cab.player_id              AS batter_id,
            cab.opponent_player_id     AS pitcher_id,
            cab.pa_in_game_seq,
            cab.team_id                AS batter_team_id,
            CASE
                WHEN cab.team_id = cab.home_team THEN cab.away_team
                ELSE cab.home_team
            END                       AS opp_team_id,
            cab.season_year            AS year,
            cab.league_id,
            -- games.csv has no level_id column — derive via teams.level
            -- through the batter's team.
            t.level                    AS level_id,
            cab.inning, cab.outs,
            cab.balls, cab.strikes,
            cab.base1, cab.base2, cab.base3,
            cab."Close"                AS close_flag,
            cab.pinch, cab.run_diff, cab.spot,
            cab.result, cab.sac,
            cab.sb, cab.cs, cab.rbi, cab.r,
            cab.hit_loc, cab.hit_xy,
            cab.exit_velo, cab.launch_angle, cab.sprint_speed,
            -- Derived flags (consolidated from advanced/enriched.py):
            (cab.result IN (4,5,6,7,8,9) AND cab.sac = 0) AS bip_flag,
            ((cab.base2 > 0 OR cab.base3 > 0) AND cab.outs < 3) AS risp_flag,
            (cab.inning >= 7 AND cab."Close" = 1) AS late_close_flag,
            -- game_type carried through so consumers can filter to
            -- regular season (game_type=0 per GameType.REGULAR_SEASON)
            -- without re-joining games.
            cab.game_type
        FROM with_seq cab
        LEFT JOIN teams t ON t.team_id = cab.team_id
    """)
    con.execute(
        "ALTER TABLE f_pa_event ADD PRIMARY KEY "
        "(year, game_id, batter_id, pa_in_game_seq)"
    )
    return con.execute("SELECT COUNT(*) FROM f_pa_event").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Awards fact (passthrough with synthetic PK preserved)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_award_event(con: duckdb.DuckDBPyConnection) -> int:
    """Awards passthrough — already has team_id/league_id from L1.

    L1 used synthetic PK (dump_date, file_seq). L2 keeps that since the
    natural key (player_id, year, award_id, ...) collides on
    multi-occurrence awards. Consumers query by (player_id, award_id) for
    career counts — see f_award_career in L3.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_award_event AS
        SELECT * FROM players_awards_event
    """)
    con.execute(
        "ALTER TABLE f_award_event ADD PRIMARY KEY (dump_date, file_seq)"
    )
    return con.execute("SELECT COUNT(*) FROM f_award_event").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l2(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build all L2 facts. Requires L1 event + snapshot tables.

    Returns dict of `{l2_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    builders = [
        ("f_player_season_batting",  _build_f_player_season_batting),
        ("f_player_season_pitching", _build_f_player_season_pitching),
        ("f_player_season_fielding", _build_f_player_season_fielding),
        ("f_player_career",          _build_f_player_career),
        ("f_team_season",            _build_f_team_season),
        ("f_league_season",          _build_f_league_season),
        ("f_pa_event",               _build_f_pa_event),
        ("f_award_event",            _build_f_award_event),
    ]

    for name, fn in builders:
        n = fn(con)
        rows[name] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {name:<30} [dim]{n:>10,} rows[/dim]"
            )

    return rows
