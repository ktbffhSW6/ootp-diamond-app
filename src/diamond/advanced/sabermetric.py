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
    """OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1) / halved_park_factor.

    Park-aware as of 2026-05-07. Halved park factor =
    `1 + (parks.avg - 1) / 2` per the audit-decoded OOTP convention
    (verified 8/9 exact for MLB-only Sox in reconcile.py). The home
    park comes from the player's current team row (`players` →
    `teams.park_id` → `parks.avg`); a mid-season trade attributes to
    the latest team. Players with no team mapping default to
    park_avg=1.0 (no adjustment).
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
        ),
        player_park AS (
            SELECT p.player_id, COALESCE(prk.avg, 1.0) AS park_avg
            FROM players p
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN parks prk ON prk.park_id = t.park_id
        )
        SELECT a.player_id AS grp, a.pa, a.obp, a.slg,
               ROUND(
                   100.0 * (a.obp / {lc.lg_obp} + a.slg / {lc.lg_slg} - 1)
                   / (1.0 + (COALESCE(pp.park_avg, 1.0) - 1.0) / 2.0),
                   0
               ) AS ops_plus
        FROM agg a
        LEFT JOIN player_park pp ON pp.player_id = a.player_id
        WHERE a.pa > 0
        ORDER BY ops_plus DESC
    """).fetchall()


def era_plus_per_pitcher(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """ERA+ = 100 * lgERA / playerERA  *  park_factor_80pct.

    Park-aware as of 2026-05-07. The 80% park factor (`1 + (parks.avg
    - 1) * 0.8`) is the audit-decoded OOTP convention (verified
    Crochet 127 vs IE 127 for Fenway in reconcile.py). Pitchers in
    hitter-friendly parks get a credit (ERA+ bumped up), pitchers in
    pitcher-friendly parks get docked. Home park comes from the
    pitcher's current team; mid-season trades attribute to latest team.
    """
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id, SUM(outs) AS outs, SUM(er) AS er
            FROM career_pit
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        ),
        pitcher_park AS (
            SELECT p.player_id, COALESCE(prk.avg, 1.0) AS park_avg
            FROM players p
            LEFT JOIN teams t ON t.team_id = p.team_id
            LEFT JOIN parks prk ON prk.park_id = t.park_id
        )
        SELECT a.player_id AS grp,
               ROUND(a.outs / 3.0, 1) AS ip,
               ROUND(9.0 * a.er / NULLIF(a.outs/3.0, 0), 2) AS era,
               ROUND(
                   100.0 * {lc.lg_era}
                   / NULLIF(9.0 * a.er / NULLIF(a.outs/3.0, 0), 0)
                   * (1.0 + (COALESCE(pp.park_avg, 1.0) - 1.0) * 0.8),
                   0
               ) AS era_plus
        FROM agg a
        LEFT JOIN pitcher_park pp ON pp.player_id = a.player_id
        WHERE a.outs >= 30   -- 10+ IP minimum
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


# Custom WAR — replacement-level baselines + runs-per-win conversion.
# These mirror the Fangraphs framework with two simplifications:
#   1. Offensive WAR is wRAA-only (no positional adjustment, no
#      baserunning runs above average, no defensive runs). Translation:
#      this is "how much did this player's BAT exceed replacement",
#      not full positional WAR. Defensive contribution surfaces as a
#      separate metric in `defensive.py` (RF/9, framing+, OF assists)
#      and would need a runs-above-avg conversion before folding in.
#   2. Pitching WAR uses FIP relative to a flat replacement multiplier
#      of league FIP × 1.13 (geometric mean between Fangraphs SP=1.27
#      and RP=1.06). True role-split would split the multiplier by
#      `gs >= g/2`; left as a refinement.
#
# Constants:
#   REPL_WRAA_PER_PA = 20/600 = 0.0333  → replacement = -20 wRAA per 600 PA
#   RUNS_PER_WIN     = 10                → standard (Fangraphs: 9-10.5 per era)
#   REPL_FIP_MULT    = 1.13              → replacement-level FIP multiplier
REPL_WRAA_PER_PA = 20.0 / 600.0
RUNS_PER_WIN = 10.0
REPL_FIP_MULT = 1.13


