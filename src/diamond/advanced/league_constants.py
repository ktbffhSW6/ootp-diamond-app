"""Per-league-year constants needed for sabermetric stats.

Computes from `players_career_*_stats` aggregates:
  - league counting/rate stats: PA, AB, H, 2B, 3B, HR, BB, IBB, HBP, K, SF, SH, R
  - league averages: AVG, OBP, SLG, OPS, BABIP, wOBA
  - linear weights for wOBA/wRAA/wRC (calibrated to lg_runs/lg_PA)
  - FIP constant: cFIP = lgERA - (13·HR + 3·(BB+HBP) - 2·K) / IP
  - Park factors per park (from `parks.csv`: avg, avg_l, avg_r, hr, hr_l, hr_r)

Linear weights use the standard Fangraphs base coefficients
(0.69 NIBB / 0.72 HBP / 0.89 1B / 1.27 2B / 1.62 3B / 2.10 HR), then
re-scaled by the league's runs/PA so the league-average wOBA equals
lg_obp (the wOBA scale convention).
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


# Standard Fangraphs base linear weights (in runs above out)
BASE_LWTS = {
    "wBB":  0.69,
    "wHBP": 0.72,
    "w1B":  0.89,
    "w2B":  1.27,
    "w3B":  1.62,
    "wHR":  2.10,
}


@dataclass(frozen=True)
class LeagueConstants:
    """All per-league-year constants needed by the sabermetric layer."""
    year: int
    league_id: int

    # Counting totals
    lg_pa: int; lg_ab: int; lg_h: int; lg_d: int; lg_t: int; lg_hr: int
    lg_bb: int; lg_ibb: int; lg_hp: int; lg_k: int; lg_sf: int; lg_sh: int
    lg_r: int; lg_sb: int; lg_cs: int

    # Pitching totals
    lg_outs: int; lg_er: int; lg_pit_bb: int; lg_pit_hp: int; lg_pit_k: int; lg_pit_hra: int

    # Rate stats
    lg_avg: float; lg_obp: float; lg_slg: float; lg_ops: float; lg_babip: float
    lg_era: float

    # Linear weights (re-scaled so lg-avg wOBA == lg_obp)
    woba_scale: float
    wBB: float; wHBP: float; w1B: float; w2B: float; w3B: float; wHR: float
    lg_woba: float
    runs_per_pa: float
    lg_runs_per_win: float       # standard ~10 runs/win

    # FIP constant
    fip_constant: float

    def woba_for(self, pa, bb, ibb, hp, h, d, t, hr, ab, sf) -> float:
        """Compute a player's wOBA using these constants."""
        nibb = (bb or 0) - (ibb or 0)
        singles = (h or 0) - (d or 0) - (t or 0) - (hr or 0)
        denom = (ab or 0) + (bb or 0) - (ibb or 0) + (sf or 0) + (hp or 0)
        if denom <= 0:
            return 0.0
        num = (
            self.wBB  * nibb
            + self.wHBP * (hp or 0)
            + self.w1B * singles
            + self.w2B * (d or 0)
            + self.w3B * (t or 0)
            + self.wHR * (hr or 0)
        )
        return num / denom


