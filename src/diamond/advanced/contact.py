"""Tier 1 — modern contact-quality stats from at-bat events.

Each function takes a DuckDB connection and an optional player/group filter,
returns a Polars-ready list[dict] of (group_key, stat) rows.

Operates against the `enriched_ab` temp table built by `enriched.materialize_enriched_ab`.
"""

from __future__ import annotations

import duckdb


def hard_hit_pct(con: duckdb.DuckDBPyConnection, ev_threshold: int = 95,
                 group_by: str = "player_id") -> list[tuple]:
    """Hard Hit % = % of BIP with EV >= threshold (default 95 mph)."""
    return con.execute(f"""
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= ?) AS hard_hit,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= ?)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS hard_hit_pct
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING bip > 0
        ORDER BY hard_hit_pct DESC NULLS LAST
    """, [ev_threshold, ev_threshold]).fetchall()


def hard_hit_buckets(con: duckdb.DuckDBPyConnection, group_by: str = "player_id") -> list[tuple]:
    """% of BIP in 95+, 100+, 105+, 110+ mph buckets."""
    return con.execute(f"""
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= 95)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS pct_95plus,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= 100)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS pct_100plus,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= 105)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS pct_105plus,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= 110)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS pct_110plus
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING bip > 0
    """).fetchall()


def sweet_spot_pct(con: duckdb.DuckDBPyConnection, group_by: str = "player_id") -> list[tuple]:
    """Sweet Spot % = % of BIP with launch angle between 8° and 32°."""
    return con.execute(f"""
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND launch_angle BETWEEN 8 AND 32)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS sweet_spot_pct
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING bip > 0
        ORDER BY sweet_spot_pct DESC NULLS LAST
    """).fetchall()


def barrel_pct(con: duckdb.DuckDBPyConnection, group_by: str = "player_id") -> list[tuple]:
    """Barrel % using Statcast's expanding-window definition.

    Approximation:
      - EV ≥ 98 mph required
      - LA window expands as EV increases:
          EV 98 → LA 26-30°
          EV 99 → LA 25-31°
          per +1 mph EV: window widens by 1° each side
          capped at LA 8-50° for EV >= 116 mph
    """
    return con.execute(f"""
        WITH bip AS (
            SELECT *,
                CASE WHEN bip_flag = 1 AND exit_velo >= 98 THEN
                    -- LA must be within [low, high] for this EV
                    CASE WHEN launch_angle >= GREATEST(8.0, 26 - (exit_velo - 98))
                          AND launch_angle <= LEAST(50.0, 30 + (exit_velo - 98))
                         THEN 1 ELSE 0 END
                ELSE 0 END AS is_barrel
            FROM enriched_ab
        )
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               SUM(is_barrel)                      AS barrels,
               ROUND(100.0 * SUM(is_barrel) / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1)
                                                   AS barrel_pct
        FROM bip
        GROUP BY {group_by}
        HAVING bip > 0
        ORDER BY barrel_pct DESC NULLS LAST
    """).fetchall()


def squared_up_pct(con: duckdb.DuckDBPyConnection, group_by: str = "player_id") -> list[tuple]:
    """Squared-up % approximation = % of BIP whose EV is in the top decile of all BIP.

    Without per-pitch maximum-potential EV, we approximate by comparing each
    BIP's EV against the overall p90 EV (league-wide). A "squared up" ball is
    one where the batter made near-optimal contact relative to the league.
    """
    p90 = con.execute("""
        SELECT QUANTILE_CONT(exit_velo, 0.90)
        FROM enriched_ab WHERE bip_flag = 1 AND exit_velo > 0
    """).fetchone()[0]
    return con.execute(f"""
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= ?)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS squared_up_pct
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING bip > 0
        ORDER BY squared_up_pct DESC NULLS LAST
    """, [p90]).fetchall()


def avg_ev_by_bip_type(con: duckdb.DuckDBPyConnection,
                       group_by: str = "player_id") -> list[tuple]:
    """Average EV broken out by BIP category (GB / LD / FB), based on launch angle."""
    return con.execute(f"""
        SELECT {group_by} AS grp,
               ROUND(AVG(exit_velo) FILTER
                   (WHERE bip_flag=1 AND launch_angle < 10), 1)                AS ev_gb,
               ROUND(AVG(exit_velo) FILTER
                   (WHERE bip_flag=1 AND launch_angle BETWEEN 10 AND 25), 1)   AS ev_ld,
               ROUND(AVG(exit_velo) FILTER
                   (WHERE bip_flag=1 AND launch_angle > 25), 1)                AS ev_fb,
               ROUND(AVG(exit_velo) FILTER (WHERE bip_flag=1), 1)              AS ev_overall
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING COUNT(*) FILTER (WHERE bip_flag=1) > 0
    """).fetchall()


def spray_pct(con: duckdb.DuckDBPyConnection, group_by: str = "player_id") -> list[tuple]:
    """Pull / Center / Oppo % by handedness (uses spray_category from enriched_ab)."""
    return con.execute(f"""
        SELECT {group_by} AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1) AS bip,
               ROUND(100.0 * COUNT(*) FILTER (WHERE spray_category = 'Pull')
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS pull_pct,
               ROUND(100.0 * COUNT(*) FILTER (WHERE spray_category = 'Center')
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS cent_pct,
               ROUND(100.0 * COUNT(*) FILTER (WHERE spray_category = 'Oppo')
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS oppo_pct
        FROM enriched_ab
        GROUP BY {group_by}
        HAVING bip > 0
    """).fetchall()


def pitcher_contact_quality_allowed(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Pitcher version: EV-allowed, LA-allowed, HardHit%-allowed, Barrel%-allowed."""
    return con.execute("""
        WITH bip AS (
            SELECT pitcher_id, exit_velo, launch_angle, bip_flag,
                CASE WHEN bip_flag = 1 AND exit_velo >= 98
                      AND launch_angle >= GREATEST(8.0, 26 - (exit_velo - 98))
                      AND launch_angle <= LEAST(50.0, 30 + (exit_velo - 98))
                     THEN 1 ELSE 0 END AS is_barrel
            FROM enriched_ab WHERE pitcher_id IS NOT NULL
        )
        SELECT pitcher_id AS grp,
               COUNT(*) FILTER (WHERE bip_flag=1)                       AS bip_allowed,
               ROUND(AVG(exit_velo) FILTER (WHERE bip_flag=1), 1)       AS ev_allowed,
               ROUND(AVG(launch_angle) FILTER (WHERE bip_flag=1), 1)    AS la_allowed,
               ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag=1 AND exit_velo >= 95)
                     / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1) AS hardhit_pct_allowed,
               ROUND(100.0 * SUM(is_barrel) / NULLIF(COUNT(*) FILTER (WHERE bip_flag=1), 0), 1)
                                                                        AS barrel_pct_allowed
        FROM bip
        GROUP BY pitcher_id
        HAVING bip_allowed > 0
    """).fetchall()