def o_war_per_player(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """Offensive WAR — wRAA + replacement-level adjustment / runs_per_win.

    Per-player formula:
        oWAR = (wRAA + REPL_WRAA_PER_PA * pa) / RUNS_PER_WIN

    Where:
      wRAA = ((player_wOBA - lg_wOBA) / wOBA_scale) * pa
      REPL_WRAA_PER_PA = 20/600 — a replacement player has -20 wRAA per
        600 PA, so this offset shifts replacement up to 0 oWAR.
      RUNS_PER_WIN = 10.

    Sanity check: a league-average player (wRAA=0 across 600 PA) gets
    oWAR ≈ 2.0 (matches Fangraphs convention for avg position player).
    A 5-WAR star needs ~+30 wRAA over 600 PA.

    NOT included: positional adjustment (catcher/SS bonus), baserunning
    runs, defensive runs above average. Add those before calling this
    "full" position-player WAR.
    """
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
        ),
        woba_calc AS (
            SELECT player_id, pa,
                ({lc.wBB}*(bb-ibb) + {lc.wHBP}*hp + {lc.w1B}*singles
                 + {lc.w2B}*d + {lc.w3B}*t + {lc.wHR}*hr)
                / NULLIF(ab + bb - ibb + sf + hp, 0) AS player_woba
            FROM agg
        ),
        wraa_calc AS (
            SELECT player_id, pa, player_woba,
                   (player_woba - {lc.lg_woba}) / {lc.woba_scale} * pa AS wraa
            FROM woba_calc
        )
        SELECT player_id AS grp,
               pa,
               ROUND(player_woba, 4) AS woba,
               ROUND(wraa, 1) AS wraa,
               ROUND((wraa + {REPL_WRAA_PER_PA} * pa) / {RUNS_PER_WIN}, 1) AS o_war
        FROM wraa_calc
        WHERE pa > 0
        ORDER BY o_war DESC
    """).fetchall()


def pit_war_per_pitcher(con: duckdb.DuckDBPyConnection, lc: LeagueConstants) -> list[tuple]:
    """Pitching WAR — FIP-based, replacement = lgFIP × 1.13.

    Per-pitcher formula:
        runs_above_repl = (replacement_FIP - playerFIP) × IP / 9
        WAR_pit         = runs_above_repl / RUNS_PER_WIN

    Where:
        replacement_FIP = lg_FIP × REPL_FIP_MULT (1.13 — flat across roles)
        playerFIP       = (13·HR + 3·(BB+HBP) - 2·K) / IP + cFIP
        lg_FIP          = (lc.lg_era — same scale, since FIP is era-shifted)

    Sanity check: a league-average pitcher with FIP = lg_FIP across
    200 IP gets WAR_pit = (lg_FIP × 0.13) × 200/9 / 10. With
    lg_FIP=4.0, that's ~1.2 WAR — slightly low for the avg SP (FG
    convention is ~2.0), reflecting the flat-multiplier simplification.
    Top SP at FIP 3.0 over 200 IP get WAR_pit ≈ 3.6, which scales
    correctly relative to 0-WAR replacement.

    Doesn't role-split (SP vs RP). RP get over-credited slightly under
    this multiplier; SP under-credited. Acceptable for a v1 metric;
    refine via `gs >= g/2` split if needed.
    """
    # lg_FIP is approximated as lg_ERA (FIP is era-shifted to match ER scale).
    lg_fip = lc.lg_era
    repl_fip = lg_fip * REPL_FIP_MULT
    return con.execute(f"""
        WITH agg AS (
            SELECT player_id,
                   SUM(outs) AS outs, SUM(hra) AS hra,
                   SUM(bb) AS bb, SUM(hp) AS hp, SUM(k) AS k
            FROM career_pit
            WHERE year = {lc.year} AND league_id = {lc.league_id} AND split_id = 1
            GROUP BY player_id
        ),
        fip_calc AS (
            SELECT player_id, outs,
                   (13.0*hra + 3.0*(bb+hp) - 2.0*k) / NULLIF(outs/3.0, 0)
                     + {lc.fip_constant} AS fip
            FROM agg
            WHERE outs > 0
        )
        SELECT player_id AS grp,
               ROUND(outs / 3.0, 1) AS ip,
               ROUND(fip, 2) AS fip,
               ROUND(({repl_fip} - fip) * (outs / 3.0) / 9.0 / {RUNS_PER_WIN}, 1) AS war_pit
        FROM fip_calc
        WHERE outs >= 30   -- 10+ IP minimum
        ORDER BY war_pit DESC
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
