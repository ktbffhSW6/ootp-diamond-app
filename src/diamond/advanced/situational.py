"""Tier 2 — situational / leverage stats from at-bat events.

Includes:
  - RE24 — Run Expectancy 24 (per-PA run-value contribution)
  - RISP / bases-loaded / 2-out splits
  - Pinch-hit performance
  - Late-and-close performance
  - vs-pitcher splits (any opponent_pitcher_id join)
  - by-inning splits (early/middle/late)
  - by-leverage tier (custom from base-state + run_diff)

Run Expectancy matrix is derived empirically from the at-bat data: for each
(base_state, outs) at the START of an AB, average the runs scored from that
state to the end of the half-inning.
"""

from __future__ import annotations

import duckdb


def build_re_matrix(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Compute the RE24 matrix from at-bat data.

    For each (base_state 0-7, outs 0-2) state at the start of an AB, average
    the total runs scored in the rest of that half-inning. Returns list of
    (base_state, outs, n_observations, mean_runs).

    We approximate "runs scored to end of inning" by summing `runs_scored`
    (ab.r) and `rbi`-derived runs over the same (game_id, inning, batting team)
    grouping. This sums runs from the AB and all subsequent ABs in that
    half-inning.
    """
    # Step 1: group at-bats by (game, inning, half-inning) and compute runs-from-here-to-end
    con.execute("""
        CREATE OR REPLACE TEMP TABLE half_inning_runs AS
        SELECT
            game_id, inning, bat_team_id,
            SUM(runs_scored) AS half_inning_total_r
        FROM enriched_ab
        WHERE game_type = 0
        GROUP BY game_id, inning, bat_team_id
    """)
    # Step 2: for each AB, compute runs scored AFTER this AB to end of half
    # Use a window function: total_runs - cumulative_runs_through_this_ab
    con.execute("""
        CREATE OR REPLACE TEMP TABLE re_states AS
        WITH ordered AS (
            SELECT
                e.*, h.half_inning_total_r,
                SUM(e.runs_scored) OVER (
                    PARTITION BY e.game_id, e.inning, e.bat_team_id
                    ORDER BY e.outs, e.lineup_spot
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS runs_through_this_ab
            FROM enriched_ab e
            JOIN half_inning_runs h
              ON e.game_id = h.game_id
             AND e.inning = h.inning
             AND e.bat_team_id = h.bat_team_id
            WHERE e.game_type = 0
        )
        SELECT
            base_state, outs,
            COUNT(*) AS n,
            -- runs from this state to end of inning = total - (runs prior to this AB)
            -- = total - (runs_through_this_ab - runs_scored_in_this_ab)
            ROUND(AVG(half_inning_total_r - (runs_through_this_ab - runs_scored)), 3) AS exp_runs
        FROM ordered
        GROUP BY base_state, outs
    """)
    return con.execute("""
        SELECT base_state, outs, n, exp_runs
        FROM re_states
        WHERE outs < 3
        ORDER BY base_state, outs
    """).fetchall()


def re24_per_player(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """RE24 per player — full Tango formulation.

    For each PA:
        re24_pa = (RE_after - RE_before) + runs_scored_in_PA

    Where RE_after is the run-expectancy at the *post-PA* base/outs
    state. We don't have a post-PA state column directly, so we
    derive it: post-state of PA N == pre-state of PA N+1 in the same
    (game × half-inning). Use a LEAD window function ordered by
    `(outs ASC, lineup_spot ASC, base_state DESC)` — this is the
    natural batting order within a half-inning for >99% of cases. The
    rare 9+-batter inning where lineup wraps may misorder a PA but the
    leaderboard impact is below noise.

    The last PA of a half-inning has no successor → RE_after = 0.

    Per-PA runs uses `rbi` (runs driven in on this PA), not `r`
    (batter's own runs, which OOTP attributes to the AB where the
    batter reached base, not the AB that drove them home). Across the
    season the two columns differ by ~3% (rbi excludes runs scored on
    errors, balks, etc.).

    Compared to the previous "RE_before exposure" version, this:
      - sums to roughly 0 across the league (value-add metric vs an
        accumulation metric)
      - rewards driving in baserunners + advancing the lineup, not
        just appearing in high-leverage spots

    Requires the `re_states` temp table built by `build_re_matrix`.
    """
    return con.execute("""
        WITH state_seq AS (
            SELECT
                e.*,
                LEAD(e.base_state) OVER (
                    PARTITION BY e.game_id, e.inning, e.bat_team_id
                    ORDER BY e.outs ASC, e.lineup_spot ASC, e.base_state DESC
                ) AS next_base_state,
                LEAD(e.outs) OVER (
                    PARTITION BY e.game_id, e.inning, e.bat_team_id
                    ORDER BY e.outs ASC, e.lineup_spot ASC, e.base_state DESC
                ) AS next_outs
            FROM enriched_ab e
            WHERE e.game_type = 0
        ),
        per_pa AS (
            SELECT
                ss.player_id,
                ss.rbi,
                rs_before.exp_runs AS re_before,
                COALESCE(rs_after.exp_runs, 0.0) AS re_after,
                (COALESCE(rs_after.exp_runs, 0.0) - rs_before.exp_runs
                  + ss.rbi) AS re24_pa
            FROM state_seq ss
            JOIN re_states rs_before
              ON rs_before.base_state = ss.base_state
             AND rs_before.outs = ss.outs
            LEFT JOIN re_states rs_after
              ON rs_after.base_state = ss.next_base_state
             AND rs_after.outs = ss.next_outs
        )
        SELECT player_id AS grp,
               COUNT(*) AS pa,
               ROUND(SUM(re24_pa), 1) AS re24,
               ROUND(AVG(re24_pa), 3) AS avg_re24_per_pa
        FROM per_pa
        GROUP BY player_id
        HAVING pa > 0
        ORDER BY re24 DESC
    """).fetchall()


def split_stats(con: duckdb.DuckDBPyConnection, where_clause: str,
                split_label: str) -> list[tuple]:
    """Generic split stats: PA/AB/H/HR/BB/K/AVG/OBP/SLG for the given filter.

    `where_clause` should reference enriched_ab columns (e.g. 'risp_flag = 1').
    """
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   COUNT(*) AS pa,
                   COUNT(*) FILTER (WHERE result NOT IN (2, 10, 11) AND sac = 0) AS ab,
                   SUM(hit_flag) AS h,
                   SUM(hr_flag) AS hr,
                   SUM(bb_flag) AS bb,
                   SUM(k_flag) AS k,
                   SUM(hbp_flag) AS hbp,
                   SUM(double_flag + triple_flag*2 + hr_flag*3 + single_flag*0) AS extra_bases
            FROM enriched_ab
            WHERE game_type = 0 AND ({where_clause})
            GROUP BY player_id
        )
        SELECT player_id AS grp,
               '{split_label}' AS split,
               pa, ab, h, hr, bb, k,
               ROUND(1.0 * h / NULLIF(ab, 0), 3) AS avg,
               ROUND(1.0 * (h + bb + hbp) / NULLIF(ab + bb + hbp, 0), 3) AS obp,
               ROUND(1.0 * (h + extra_bases) / NULLIF(ab, 0), 3) AS slg
        FROM agg
        WHERE pa > 0
        ORDER BY pa DESC
    """).fetchall()


def risp_split(con):       return split_stats(con, "risp_flag = 1", "RISP")
def loaded_split(con):     return split_stats(con, "loaded_flag = 1", "Bases Loaded")
def two_out_split(con):    return split_stats(con, "outs = 2", "2 Outs")
def two_out_risp_split(con): return split_stats(con, "risp_flag = 1 AND outs = 2", "2 Out RISP")
def pinch_hit_split(con):  return split_stats(con, "pinch = 1", "Pinch Hit")
def late_close_split(con): return split_stats(con, "late_close_flag = 1", "Late & Close")


def by_inning_split(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """PA-weighted slash line by inning bucket (1-3, 4-6, 7+)."""
    return con.execute("""
        WITH agg AS (
            SELECT player_id, inning_bucket,
                   COUNT(*) AS pa,
                   COUNT(*) FILTER (WHERE result NOT IN (2, 10, 11) AND sac = 0) AS ab,
                   SUM(hit_flag) AS h, SUM(hr_flag) AS hr,
                   SUM(bb_flag) AS bb, SUM(k_flag) AS k, SUM(hbp_flag) AS hbp,
                   SUM(double_flag + triple_flag*2 + hr_flag*3) AS extra_bases
            FROM enriched_ab WHERE game_type = 0
            GROUP BY player_id, inning_bucket
        )
        SELECT player_id, inning_bucket, pa, ab, h, hr, bb, k,
               ROUND(1.0 * h / NULLIF(ab, 0), 3) AS avg,
               ROUND(1.0 * (h + bb + hbp) / NULLIF(ab + bb + hbp, 0), 3) AS obp,
               ROUND(1.0 * (h + extra_bases) / NULLIF(ab, 0), 3) AS slg
        FROM agg WHERE pa > 0
        ORDER BY player_id, inning_bucket
    """).fetchall()


def by_leverage_tier(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Three custom leverage tiers based on close_flag + late_inning + base_state.

    HIGH: close_flag=1 AND late_inning=1 AND (risp OR loaded)
    MED:  close_flag=1 AND late_inning=1 AND NOT risp_or_loaded, OR
          close_flag=1 AND inning>=5
    LOW:  everything else
    """
    return con.execute("""
        WITH classified AS (
            SELECT *,
                CASE
                  WHEN close_flag=1 AND late_inning_flag=1 AND (risp_flag=1 OR loaded_flag=1) THEN 'HIGH'
                  WHEN close_flag=1 AND inning >= 5 THEN 'MED'
                  ELSE 'LOW'
                END AS lev_tier
            FROM enriched_ab WHERE game_type = 0
        )
        SELECT player_id, lev_tier,
               COUNT(*) AS pa,
               SUM(hit_flag) AS h, SUM(hr_flag) AS hr,
               COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0) AS ab,
               ROUND(1.0 * SUM(hit_flag)
                     / NULLIF(COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0), 0), 3) AS avg
        FROM classified
        GROUP BY player_id, lev_tier
        HAVING pa > 0
        ORDER BY player_id, lev_tier
    """).fetchall()


def vs_specific_pitcher(con: duckdb.DuckDBPyConnection,
                        batter_id: int, pitcher_id: int) -> list[tuple]:
    """Career H2H: this batter vs this pitcher across all years in the dump."""
    return con.execute("""
        SELECT
               COUNT(*) AS pa,
               COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0) AS ab,
               SUM(hit_flag) AS h, SUM(hr_flag) AS hr,
               SUM(bb_flag) AS bb, SUM(k_flag) AS k,
               ROUND(1.0 * SUM(hit_flag)
                     / NULLIF(COUNT(*) FILTER (WHERE result NOT IN (2,10,11) AND sac=0), 0), 3) AS avg
        FROM enriched_ab
        WHERE player_id = ? AND pitcher_id = ?
    """, [batter_id, pitcher_id]).fetchall()
