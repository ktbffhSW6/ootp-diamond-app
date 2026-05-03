"""Tier 4 — defensive stats beyond what OOTP exports directly.

  - Range Factor (RF/9, RF/G) per position
  - Catcher Framing+ (calibrated against league average)
  - Outfield Assist Rate (assists per OF chance)

All operate on `career_field` for a given year + league scope.
"""

from __future__ import annotations

import duckdb


def range_factor(con: duckdb.DuckDBPyConnection, year: int, league_id: int) -> list[tuple]:
    """RF/9 and RF/G per (player, position).

    RF/9  = 9 * (PO + A) / IP
    RF/G  = (PO + A) / G
    """
    return con.execute("""
        SELECT player_id, position,
               g, po, a, ip,
               ROUND(1.0 * (po + a) / NULLIF(g, 0), 2) AS rf_per_g,
               ROUND(9.0 * (po + a) / NULLIF(ipf / 1000.0 + ip, 0), 2) AS rf_per_9
        FROM career_field
        WHERE year = ? AND league_id = ? AND split_id = 0
          AND g >= 10
        ORDER BY rf_per_9 DESC
    """, [year, league_id]).fetchall()


def catcher_framing_plus(con: duckdb.DuckDBPyConnection, year: int, league_id: int) -> list[tuple]:
    """Catcher Framing+ — relative to league-average catcher framing.

    Framing+ = 100 * (player_framing - lg_framing) / stdev_framing + 100

    Where framing is from career_field for catchers (position=2).
    """
    lg = con.execute("""
        SELECT AVG(framing) AS lg_avg, STDDEV_SAMP(framing) AS lg_std
        FROM career_field
        WHERE year = ? AND league_id = ? AND split_id = 0 AND position = 2
          AND ipf > 100   -- catchers with meaningful playing time
    """, [year, league_id]).fetchone()
    lg_avg, lg_std = (lg[0] or 0.0), (lg[1] or 1.0)
    return con.execute("""
        SELECT player_id,
               ROUND(g, 0) AS g, ROUND(framing, 1) AS framing,
               ROUND(100.0 + 10.0 * (framing - ?) / NULLIF(?, 0), 0) AS framing_plus
        FROM career_field
        WHERE year = ? AND league_id = ? AND split_id = 0 AND position = 2 AND g >= 20
        ORDER BY framing_plus DESC
    """, [lg_avg, lg_std, year, league_id]).fetchall()


def of_assist_rate(con: duckdb.DuckDBPyConnection, year: int, league_id: int) -> list[tuple]:
    """OF assists per 1000 innings (positions 7=LF, 8=CF, 9=RF)."""
    return con.execute("""
        SELECT player_id, position,
               g, a, po,
               ROUND(ipf / 1000.0 + ip, 1) AS ip_total,
               ROUND(1000.0 * a / NULLIF(ipf / 1000.0 + ip, 0), 2) AS asst_per_1000ip
        FROM career_field
        WHERE year = ? AND league_id = ? AND split_id = 0
          AND position IN (7, 8, 9)
          AND g >= 20
        ORDER BY asst_per_1000ip DESC
    """, [year, league_id]).fetchall()
