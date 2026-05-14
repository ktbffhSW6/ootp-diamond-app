"""Phase 4b Tier B — per-dump SCD2 history snapshots (D40).

Builds per-(player, year, league, level, split, dump_date) counting-stat
tables that capture each player-season's stat line **at every monthly
dump** Diamond has ingested. Unlike the snapshot-forward pattern (capture
"now" on each build and accumulate), this approach **backfills the full
warehouse-history at every build** by GROUP BY-ing on dump_date over the
L1 event tables (which are themselves cumulative + cross-dump deduped at
the natural-key level but RETAIN dump_date as part of the synthetic PK).

Why backfill instead of snapshot-forward
----------------------------------------

OOTP's monthly dumps each contain the full career-stats-to-date for
every player. The L0 ingest stamps every row with `dump_date`, so the
L0 has an implicit per-dump time-series.

Snapshot-forward (the SCD2-classic pattern of "capture state on each
build, insert if changed") would only give us forward-looking sparklines
starting at the next ingest. Backfill gives us all 29 dumps of history
on the very first build that runs after this code lands — instant
trajectory data for every spotlight card.

Why source from L0 directly
---------------------------

The L1 event tables (``players_career_*_event``) collapse to
``MAX(dump_date)`` only — that's the cross-dump dedup pattern that
makes ``f_player_season_batting`` correct. They DON'T retain per-dump
history. So Tier B reads from ``l0_players_career_*_stats`` instead,
applying the same team-scope filter (D40 fix 2026-05-14 — captures
retired/released players whose stints on scoped teams would otherwise
drop).

Tables built
------------

f_player_season_batting_history    PK (player_id, year, league_id, level_id, split_id, dump_date)
                                    Counting line per player per league-level-split per dump.
                                    ~17M rows on Padres (29 dumps × 600K player-seasons).

f_player_season_pitching_history   PK same shape
                                    ~7M rows on Padres.

f_player_career_history            PK (player_id, dump_date)
                                    Career rollups (batting + pitching + fielding) per dump.
                                    ~3M rows on Padres.

Sparkline consumption
---------------------

For a player's career WAR trajectory:
  SELECT dump_date, bat_war FROM f_player_career_history
   WHERE player_id = ? ORDER BY dump_date

For per-(year, level) trajectories (e.g. "Merrill 2028 PA over the
season"):
  SELECT dump_date, pa FROM f_player_season_batting_history
   WHERE player_id = ? AND year = ? AND level_id = ? AND split_id = 1
   ORDER BY dump_date

Rate stats (AVG / OBP / SLG / ERA / WHIP) compute trivially from the
counting columns. Rate-stat history with league-constants context
(wOBA / wRC+ / OPS+ / FIP) is a Tier B v2 follow-up — needs per-dump
league constants which currently only exist for the latest dump.

Idempotency
-----------

DROP + CREATE pattern. Each rebuild reconstructs the full history from
L1 events (cheap — pure GROUP BY).
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


def _build_f_player_season_batting_history(
    con: duckdb.DuckDBPyConnection,
) -> int:
    """Per-dump counting line per (player, year, league, level, split).

    Sourced from L0 directly (``l0_players_career_batting_stats``) since
    the L1 event tables collapse to MAX(dump_date) only. Applies team-
    scope filter (D40 fix) to match the rest of the warehouse, and
    cross-stint dedup at the (player, year, team, league, level, split,
    stint, dump_date) grain — same OOTP-source dup pattern as the L1
    event spec notes (D17). Then GROUP BY collapses stints into the
    per-(season, dump) total.
    """
    sql = """
        DROP TABLE IF EXISTS f_player_season_batting_history;
        CREATE TABLE f_player_season_batting_history AS
        WITH dedup AS (
            SELECT
                player_id, year, league_id, level_id, split_id,
                dump_date, team_id, stint,
                pa, ab, h, d, t, hr, r, rbi, bb, ibb, hp, sf, sh, k, sb, cs, gdp, ci, g,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, year, team_id, league_id, level_id, split_id, stint, dump_date
                    ORDER BY file_seq DESC
                ) AS rn
            FROM l0_players_career_batting_stats
            WHERE TRY_CAST(team_id AS BIGINT) IN (SELECT team_id FROM _scoped_teams)
            QUALIFY rn = 1
        )
        SELECT
            player_id, year, league_id, level_id, split_id, dump_date,
            SUM(g)    AS g,
            SUM(pa)   AS pa,
            SUM(ab)   AS ab,
            SUM(h)    AS h,
            SUM(d)    AS d,
            SUM(t)    AS t,
            SUM(hr)   AS hr,
            SUM(r)    AS r,
            SUM(rbi)  AS rbi,
            SUM(bb)   AS bb,
            SUM(ibb)  AS ibb,
            SUM(hp)   AS hbp,
            SUM(sf)   AS sf,
            SUM(sh)   AS sh,
            SUM(k)    AS k,
            SUM(sb)   AS sb,
            SUM(cs)   AS cs,
            SUM(gdp)  AS gdp,
            SUM(ci)   AS ci
        FROM dedup
        GROUP BY player_id, year, league_id, level_id, split_id, dump_date
    """
    con.execute(sql)
    con.execute(
        "ALTER TABLE f_player_season_batting_history "
        "ADD PRIMARY KEY (player_id, year, league_id, level_id, split_id, dump_date)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_batting_history"
    ).fetchone()[0]


def _build_f_player_season_pitching_history(
    con: duckdb.DuckDBPyConnection,
) -> int:
    """Per-dump counting line for pitchers. Sources from L0 directly."""
    sql = """
        DROP TABLE IF EXISTS f_player_season_pitching_history;
        CREATE TABLE f_player_season_pitching_history AS
        WITH dedup AS (
            SELECT
                player_id, year, league_id, level_id, split_id,
                dump_date, team_id, stint,
                g, gs, w, l, s, hld, bs, qs, cg, sho,
                ip, ipf, outs, bf, ab, ha, r, er, bb, iw, k, hra, hp, gb, fb, pi, wp,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, year, team_id, league_id, level_id, split_id, stint, dump_date
                    ORDER BY file_seq DESC
                ) AS rn
            FROM l0_players_career_pitching_stats
            WHERE TRY_CAST(team_id AS BIGINT) IN (SELECT team_id FROM _scoped_teams)
            QUALIFY rn = 1
        )
        SELECT
            player_id, year, league_id, level_id, split_id, dump_date,
            SUM(g)    AS g,
            SUM(gs)   AS gs,
            SUM(w)    AS w,
            SUM(l)    AS l,
            SUM(s)    AS sv,
            SUM(hld)  AS hld,
            SUM(bs)   AS bs,
            SUM(qs)   AS qs,
            SUM(cg)   AS cg,
            SUM(sho)  AS sho,
            SUM(ip)   AS ip,
            SUM(ipf)  AS ipf,
            SUM(outs) AS outs,
            SUM(bf)   AS bf,
            SUM(ab)   AS ab,
            SUM(ha)   AS ha,
            SUM(r)    AS r,
            SUM(er)   AS er,
            SUM(bb)   AS bb,
            SUM(iw)   AS iw,
            SUM(k)    AS k,
            SUM(hra)  AS hra,
            SUM(hp)   AS hp,
            SUM(gb)   AS gb,
            SUM(fb)   AS fb,
            SUM(pi)   AS pi,
            SUM(wp)   AS wp
        FROM dedup
        GROUP BY player_id, year, league_id, level_id, split_id, dump_date
    """
    con.execute(sql)
    con.execute(
        "ALTER TABLE f_player_season_pitching_history "
        "ADD PRIMARY KEY (player_id, year, league_id, level_id, split_id, dump_date)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_pitching_history"
    ).fetchone()[0]


def _build_f_player_career_history(
    con: duckdb.DuckDBPyConnection,
) -> int:
    """One row per (player, dump_date) with career-total counting stats.

    Mirrors f_player_career (Phase 4a #2) but adds the dump_date axis
    so sparklines can show "career WAR over time". Built from the
    season-history tables grouped by (player, dump_date), so the per-
    dump season totals are aggregated up rather than re-computed.

    Matches f_player_career's split-id filtering: batting + pitching
    use split_id=1 (overall); fielding uses split_id=0.
    """
    sql = """
        DROP TABLE IF EXISTS f_player_career_history;
        CREATE TABLE f_player_career_history AS
        WITH bat AS (
            SELECT player_id, dump_date,
                   SUM(g)   AS bat_g,    SUM(pa)  AS bat_pa,  SUM(ab) AS bat_ab,
                   SUM(h)   AS bat_h,    SUM(d)   AS bat_d,   SUM(t)  AS bat_t,
                   SUM(hr)  AS bat_hr,   SUM(r)   AS bat_r,   SUM(rbi) AS bat_rbi,
                   SUM(bb)  AS bat_bb,   SUM(k)   AS bat_k,
                   SUM(sb)  AS bat_sb,   SUM(cs)  AS bat_cs,
                   SUM(hbp) AS bat_hbp,  SUM(sf)  AS bat_sf,  SUM(sh) AS bat_sh
            FROM f_player_season_batting_history
            WHERE split_id = 1
            GROUP BY player_id, dump_date
        ),
        pit AS (
            SELECT player_id, dump_date,
                   SUM(g)   AS pit_g,    SUM(gs)  AS pit_gs,  SUM(outs) AS pit_outs,
                   SUM(w)   AS pit_w,    SUM(l)   AS pit_l,   SUM(sv)   AS pit_sv,
                   SUM(k)   AS pit_k,    SUM(bb)  AS pit_bb,  SUM(ha)   AS pit_ha,
                   SUM(hra) AS pit_hra,  SUM(er)  AS pit_er,  SUM(bf)   AS pit_bf,
                   SUM(qs)  AS pit_qs,   SUM(cg)  AS pit_cg,  SUM(sho)  AS pit_sho,
                   SUM(hld) AS pit_hld
            FROM f_player_season_pitching_history
            WHERE split_id = 1
            GROUP BY player_id, dump_date
        ),
        all_pids AS (
            SELECT player_id, dump_date FROM bat
            UNION
            SELECT player_id, dump_date FROM pit
        )
        SELECT a.player_id, a.dump_date,
               bat.* EXCLUDE (player_id, dump_date),
               pit.* EXCLUDE (player_id, dump_date)
        FROM all_pids a
        LEFT JOIN bat USING (player_id, dump_date)
        LEFT JOIN pit USING (player_id, dump_date)
    """
    con.execute(sql)
    con.execute(
        "ALTER TABLE f_player_career_history "
        "ADD PRIMARY KEY (player_id, dump_date)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_career_history"
    ).fetchone()[0]


def build_l2_history(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build per-dump history tables. Idempotent (DROP+CREATE).

    Returns ``{table_name: row_count}``.
    """
    out: dict[str, int] = {}
    for name, builder in (
        ("f_player_season_batting_history",  _build_f_player_season_batting_history),
        ("f_player_season_pitching_history", _build_f_player_season_pitching_history),
        ("f_player_career_history",          _build_f_player_career_history),
    ):
        n = builder(con)
        out[name] = n
        if verbose:
            console.print(f"  [green]✓[/green] {name:<40} [dim]{n:>10,} rows[/dim]")
    return out
