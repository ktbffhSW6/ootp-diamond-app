"""Reusable enriched at-bat view used by Tier 1, 2, 5 stats.

Wraps `players_at_bat_batting_stats` with derived columns:
  - bip_flag, hit_flag, walk_flag, k_flag (from result code)
  - base_state (0-7, encoded as base1*1 + base2*2 + base3*4)
  - risp_flag (runner on 2nd or 3rd, pre-AB)
  - bases_loaded_flag
  - late_inning_flag (inning >= 7)
  - close_late_flag (Close = 1 AND late_inning)
  - bats_hand, throws_hand (joined from players)
  - spray (Pull / Center / Oppo, derived from hit_xy + bats_hand)

Materialized as a TEMP TABLE called `enriched_ab` on first call so all
downstream queries can reuse it without rejoining.
"""

from __future__ import annotations

import duckdb


ENRICH_SQL = """
CREATE OR REPLACE TEMP TABLE enriched_ab AS
SELECT
    ab.player_id,
    ab.opponent_player_id     AS pitcher_id,
    ab.team_id                AS bat_team_id,
    ab.game_id,
    g.date                    AS game_date,
    g.game_type,
    g.league_id,
    ab.inning,
    ab.outs,
    ab.balls,
    ab.strikes,
    ab.result,
    ab.sac,
    ab.pinch,
    ab.Close                  AS close_flag,
    ab.run_diff,
    ab.spot                   AS lineup_spot,
    ab.rbi,
    ab.r                      AS runs_scored,
    ab.sb,
    ab.cs,
    ab.hit_loc,
    ab.hit_xy,
    ab.exit_velo,
    ab.launch_angle,
    ab.sprint_speed,
    p_bat.bats                AS bats_hand,                  -- 1=R, 2=L, 3=S
    p_pit.throws              AS throws_hand,
    -- Outcome flags
    CASE WHEN ab.result IN (4,5,6,7,8,9) THEN 1 ELSE 0 END   AS bip_flag,
    CASE WHEN ab.result IN (6,7,8,9)     THEN 1 ELSE 0 END   AS hit_flag,
    CASE WHEN ab.result = 2              THEN 1 ELSE 0 END   AS bb_flag,
    CASE WHEN ab.result = 1              THEN 1 ELSE 0 END   AS k_flag,
    CASE WHEN ab.result = 10             THEN 1 ELSE 0 END   AS hbp_flag,
    CASE WHEN ab.result = 6              THEN 1 ELSE 0 END   AS single_flag,
    CASE WHEN ab.result = 7              THEN 1 ELSE 0 END   AS double_flag,
    CASE WHEN ab.result = 8              THEN 1 ELSE 0 END   AS triple_flag,
    CASE WHEN ab.result = 9              THEN 1 ELSE 0 END   AS hr_flag,
    CASE WHEN ab.result = 4              THEN 1 ELSE 0 END   AS go_flag,
    CASE WHEN ab.result = 5              THEN 1 ELSE 0 END   AS fo_flag,
    -- Base state
    (ab.base1 + 2*ab.base2 + 4*ab.base3) AS base_state,
    CASE WHEN ab.base2 = 1 OR ab.base3 = 1 THEN 1 ELSE 0 END AS risp_flag,
    CASE WHEN ab.base1 = 1 AND ab.base2 = 1 AND ab.base3 = 1 THEN 1 ELSE 0 END AS loaded_flag,
    -- Inning / context
    CASE WHEN ab.inning >= 7   THEN 1 ELSE 0 END             AS late_inning_flag,
    CASE WHEN ab.Close = 1 AND ab.inning >= 7 THEN 1 ELSE 0 END AS late_close_flag,
    CASE WHEN ab.inning <= 3 THEN '1-3'
         WHEN ab.inning <= 6 THEN '4-6'
         ELSE '7+'
    END                                                     AS inning_bucket,
    -- Spray category. hit_xy 0-255 maps to lateral field position.
    -- For a RH batter, low xy = LF (pull). For LHB, low xy = LF (oppo).
    -- Heuristic thirds:
    --   <85   = LF area
    --   86-170 = CF area
    --   >170   = RF area
    CASE
      WHEN ab.hit_xy IS NULL OR ab.result NOT IN (4,5,6,7,8,9) THEN NULL
      WHEN ab.hit_xy < 86 THEN
            CASE WHEN p_bat.bats = 1 THEN 'Pull'   -- RH → LF = pull
                 WHEN p_bat.bats = 2 THEN 'Oppo'   -- LH → LF = oppo
                 ELSE 'Pull' END
      WHEN ab.hit_xy <= 170 THEN 'Center'
      ELSE  CASE WHEN p_bat.bats = 1 THEN 'Oppo'   -- RH → RF = oppo
                 WHEN p_bat.bats = 2 THEN 'Pull'   -- LH → RF = pull
                 ELSE 'Pull' END
    END                                                     AS spray_category
FROM at_bat ab
JOIN games g       ON ab.game_id = g.game_id
LEFT JOIN players p_bat ON ab.player_id          = p_bat.player_id
LEFT JOIN players p_pit ON ab.opponent_player_id = p_pit.player_id
"""


def materialize_enriched_ab(con: duckdb.DuckDBPyConnection) -> None:
    """Build the `enriched_ab` temp table. Idempotent — re-runs replace it."""
    con.execute(ENRICH_SQL)
