"""Tier 5 — terminal-count approach metrics.

Limited but useful — we only have the COUNT AT END OF PA, not the pitch sequence.
What we can derive:
  - Pitches per PA (overall, but redundant with OOTP's PI/PA)
  - Performance after reaching 2 strikes (PA where terminal strikes = 2)
  - Performance in even counts (terminal balls == terminal strikes) vs ahead/behind
  - Rate of 4-pitch walks (walk + balls=4 + strikes=0)
  - Rate of 3-pitch K (K + strikes=3 + balls=0)

NOTE: The "terminal count" interpretation is a proxy. A PA that ENDS at 0-0
just means the batter put the first pitch in play — it doesn't tell us about
preceding pitches in PAs that ended at higher counts. Use cautiously.
"""

from __future__ import annotations

import duckdb


def two_strike_performance(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Slash line in PAs that ended at 2 strikes (a proxy for "made the batter expand")."""
    return con.execute("""
        WITH agg AS (
            SELECT player_id,
                   COUNT(*) AS pa,
                   COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0) AS ab,
                   SUM(hit_flag) AS h, SUM(hr_flag) AS hr,
                   SUM(bb_flag) AS bb, SUM(k_flag) AS k, SUM(hbp_flag) AS hbp,
                   SUM(double_flag + triple_flag*2 + hr_flag*3) AS extra_bases
            FROM enriched_ab
            WHERE game_type = 0 AND strikes = 2
            GROUP BY player_id
        )
        SELECT player_id AS grp,
               pa, ab, h, hr, bb, k,
               ROUND(1.0 * h / NULLIF(ab, 0), 3) AS avg_2k,
               ROUND(1.0 * (h + bb + hbp) / NULLIF(ab + bb + hbp, 0), 3) AS obp_2k,
               ROUND(1.0 * (h + extra_bases) / NULLIF(ab, 0), 3) AS slg_2k
        FROM agg WHERE pa > 0
        ORDER BY pa DESC
    """).fetchall()


def count_state_splits(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Performance grouped by terminal count state.

    EVEN  = balls == strikes (0-0, 1-1, 2-2)
    AHEAD = balls > strikes (1-0, 2-0, 2-1, 3-0, 3-1, 3-2)
    BEHIND= strikes > balls (0-1, 0-2, 1-2)
    """
    return con.execute("""
        WITH classified AS (
            SELECT *,
                CASE
                  WHEN balls = strikes THEN 'EVEN'
                  WHEN balls > strikes THEN 'AHEAD'
                  ELSE 'BEHIND'
                END AS count_state
            FROM enriched_ab WHERE game_type = 0
        )
        SELECT player_id, count_state,
               COUNT(*) AS pa,
               SUM(hit_flag) AS h,
               COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0) AS ab,
               ROUND(1.0 * SUM(hit_flag)
                     / NULLIF(COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0), 0), 3) AS avg
        FROM classified
        GROUP BY player_id, count_state
        HAVING pa > 0
        ORDER BY player_id, count_state
    """).fetchall()


def four_pitch_walks_rate(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """% of walks that ended at exactly 4 balls / 0 strikes (no foul / contested pitches)."""
    return con.execute("""
        WITH agg AS (
            SELECT pitcher_id,
                   COUNT(*) FILTER (WHERE bb_flag = 1)                                AS bbs,
                   COUNT(*) FILTER (WHERE bb_flag = 1 AND balls = 4 AND strikes = 0)  AS four_pitch_bbs
            FROM enriched_ab WHERE game_type = 0 AND pitcher_id IS NOT NULL
            GROUP BY pitcher_id
        )
        SELECT pitcher_id AS grp,
               bbs, four_pitch_bbs,
               ROUND(100.0 * four_pitch_bbs / NULLIF(bbs, 0), 1) AS four_pitch_bb_rate
        FROM agg WHERE bbs >= 5
        ORDER BY four_pitch_bb_rate DESC
    """).fetchall()


def three_pitch_k_rate(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """% of strikeouts that ended at exactly 3 strikes / 0 balls (clean punchouts)."""
    return con.execute("""
        WITH agg AS (
            SELECT pitcher_id,
                   COUNT(*) FILTER (WHERE k_flag = 1)                                AS ks,
                   COUNT(*) FILTER (WHERE k_flag = 1 AND strikes = 3 AND balls = 0)  AS three_pitch_ks
            FROM enriched_ab WHERE game_type = 0 AND pitcher_id IS NOT NULL
            GROUP BY pitcher_id
        )
        SELECT pitcher_id AS grp,
               ks, three_pitch_ks,
               ROUND(100.0 * three_pitch_ks / NULLIF(ks, 0), 1) AS three_pitch_k_rate
        FROM agg WHERE ks >= 10
        ORDER BY three_pitch_k_rate DESC
    """).fetchall()
