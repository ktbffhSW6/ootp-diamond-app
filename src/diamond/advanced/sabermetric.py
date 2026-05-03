"""Tier 3 — sabermetric stats requiring league constants.

Includes:
  - wOBA, wRAA, wRC, wRC+
  - OPS+ (using league OPS + park factor)
  - ERA+ (using league ERA + park factor)
  - Power-Speed Number (PSN)
  - Speed Score (Bill James composite)
  - isoP (already SLG-AVG), isoD (OBP-AVG)
  - Custom WAR (pos players: oWAR + dWAR vs replacement)

All functions take (con, league_constants) where league_constants is the
LeagueConstants dataclass from `league_constants.py`. They operate on
career_bat / career_pit / career_field tables — split_id=1 (overall) for
year+league scope.
"""

from __future__ import annotations

import duckdb

from diamond.advanced.league_constants import LeagueConstants


def woba_per_player(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """Player wOBA, wRAA, wRC, wRC+ for the given league-year."""
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
                   SUM(d) AS d, SUM(t) AS t, SUM(hr) AS hr,
                   SUM(bb) AS bb, SUM(ibb) AS ibb, SUM(hp) AS hp,
                   SUM(sf) AS sf,
                   (SUM(h) - SUM(d) - SUM(t) - SUM(hr)) AS singles
            FROM career_bat
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT
            player_id AS grp,
            pa,
            ROUND(
                ({lc.wBB}*(bb-ibb) + {lc.wHBP}*hp + {lc.w1B}*singles
                 + {lc.w2B}*d + {lc.w3B}*t + {lc.wHR}*hr)
                / NULLIF(ab + bb - ibb + sf + hp, 0), 4
            ) AS woba,
            ROUND(
                ((({lc.wBB}*(bb-ibb) + {lc.wHBP}*hp + {lc.w1B}*singles
                  + {lc.w2B}*d + {lc.w3B}*t + {lc.wHR}*hr)
                 / NULLIF(ab + bb - ibb + sf + hp, 0))
                 - {lc.lg_woba}) / {lc.woba_scale} * pa, 1
            ) AS wRAA,
            ROUND(
                (
                  ((({lc.wBB}*(bb-ibb) + {lc.wHBP}*hp + {lc.w1B}*singles
                    + {lc.w2B}*d + {lc.w3B}*t + {lc.wHR}*hr)
                   / NULLIF(ab + bb - ibb + sf + hp, 0))
                   - {lc.lg_woba}) / {lc.woba_scale}
                  + {lc.runs_per_pa}
                ) * pa, 1
            ) AS wRC,
            ROUND(
                100.0 * (
                    ((({lc.wBB}*(bb-ibb) + {lc.wHBP}*hp + {lc.w1B}*singles
                      + {lc.w2B}*d + {lc.w3B}*t + {lc.wHR}*hr)
                     / NULLIF(ab + bb - ibb + sf + hp, 0))
                     - {lc.lg_woba}) / {lc.woba_scale}
                    + {lc.runs_per_pa}
                ) / NULLIF({lc.runs_per_pa}, 0), 0
            ) AS wRCplus
        FROM agg
        WHERE pa > 0
        ORDER BY wRC DESC
    """).fetchall()


def ops_plus_per_player(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1).

    Park-neutral version (would need park factor join for full OPS+).
    """
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
                   SUM(d) AS d, SUM(t) AS t, SUM(hr) AS hr,
                   SUM(bb) AS bb, SUM(hp) AS hp, SUM(sf) AS sf,
                   ROUND(1.0 * (SUM(h) + SUM(bb) + SUM(hp))
                         / NULLIF(SUM(ab) + SUM(bb) + SUM(hp) + SUM(sf), 0), 4) AS obp,
                   ROUND(1.0 * (SUM(h) + SUM(d) + 2*SUM(t) + 3*SUM(hr))
                         / NULLIF(SUM(ab), 0), 4) AS slg
            FROM career_bat
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT player_id AS grp, pa, obp, slg,
               ROUND(100.0 * (obp / {lc.lg_obp} + slg / {lc.lg_slg} - 1), 0) AS ops_plus
        FROM agg
        WHERE pa > 0
        ORDER BY ops_plus DESC
    """).fetchall()


def era_plus_per_pitcher(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """ERA+ = 100 * lgERA / playerERA  (park-neutral)."""
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id, SUM(outs) AS outs, SUM(er) AS er
            FROM career_pit
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT player_id AS grp,
               ROUND(outs / 3.0, 1) AS ip,
               ROUND(9.0 * er / NULLIF(outs/3.0, 0), 2) AS era,
               ROUND(100.0 * {lc.lg_era} / NULLIF(9.0 * er / NULLIF(outs/3.0, 0), 0), 0) AS era_plus
        FROM agg
        WHERE outs >= 30   -- 10+ IP minimum
        ORDER BY era_plus DESC
    """).fetchall()