def compute_constants(con: duckdb.DuckDBPyConnection, year: int, league_id: int) -> LeagueConstants:
    """Compute league constants for one (year, league_id).

    Requires `career_bat` and `career_pit` views registered on the connection
    (via diamond.audit.* `_connect` or equivalent).
    """
    bat = con.execute(
        """
        SELECT
            SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h, SUM(d) AS d, SUM(t) AS t, SUM(hr) AS hr,
            SUM(bb) AS bb, SUM(ibb) AS ibb, SUM(hp) AS hp, SUM(k) AS k,
            SUM(sf) AS sf, SUM(sh) AS sh, SUM(r) AS r, SUM(sb) AS sb, SUM(cs) AS cs
        FROM career_bat
        WHERE year = ? AND league_id = ? AND split_id = 1
        """,
        [year, league_id],
    ).fetchone()
    pit = con.execute(
        """
        SELECT SUM(outs) AS outs, SUM(er) AS er, SUM(bb) AS bb, SUM(hp) AS hp,
               SUM(k) AS k, SUM(hra) AS hra
        FROM career_pit
        WHERE year = ? AND league_id = ? AND split_id = 1
        """,
        [year, league_id],
    ).fetchone()

    lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr, lg_bb, lg_ibb, lg_hp, lg_k, lg_sf, lg_sh, lg_r, lg_sb, lg_cs = bat
    lg_outs, lg_er, lg_pit_bb, lg_pit_hp, lg_pit_k, lg_pit_hra = pit

    lg_avg = lg_h / lg_ab
    lg_obp = (lg_h + lg_bb + lg_hp) / (lg_ab + lg_bb + lg_hp + lg_sf)
    lg_singles = lg_h - lg_d - lg_t - lg_hr
    lg_slg = (lg_singles + 2 * lg_d + 3 * lg_t + 4 * lg_hr) / lg_ab
    lg_ops = lg_obp + lg_slg
    lg_babip = (lg_h - lg_hr) / (lg_ab - lg_k - lg_hr + lg_sf)

    lg_ip = lg_outs / 3.0
    lg_era = 9.0 * lg_er / lg_ip
    fip_const = lg_era - (13 * lg_pit_hra + 3 * (lg_pit_bb + lg_pit_hp) - 2 * lg_pit_k) / lg_ip

    # Linear weights: scale base FG weights so the resulting league wOBA == lg_obp
    nibb = lg_bb - lg_ibb
    woba_denom = lg_ab + lg_bb - lg_ibb + lg_sf + lg_hp
    base_num = (
        BASE_LWTS["wBB"]  * nibb
        + BASE_LWTS["wHBP"] * lg_hp
        + BASE_LWTS["w1B"]  * lg_singles
        + BASE_LWTS["w2B"]  * lg_d
        + BASE_LWTS["w3B"]  * lg_t
        + BASE_LWTS["wHR"]  * lg_hr
    )
    base_lg_woba = base_num / woba_denom
    woba_scale = lg_obp / base_lg_woba   # multiply each linear weight by this

    return LeagueConstants(
        year=year, league_id=league_id,
        lg_pa=lg_pa, lg_ab=lg_ab, lg_h=lg_h, lg_d=lg_d, lg_t=lg_t, lg_hr=lg_hr,
        lg_bb=lg_bb, lg_ibb=lg_ibb, lg_hp=lg_hp, lg_k=lg_k, lg_sf=lg_sf, lg_sh=lg_sh,
        lg_r=lg_r, lg_sb=lg_sb, lg_cs=lg_cs,
        lg_outs=lg_outs, lg_er=lg_er, lg_pit_bb=lg_pit_bb, lg_pit_hp=lg_pit_hp,
        lg_pit_k=lg_pit_k, lg_pit_hra=lg_pit_hra,
        lg_avg=round(lg_avg, 4), lg_obp=round(lg_obp, 4), lg_slg=round(lg_slg, 4),
        lg_ops=round(lg_ops, 4), lg_babip=round(lg_babip, 4), lg_era=round(lg_era, 3),
        woba_scale=round(woba_scale, 4),
        wBB=round(BASE_LWTS["wBB"]  * woba_scale, 4),
        wHBP=round(BASE_LWTS["wHBP"] * woba_scale, 4),
        w1B=round(BASE_LWTS["w1B"]  * woba_scale, 4),
        w2B=round(BASE_LWTS["w2B"]  * woba_scale, 4),
        w3B=round(BASE_LWTS["w3B"]  * woba_scale, 4),
        wHR=round(BASE_LWTS["wHR"]  * woba_scale, 4),
        lg_woba=round(lg_obp, 4),               # by construction equals lg_obp
        runs_per_pa=round(lg_r / lg_pa, 4),
        lg_runs_per_win=10.0,                   # standard sabermetric convention
        fip_constant=round(fip_const, 3),
    )
