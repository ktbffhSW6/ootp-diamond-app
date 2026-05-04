"""L3 derived advanced-stats tables — per-(player, year, league, level).

Materializes the sabermetric stat surface (wOBA / wRAA / wRC / wRC+ /
OPS+ / FIP / ERA+ / oWAR / pit_WAR) at a stable warehouse grain so the
player API and future leaderboards / AI prompts can SELECT instead of
recomputing on demand.

Why per (player_id, year, league_id, level_id) — not per stint:
- **Park factors** apply per-team; a multi-team-same-level season (e.g.
  a mid-year trade between two NL clubs) gets the dominant team's
  park factor rather than something synthesized across stints.
- **League constants** are per (league_id, year, level_id) — the audit
  decoded this convention (D11). Cross-level WAR / wRC+ isn't a
  well-defined number; computing per-level keeps each row anchored to
  its own constants.
- **Sample size** — per-stint advanced stats on a 3-PA cup of coffee
  aren't useful, and the disclosure UI already exposes per-stint
  counting stats for those cases.

Resulting UI shape:
- The Stats tab renders one batting/pitching/fielding section per
  (year, level, team) — counting + slash, with TOT-row disclosure.
- A separate "Advanced" section renders one row per (year, level)
  pulling from this table — wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR.
- Players who never split a season have a 1:1 mapping; players who
  did get one advanced row per level (e.g. an MLB row + a AAA row).

Build pattern: full DROP/CREATE on every ingest (consistent with the
rest of L3). Depends on L2 being current — specifically
`f_player_season_batting`, `f_player_season_pitching`, plus the L1
reference tables `players` (for park lookup), `teams`, `parks`,
and `league_history_batting_event` / `_pitching_event` for the
league totals.

Dictionary cross-reference (per D15):
  wOBA / wRAA / wRC / wRC_plus / OPS_plus / FIP / ERA_plus / oWAR /
  pit_WAR — every column maps to a `STATS[id]` entry with the formula
  + park-factor convention documented.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# League-constants temp view (per (league_id, year, level_id))
#
# Materializes everything `compute_constants` from
# `diamond.advanced.league_constants` produces, but in pure SQL so the
# downstream JOINs stay set-based. Linear weights are the Fangraphs
# canonical base values scaled by `woba_scale`, where:
#
#   base_lg_woba = Σ(base_weights × lg counting) / (AB + nibb + SF + HBP)
#   woba_scale   = lg_obp / base_lg_woba
#   wX           = base_X × woba_scale
#
# By construction this makes lg_woba == lg_obp — convenient for sanity
# checks and matches the implementation in `advanced/league_constants.py`.
# ─────────────────────────────────────────────────────────────────────────────


# Fangraphs base linear weights — pre-scaling. Constants across leagues.
_BASE_W_BB = 0.69
_BASE_W_HBP = 0.72
_BASE_W_1B = 0.89
_BASE_W_2B = 1.27
_BASE_W_3B = 1.62
_BASE_W_HR = 2.10


_LG_CONSTANTS_VIEW_SQL = f"""
CREATE OR REPLACE VIEW _lg_constants_advanced AS
WITH agg_bat AS (
    SELECT
        league_id, year, level_id,
        SUM(pa)::DOUBLE  AS lg_pa,
        SUM(ab)::DOUBLE  AS lg_ab,
        SUM(h)::DOUBLE   AS lg_h,
        SUM(d)::DOUBLE   AS lg_d,
        SUM(t)::DOUBLE   AS lg_t,
        SUM(hr)::DOUBLE  AS lg_hr,
        SUM(bb)::DOUBLE  AS lg_bb,
        SUM(ibb)::DOUBLE AS lg_ibb,
        SUM(hp)::DOUBLE  AS lg_hp,
        SUM(sf)::DOUBLE  AS lg_sf,
        SUM(r)::DOUBLE   AS lg_r,
        (SUM(h) - SUM(d) - SUM(t) - SUM(hr))::DOUBLE AS lg_singles
    FROM league_history_batting_event
    GROUP BY league_id, year, level_id
),
agg_pit AS (
    -- league_history_pitching has ip + ipf (full innings + frac outs);
    -- collapse to total outs to match the player-side outs convention.
    SELECT
        league_id, year, level_id,
        (SUM(ip) * 3.0 + SUM(ipf))::DOUBLE AS lg_outs,
        SUM(er)::DOUBLE                    AS lg_er,
        SUM(hra)::DOUBLE                   AS lg_hra,
        SUM(bb)::DOUBLE                    AS lg_pit_bb,
        SUM(hp)::DOUBLE                    AS lg_pit_hp,
        SUM(k)::DOUBLE                     AS lg_pit_k
    FROM league_history_pitching_event
    GROUP BY league_id, year, level_id
),
joined AS (
    SELECT
        b.league_id, b.year, b.level_id,
        b.lg_pa, b.lg_ab, b.lg_h, b.lg_d, b.lg_t, b.lg_hr,
        b.lg_bb, b.lg_ibb, b.lg_hp, b.lg_sf, b.lg_r, b.lg_singles,
        COALESCE(p.lg_outs, 0.0)   AS lg_outs,
        COALESCE(p.lg_er,   0.0)   AS lg_er,
        COALESCE(p.lg_hra,  0.0)   AS lg_hra,
        COALESCE(p.lg_pit_bb, 0.0) AS lg_pit_bb,
        COALESCE(p.lg_pit_hp, 0.0) AS lg_pit_hp,
        COALESCE(p.lg_pit_k,  0.0) AS lg_pit_k
    FROM agg_bat b
    LEFT JOIN agg_pit p USING (league_id, year, level_id)
),
derived AS (
    SELECT *,
        -- Slash-line league rates (recomputed from totals — mirrors lg_constants_bat)
        (lg_h + lg_bb + lg_hp) / NULLIF(lg_ab + lg_bb + lg_hp + lg_sf, 0) AS lg_obp,
        (lg_singles + 2*lg_d + 3*lg_t + 4*lg_hr) / NULLIF(lg_ab, 0)         AS lg_slg,
        -- IP and ERA
        lg_outs / 3.0 AS lg_ip,
        9.0 * lg_er / NULLIF(lg_outs / 3.0, 0) AS lg_era,
        -- Per-PA run environment
        lg_r / NULLIF(lg_pa, 0) AS runs_per_pa,
        -- nibb (non-intentional walks)
        (lg_bb - lg_ibb) AS lg_nibb,
        -- Base wOBA numerator + denominator (pre-scaling)
        ({_BASE_W_BB} * (lg_bb - lg_ibb)
         + {_BASE_W_HBP} * lg_hp
         + {_BASE_W_1B}  * lg_singles
         + {_BASE_W_2B}  * lg_d
         + {_BASE_W_3B}  * lg_t
         + {_BASE_W_HR}  * lg_hr) AS base_woba_num,
        (lg_ab + (lg_bb - lg_ibb) + lg_sf + lg_hp) AS woba_denom
    FROM joined
),
scaled AS (
    SELECT *,
        base_woba_num / NULLIF(woba_denom, 0) AS base_lg_woba
    FROM derived
)
SELECT
    league_id, year, level_id,
    lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
    lg_bb, lg_ibb, lg_hp, lg_sf, lg_r, lg_singles, lg_nibb,
    lg_outs, lg_er, lg_hra, lg_pit_bb, lg_pit_hp, lg_pit_k,
    lg_ip, lg_era, lg_obp, lg_slg, runs_per_pa,
    -- woba_scale calibrates linear weights so that league wOBA == league OBP
    lg_obp / NULLIF(base_lg_woba, 0) AS woba_scale,
    -- Final scaled weights
    {_BASE_W_BB}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_bb,
    {_BASE_W_HBP} * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hbp,
    {_BASE_W_1B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_1b,
    {_BASE_W_2B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_2b,
    {_BASE_W_3B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_3b,
    {_BASE_W_HR}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hr,
    -- League wOBA — equals lg_obp by construction
    lg_obp AS lg_woba,
    -- FIP constant — calibrates so league FIP == league ERA
    lg_era - (13.0 * lg_hra + 3.0 * (lg_pit_bb + lg_pit_hp) - 2.0 * lg_pit_k) / NULLIF(lg_ip, 0) AS fip_constant
FROM scaled
"""


# Replacement-level + runs-per-win constants, mirrored from
# `diamond.advanced.sabermetric` so the materialized values match the
# audit's computed numbers exactly. Update both places together.
_REPL_WRAA_PER_PA = 20.0 / 600.0
_RUNS_PER_WIN = 10.0
_REPL_FIP_MULT = 1.13


# ─────────────────────────────────────────────────────────────────────────────
# Park-factor lookup CTE
#
# Per-stint home park varies — a player traded mid-season has different
# parks for each stint. For per-(year, league, level) advanced rows we
# pick the team where the player accumulated the most PA (batting) or
# outs (pitching) at that level, and use that team's park factor.
# Players with no team mapping default to park_avg=1.0 (no adjustment),
# matching the convention in `sabermetric.ops_plus_per_player`.
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_player_season_advanced_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, league_id, level_id) batting advanced stats.

    Computed:
      pa, woba, wraa, wrc, wrc_plus, ops_plus, o_war

    Filters: ``split_id = 1`` (overall split — vs LHP / vs RHP would
    double-count). Output is the natural unit for headline rate stats —
    cross-level rollups aren't included since league constants differ.
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_advanced_batting AS
        WITH agg AS (
            SELECT
                player_id, year, league_id, level_id,
                SUM(pa)::DOUBLE  AS pa,
                SUM(ab)::DOUBLE  AS ab,
                SUM(h)::DOUBLE   AS h,
                SUM(d)::DOUBLE   AS d,
                SUM(t)::DOUBLE   AS t,
                SUM(hr)::DOUBLE  AS hr,
                SUM(bb)::DOUBLE  AS bb,
                SUM(ibb)::DOUBLE AS ibb,
                SUM(hp)::DOUBLE  AS hp,
                SUM(sf)::DOUBLE  AS sf,
                (SUM(h) - SUM(d) - SUM(t) - SUM(hr))::DOUBLE AS singles,
                (SUM(bb) - SUM(ibb))::DOUBLE                 AS nibb
            FROM f_player_season_batting
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        ),
        -- Pick the team where the player took the most PA at this level.
        -- Ties broken by ascending team_id for stability.
        dominant_team AS (
            SELECT player_id, year, league_id, level_id, team_id
            FROM (
                SELECT player_id, year, league_id, level_id, team_id, pa,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_id, year, league_id, level_id
                           ORDER BY pa DESC, team_id ASC
                       ) AS rn
                FROM f_player_season_batting
                WHERE split_id = 1
            ) WHERE rn = 1
        ),
        park_lookup AS (
            SELECT d.player_id, d.year, d.league_id, d.level_id,
                   COALESCE(prk.avg, 1.0) AS park_avg
            FROM dominant_team d
            LEFT JOIN teams t ON t.team_id  = d.team_id
            LEFT JOIN parks prk ON prk.park_id = t.park_id
        ),
        joined AS (
            SELECT
                a.*,
                lc.lg_obp, lc.lg_slg, lc.lg_woba, lc.woba_scale, lc.runs_per_pa,
                lc.w_bb, lc.w_hbp, lc.w_1b, lc.w_2b, lc.w_3b, lc.w_hr,
                COALESCE(pl.park_avg, 1.0) AS park_avg
            FROM agg a
            LEFT JOIN _lg_constants_advanced lc USING (league_id, year, level_id)
            LEFT JOIN park_lookup pl USING (player_id, year, league_id, level_id)
        ),
        woba_calc AS (
            SELECT *,
                (w_bb*nibb + w_hbp*hp + w_1b*singles + w_2b*d + w_3b*t + w_hr*hr)
                / NULLIF(ab + nibb + sf + hp, 0) AS player_woba,
                -- Slash-line for OPS+
                (h + bb + hp) / NULLIF(ab + bb + hp + sf, 0) AS player_obp,
                (singles + 2*d + 3*t + 4*hr) / NULLIF(ab, 0)  AS player_slg
            FROM joined
        )
        SELECT
            player_id, year, league_id, level_id,
            CAST(pa AS BIGINT) AS pa,
            ROUND(player_woba, 4) AS woba,
            ROUND((player_woba - lg_woba) / NULLIF(woba_scale, 0) * pa, 1) AS wraa,
            ROUND(((player_woba - lg_woba) / NULLIF(woba_scale, 0) + runs_per_pa) * pa, 1) AS wrc,
            CAST(ROUND(
                100.0 * (
                    ((player_woba - lg_woba) / NULLIF(woba_scale, 0) + runs_per_pa)
                    / NULLIF(runs_per_pa, 0)
                ), 0
            ) AS INTEGER) AS wrc_plus,
            CAST(ROUND(
                100.0 * (player_obp / NULLIF(lg_obp, 0)
                         + player_slg / NULLIF(lg_slg, 0) - 1)
                / NULLIF(1.0 + (park_avg - 1.0) / 2.0, 0),
                0
            ) AS INTEGER) AS ops_plus,
            ROUND(
                ((player_woba - lg_woba) / NULLIF(woba_scale, 0) * pa
                 + {_REPL_WRAA_PER_PA} * pa) / {_RUNS_PER_WIN},
                1
            ) AS o_war,
            ROUND(park_avg, 3) AS park_avg
        FROM woba_calc
        WHERE pa > 0
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_advanced_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_advanced_batting"
    ).fetchone()[0]


def _build_f_player_season_advanced_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, league_id, level_id) pitching advanced stats.

    Computed:
      outs, ip_display, fip, era_plus, pit_war

    Filters: ``split_id = 1``. Park factor is the dominant-team's park
    (most outs at this level). Quality threshold: outs >= 30 (10 IP) —
    matches the audit's `era_plus_per_pitcher` filter so headline values
    line up with the audit's IE-reconciled numbers.
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_advanced_pitching AS
        WITH agg AS (
            SELECT
                player_id, year, league_id, level_id,
                SUM(outs)::DOUBLE AS outs,
                SUM(er)::DOUBLE   AS er,
                SUM(hra)::DOUBLE  AS hra,
                SUM(bb)::DOUBLE   AS bb,
                SUM(hp)::DOUBLE   AS hp,
                SUM(k)::DOUBLE    AS k
            FROM f_player_season_pitching
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        ),
        dominant_team AS (
            SELECT player_id, year, league_id, level_id, team_id
            FROM (
                SELECT player_id, year, league_id, level_id, team_id, outs,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_id, year, league_id, level_id
                           ORDER BY outs DESC, team_id ASC
                       ) AS rn
                FROM f_player_season_pitching
                WHERE split_id = 1
            ) WHERE rn = 1
        ),
        park_lookup AS (
            SELECT d.player_id, d.year, d.league_id, d.level_id,
                   COALESCE(prk.avg, 1.0) AS park_avg
            FROM dominant_team d
            LEFT JOIN teams t ON t.team_id  = d.team_id
            LEFT JOIN parks prk ON prk.park_id = t.park_id
        ),
        joined AS (
            SELECT
                a.*,
                lc.lg_era, lc.fip_constant,
                COALESCE(pl.park_avg, 1.0) AS park_avg
            FROM agg a
            LEFT JOIN _lg_constants_advanced lc USING (league_id, year, level_id)
            LEFT JOIN park_lookup pl USING (player_id, year, league_id, level_id)
        ),
        rates AS (
            SELECT *,
                outs / 3.0 AS ip,
                9.0 * er / NULLIF(outs / 3.0, 0) AS player_era,
                (13.0 * hra + 3.0 * (bb + hp) - 2.0 * k) / NULLIF(outs / 3.0, 0)
                    + fip_constant AS player_fip
            FROM joined
        )
        SELECT
            player_id, year, league_id, level_id,
            CAST(outs AS BIGINT) AS outs,
            ROUND(FLOOR(outs / 3.0) + ((CAST(outs AS BIGINT) % 3)) * 0.1, 1) AS ip_display,
            ROUND(player_fip, 2) AS fip,
            CAST(ROUND(
                100.0 * lg_era / NULLIF(player_era, 0)
                * (1.0 + (park_avg - 1.0) * 0.8),
                0
            ) AS INTEGER) AS era_plus,
            ROUND(
                ((lg_era * {_REPL_FIP_MULT}) - player_fip) * (outs / 3.0) / 9.0
                / {_RUNS_PER_WIN},
                1
            ) AS pit_war,
            ROUND(park_avg, 3) AS park_avg
        FROM rates
        WHERE outs >= 30   -- 10+ IP minimum, matches audit threshold
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_advanced_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_advanced_pitching"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — registered into the L3 builder list
# ─────────────────────────────────────────────────────────────────────────────


def build_l3_advanced(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build the per-(player, year, league_id, level_id) advanced fact tables.

    Returns dict of `{table_name: row_count}`. Idempotent (CREATE OR
    REPLACE under the hood). Depends on L2 facts being current — the
    L3 orchestrator runs after L2 so this is always satisfied during
    normal `build_warehouse` runs.
    """
    rows: dict[str, int] = {}

    # 1. Register the league-constants view first; the table builders
    #    JOIN against it.
    con.execute(_LG_CONSTANTS_VIEW_SQL)
    if verbose:
        console.print(
            "  [green]✓[/green] _lg_constants_advanced (view) "
            "[dim]per (league_id, year, level_id)[/dim]"
        )

    # 2. Per-player advanced facts.
    builders = [
        ("f_player_season_advanced_batting",  _build_f_player_season_advanced_batting),
        ("f_player_season_advanced_pitching", _build_f_player_season_advanced_pitching),
    ]
    for name, fn in builders:
        n = fn(con)
        rows[name] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {name:<42} [dim]{n:>10,} rows[/dim]"
            )

    return rows