def fip_per_pitcher(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """FIP = (13·HR + 3·(BB+HBP) - 2·K) / IP  +  cFIP."""
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   SUM(outs) AS outs, SUM(hra) AS hra,
                   SUM(bb) AS bb, SUM(hp) AS hp, SUM(k) AS k
            FROM career_pit
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT player_id AS grp,
               ROUND(outs / 3.0, 1) AS ip,
               ROUND((13.0*hra + 3.0*(bb+hp) - 2.0*k) / NULLIF(outs/3.0, 0)
                     + {lc.fip_constant}, 2) AS fip
        FROM agg
        WHERE outs >= 30
        ORDER BY fip
    """).fetchall()


def power_speed_number(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """Power-Speed Number = 2·HR·SB / (HR+SB).  20-20 hitters get ~20."""
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id, SUM(hr) AS hr, SUM(sb) AS sb
            FROM career_bat
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT player_id AS grp, hr, sb,
               ROUND(2.0 * hr * sb / NULLIF(hr + sb, 0), 1) AS psn
        FROM agg
        WHERE hr + sb > 0
        ORDER BY psn DESC
    """).fetchall()


def speed_score(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """Bill James Speed Score: composite of SB%, freq of attempts, 3B rate, R/(H+BB-HR), GIDP rate.

    Five 0-10 components averaged. Implementation simplified — uses three of
    the five components (SB%, 3B/PA, GIDP avoidance) as our dump has the data
    for all but accurate baserunning attempt count.
    """
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id, SUM(pa) AS pa, SUM(ab) AS ab,
                   SUM(sb) AS sb, SUM(cs) AS cs, SUM(t) AS t,
                   SUM(gdp) AS gdp, SUM(h) AS h, SUM(bb) AS bb, SUM(hr) AS hr
            FROM career_bat
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        ),
        components AS (
            SELECT player_id, pa, sb, cs, t, gdp,
                   -- SB% component (0-10)
                   GREATEST(0.0, LEAST(10.0,
                       (1.0 * sb / NULLIF(sb + cs, 0) - 0.5) * 50.0
                   )) AS sb_pct_score,
                   -- Triples rate component (0-10)
                   GREATEST(0.0, LEAST(10.0,
                       1.0 * t / NULLIF(ab, 0) * 1000.0
                   )) AS triples_score,
                   -- GIDP avoidance component (0-10) — fewer GDP per opportunity
                   GREATEST(0.0, LEAST(10.0,
                       10.0 - 1.0 * gdp / NULLIF(h + bb - hr, 0) * 100.0
                   )) AS gidp_score
            FROM agg
            WHERE pa > 0
        )
        SELECT player_id AS grp,
               ROUND((sb_pct_score + triples_score + gidp_score) / 3.0, 1) AS speed_score
        FROM components
        ORDER BY speed_score DESC
    """).fetchall()


def iso_d_p(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """isoP = SLG - AVG.  isoD = OBP - AVG."""
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
                   SUM(d) AS d, SUM(t) AS t, SUM(hr) AS hr,
                   SUM(bb) AS bb, SUM(hp) AS hp, SUM(sf) AS sf
            FROM career_bat
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        )
        SELECT player_id AS grp,
               pa,
               ROUND(1.0 * h / NULLIF(ab, 0), 3) AS avg,
               ROUND(1.0 * (h + d + 2*t + 3*hr) / NULLIF(ab, 0), 3) AS slg,
               ROUND(1.0 * (h + bb + hp) / NULLIF(ab + bb + hp + sf, 0), 3) AS obp,
               ROUND(1.0 * (d + 2*t + 3*hr) / NULLIF(ab, 0), 3) AS iso_p,
               ROUND(1.0 * (h + bb + hp) / NULLIF(ab + bb + hp + sf, 0)
                     - 1.0 * h / NULLIF(ab, 0), 3) AS iso_d
        FROM agg
        WHERE pa > 0
    """).fetchall()
