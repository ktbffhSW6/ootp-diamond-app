"""Per-column reconciliation of OOTP `import_export` Red Sox roster files
against derivations from the monthly dump CSVs.

For each `boston_red_sox_organization_-_roster_*.csv` file:
  - Derive every visible column from dump tables using SQL
  - Compare cell-by-cell against the import_export values
  - Score each column: match rate, mean error, max error
  - Tag with tier:
        A = direct dump column (ties exactly)
        B = trivial calc from dump fields (AVG = H/AB, etc.)
        C = derived w/ league constants (OPS+, wOBA, FIP, ERA+) — TODO v2
        D = modeled (xBA/xSLG/xwOBA/xERA) — TODO v3
        E = aggregated from at-bat events (EV, LA, hit-type %s)
        F = cannot replicate (Z%, SW%, RV-*)
        G = needs scale conversion (overall ratings: divide by 2)

Output: audit_output/reconciliation_report.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()

# Match thresholds for "considered equal"
INT_TOLERANCE = 0
RATE_TOLERANCE = 0.001       # AVG/OBP/SLG/etc — 3-decimal precision
RATING_TOLERANCE = 1         # 20-80 scouting scale, allow ±1 for scout variance

# Boston Red Sox organization team_ids — sum stats across these for org-level rollup
# (MLB + AAA + AA + A+ + A + FCL + 2 DSL = 8 teams)
BOSTON_ORG_TEAMS = (4, 35, 64, 269, 289, 113, 158, 326)
BOSTON_MLB_TEAM = 4


# ─────────────────────────────────────────────────────────────────────────────
# Column derivation specs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ColSpec:
    """One column from an import_export file with its dump derivation."""

    ie_name: str                # column name as it appears in import_export
    derived_sql: str            # SQL expression producing the value, given the join CTE
    tier: str                   # A / B / C / D / E / F / G
    tolerance: float = 0.0
    notes: str = ""


@dataclass
class FileSpec:
    """One import_export file with its full set of column derivations."""

    ie_filename: str            # e.g. "boston_red_sox_organization_-_roster_batting_stats_1.csv"
    short_name: str             # e.g. "batting_stats_1"
    derived_cte: str            # SQL CTE producing per-player derived row keyed by player_id
    cols: list[ColSpec]
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Derivation SQL templates
# ─────────────────────────────────────────────────────────────────────────────


# Career batting overall — sum across ALL teams a player appeared on in 2029.
# IE shows org-roster snapshot with each player's FULL season stats (incl. amateur/short-season
# stints and time on prior orgs before mid-year trades), so we don't restrict team_id here.
BATTING_DERIVED_CTE = """
agg AS (
    SELECT
        player_id,
        SUM(g) AS g, SUM(gs) AS gs, SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
        SUM(k) AS k, SUM(bb) AS bb, SUM(ibb) AS ibb, SUM(hp) AS hp,
        SUM(d) AS d, SUM(t) AS t, SUM(hr) AS hr,
        SUM(r) AS r, SUM(rbi) AS rbi, SUM(sb) AS sb, SUM(cs) AS cs,
        SUM(gdp) AS gdp, SUM(sh) AS sh, SUM(sf) AS sf, SUM(ci) AS ci,
        SUM(pitches_seen) AS pitches_seen,
        SUM(wpa) AS wpa,
        SUM(war) AS war,
        -- Player's primary playing-level (highest = lowest level_id, US-affiliated only).
        -- Used to look up league constants and home-park factor for OPS+/wRC+/etc.
        MIN(CASE WHEN level_id BETWEEN 1 AND 6 THEN level_id END) AS primary_level,
        MIN(CASE WHEN level_id BETWEEN 1 AND 6 THEN league_id END) AS primary_league
    FROM career_bat
    WHERE year = 2029 AND split_id = 1
    GROUP BY player_id
),
-- League constants per (league_id, level_id), aggregated across AL/NL sub-leagues
-- per Decision D11 (no AL/NL split — empirically a no-op in this save).
lg_b AS (
    SELECT
        league_id, year, level_id,
        SUM(pa) AS lg_pa, SUM(ab) AS lg_ab, SUM(h) AS lg_h, SUM(d) AS lg_d, SUM(t) AS lg_t,
        SUM(hr) AS lg_hr, SUM(bb) AS lg_bb, SUM(hp) AS lg_hp, SUM(sf) AS lg_sf,
        SUM(sh) AS lg_sh, SUM(k) AS lg_k, SUM(sb) AS lg_sb, SUM(cs) AS lg_cs,
        -- Pre-computed lg_obp / lg_slg / lg_woba may be averaged across sub-leagues.
        -- Recompute from totals to be safe.
        ROUND((SUM(h) + SUM(bb) + SUM(hp))::DOUBLE / NULLIF(SUM(ab) + SUM(bb) + SUM(hp) + SUM(sf), 0), 4) AS lg_obp,
        ROUND((SUM(tb))::DOUBLE / NULLIF(SUM(ab), 0), 4) AS lg_slg
    FROM league_history_batting_stats
    GROUP BY league_id, year, level_id
),
-- Home-park factor for each player from teams -> parks.
-- IE OPS+ uses the halved-home park factor: 1 + (parks.avg - 1) / 2.
-- Verified empirically against MLB-only Red Sox players (Mayer, Gonzales, etc.)
-- — gives 8/9 exact match on OPS+.
player_park AS (
    SELECT p.player_id, prk.avg AS park_avg
    FROM players p
    LEFT JOIN teams t ON t.team_id = p.team_id
    LEFT JOIN parks prk ON prk.park_id = t.park_id
),
derived AS (
    SELECT
        a.player_id,
        a.g, a.gs, a.pa, a.ab, a.h, a.k, a.bb, a.ibb, a.hp,
        a.d, a.t, a.hr, a.r, a.rbi, a.sb, a.cs, a.gdp, a.sh, a.sf, a.ci,
        a.pitches_seen, a.wpa, a.war,
        a.primary_level, a.primary_league,
        -- Slash line
        ROUND(1.0 * a.h / NULLIF(a.ab, 0), 3) AS avg,
        ROUND(1.0 * (a.h + a.bb + a.hp) / NULLIF(a.ab + a.bb + a.hp + a.sf, 0), 3) AS obp,
        ROUND(1.0 * (a.h + a.d + 2*a.t + 3*a.hr) / NULLIF(a.ab, 0), 3) AS slg,
        ROUND(1.0 * (a.d + 2*a.t + 3*a.hr) / NULLIF(a.ab, 0), 3) AS iso,
        ROUND(1.0 * (a.h - a.hr) / NULLIF(a.ab - a.k - a.hr + a.sf, 0), 3) AS babip,
        (a.d + a.t + a.hr) AS ebh,
        (a.h + a.d + 2*a.t + 3*a.hr) AS tb,
        ROUND(100.0 * a.bb / NULLIF(a.pa, 0), 1) AS bb_pct,
        ROUND(100.0 * a.k / NULLIF(a.pa, 0), 1) AS k_pct,
        ROUND(1.0 * a.pitches_seen / NULLIF(a.pa, 0), 2) AS pi_per_pa,
        -- OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1) / parkFactorHalved
        -- where parkFactorHalved = 1 + (parks.avg - 1) / 2.
        -- Per-level league constants (level=1 MLB constants for MLB players,
        -- level=2 AAA for AAA players, etc.). Verified 8/9 exact for MLB-only Sox.
        ROUND(
            100.0 * ((a.h + a.bb + a.hp)::DOUBLE / NULLIF(a.ab + a.bb + a.hp + a.sf, 0) / NULLIF(lg_b.lg_obp, 0)
                     + (a.h + a.d + 2*a.t + 3*a.hr)::DOUBLE / NULLIF(a.ab, 0) / NULLIF(lg_b.lg_slg, 0)
                     - 1.0)
            / (1.0 + (COALESCE(pp.park_avg, 1.0) - 1.0) / 2.0), 0
        ) AS ops_plus,
        -- Bill James technical RC: ((H+BB-CS+HBP-GIDP) * (TB + 0.26*(BB+HBP) + 0.52*(SH+SF+SB))) / PA
        ROUND(
            (a.h + a.bb - a.cs + a.hp - a.gdp)::DOUBLE
            * (a.h + a.d + 2*a.t + 3*a.hr + 0.26 * (a.bb + a.hp) + 0.52 * (a.sh + a.sf + a.sb))
            / NULLIF(a.ab + a.bb + a.hp + a.sf + a.sh + a.ci, 0),
            1
        ) AS rc,
        -- RC/27 = RC * 27 / outs. Outs = AB - H + GIDP + SH + SF + CS.
        ROUND(
            (a.h + a.bb - a.cs + a.hp - a.gdp)::DOUBLE
            * (a.h + a.d + 2*a.t + 3*a.hr + 0.26 * (a.bb + a.hp) + 0.52 * (a.sh + a.sf + a.sb))
            / NULLIF(a.ab + a.bb + a.hp + a.sf + a.sh + a.ci, 0)
            * 27.0
            / NULLIF((a.ab - a.h) + a.gdp + a.sh + a.sf + a.cs, 0),
            1
        ) AS rc27,
        -- wOBA — Fangraphs standard linear weights, divided by PA-equivalent denom.
        -- 1B = H - 2B - 3B - HR. uBB = BB - IBB.
        ROUND(
            (0.69 * (a.bb - a.ibb)
             + 0.72 * a.hp
             + 0.89 * (a.h - a.d - a.t - a.hr)
             + 1.27 * a.d
             + 1.62 * a.t
             + 2.10 * a.hr)::DOUBLE
            / NULLIF(a.ab + a.bb - a.ibb + a.sf + a.hp, 0),
            3
        ) AS woba
    FROM agg a
    LEFT JOIN lg_b      ON lg_b.league_id = a.primary_league AND lg_b.year = 2029 AND lg_b.level_id = a.primary_level
    LEFT JOIN player_park pp ON pp.player_id = a.player_id
)
"""


BATTING_STATS_1 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_stats_1.csv",
    short_name="batting_stats_1",
    derived_cte=BATTING_DERIVED_CTE,
    cols=[
        ColSpec("G",   "g",        "A"),
        ColSpec("PA",  "pa",       "A"),
        ColSpec("AB",  "ab",       "A"),
        ColSpec("H",   "h",        "A"),
        ColSpec("2B",  "d",        "A"),
        ColSpec("3B",  "t",        "A"),
        ColSpec("HR",  "hr",       "A"),
        ColSpec("RBI", "rbi",      "A"),
        ColSpec("R",   "r",        "A"),
        ColSpec("BB",  "bb",       "A"),
        ColSpec("IBB", "ibb",      "A"),
        ColSpec("HP",  "hp",       "A"),
        ColSpec("K",   "k",        "A"),
        ColSpec("GIDP", "gdp",     "A"),
        ColSpec("AVG", "avg",      "B", tolerance=RATE_TOLERANCE),
        ColSpec("OBP", "obp",      "B", tolerance=RATE_TOLERANCE),
        ColSpec("SLG", "slg",      "B", tolerance=RATE_TOLERANCE),
        ColSpec("ISO", "iso",      "B", tolerance=RATE_TOLERANCE),
        # OPS = OBP + SLG. IE rounds inputs separately then sums; we sum then round.
        # 0.002 tolerance covers the 1-thousandth rounding cascade.
        ColSpec("OPS", "ROUND(d.obp + d.slg, 3)", "B", tolerance=0.002),
        # OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1) / halved_park_factor.
        # Park factor halved: 1 + (parks.avg - 1) / 2. Verified 8/9 MLB-only Sox.
        ColSpec("OPS+", "ops_plus", "B", tolerance=2,
                notes="100 * (OBP/lgOBP + SLG/lgSLG - 1) / (1 + (park.avg-1)/2)"),
        ColSpec("BABIP", "babip", "B", tolerance=RATE_TOLERANCE),
        # WAR is in players_value
        ColSpec("WAR", "ROUND(d.war, 1)", "A", tolerance=0.1,
                notes="career_bat.war (summed across stints)"),
        ColSpec("SB",  "sb",       "A"),
        ColSpec("CS",  "cs",       "A"),
    ],
)


BATTING_STATS_2 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_stats_2.csv",
    short_name="batting_stats_2",
    derived_cte=BATTING_DERIVED_CTE,
    cols=[
        ColSpec("G",   "g",        "A"),
        ColSpec("PA",  "pa",       "A"),
        ColSpec("BB",  "bb",       "A"),
        ColSpec("BB%", "bb_pct",   "B", tolerance=0.05),
        ColSpec("SH",  "sh",       "A"),
        ColSpec("SF",  "sf",       "A"),
        ColSpec("CI",  "ci",       "A"),
        ColSpec("K",   "k",        "A"),
        ColSpec("K%",  "k_pct",    "B", tolerance=0.05),
        ColSpec("GIDP", "gdp",     "A"),
        ColSpec("EBH", "ebh",      "B"),
        ColSpec("TB",  "tb",       "B"),
        # Bill James technical RC formula. Verified Mayer 72.5=72.5 exact.
        ColSpec("RC",  "rc",       "B", tolerance=0.5,
                notes="((H+BB-CS+HBP-GIDP) * (TB + 0.26*(BB+HBP) + 0.52*(SH+SF+SB))) / PA"),
        ColSpec("RC/27", "rc27",   "B", tolerance=0.1, notes="RC * 27 / batting outs"),
        ColSpec("ISO", "iso",      "B", tolerance=RATE_TOLERANCE),
        # wOBA via standard Fangraphs linear weights (0.69/0.72/0.89/1.27/1.62/2.10).
        # Within 0.005 of IE for Mayer (0.326 vs 0.322). May need tighter weights from lg-calibration.
        ColSpec("wOBA", "woba",    "B", tolerance=0.01,
                notes="standard Fangraphs linear weights"),
        ColSpec("WPA", "ROUND(d.wpa, 2)", "A", tolerance=0.05),
        ColSpec("PI/PA", "pi_per_pa", "B", tolerance=0.02),
    ],
)


# Pitching career overall — also aggregated across the Red Sox org.
# IP convention: integer-innings + (remaining-outs * 0.1), e.g. 517 outs → 172.1 IP.
PITCHING_DERIVED_CTE = f"""
agg AS (
    SELECT
        player_id,
        SUM(g) AS g, SUM(gs) AS gs, SUM(gf) AS gf,
        SUM(w) AS w, SUM(l) AS l, SUM(s) AS sv, SUM(hld) AS hld,
        SUM(outs) AS outs,
        SUM(ha) AS ha, SUM(hra) AS hra, SUM(r) AS r, SUM(er) AS er, SUM(rs) AS rs_total,
        SUM(bb) AS bb, SUM(k) AS k, SUM(hp) AS hp, SUM(bf) AS bf,
        SUM(ab) AS ab, SUM(tb) AS tb, SUM(gb) AS gb, SUM(fb) AS fb, SUM(pi) AS pitches_thrown,
        SUM(dp) AS dp, SUM(qs) AS qs, SUM(svo) AS svo, SUM(bs) AS bs,
        SUM(cg) AS cg, SUM(sho) AS sho,
        SUM(sb) AS sb_against, SUM(cs) AS cs_against, SUM(iw) AS iw, SUM(wp) AS wp, SUM(bk) AS bk,
        SUM(ir) AS ir, SUM(irs) AS irs, SUM(wpa) AS wpa, SUM(li) AS li_cum,
        SUM(sd) AS sd, SUM(md) AS md, SUM(war) AS war, SUM(ra9war) AS ra9war,
        SUM(sf) AS sf,
        MIN(CASE WHEN level_id BETWEEN 1 AND 6 THEN level_id END) AS primary_level,
        MIN(CASE WHEN level_id BETWEEN 1 AND 6 THEN league_id END) AS primary_league
    FROM career_pit
    WHERE year = 2029 AND split_id = 1
    GROUP BY player_id
),
lg_p AS (
    SELECT
        league_id, year, level_id,
        ROUND(SUM(er)::DOUBLE * 9.0 / NULLIF((SUM(ip) + SUM(ipf) / 3.0), 0), 3) AS lg_era,
        SUM(ha) AS lg_ha, SUM(hra) AS lg_hra, SUM(bb) AS lg_bb, SUM(hp) AS lg_hp,
        SUM(k) AS lg_k, SUM(ab) AS lg_ab, SUM(bf) AS lg_bf,
        SUM(ip) + SUM(ipf) / 3.0 AS lg_ip
    FROM league_history_pitching_stats
    GROUP BY league_id, year, level_id
),
pitcher_park AS (
    SELECT p.player_id, prk.avg AS park_avg
    FROM players p
    LEFT JOIN teams t ON t.team_id = p.team_id
    LEFT JOIN parks prk ON prk.park_id = t.park_id
),
derived AS (
    SELECT
        a.player_id,
        a.g, a.gs, a.gf, a.w, a.l, a.sv, a.hld, a.outs,
        a.ha, a.hra, a.r, a.er, a.bb, a.k, a.hp, a.bf, a.ab, a.tb,
        a.gb, a.fb, a.pitches_thrown, a.dp, a.qs, a.svo, a.bs, a.cg, a.sho,
        a.sb_against, a.cs_against, a.iw, a.wp, a.bk, a.ir, a.irs, a.wpa, a.li_cum,
        a.sd, a.md, a.war, a.ra9war,
        a.primary_level, a.primary_league,
        -- IP: integer innings + (remaining outs * 0.1)
        ROUND(FLOOR(a.outs / 3.0) + (a.outs % 3) * 0.1, 1) AS ip,
        ROUND(9.0 * a.er / NULLIF(a.outs / 3.0, 0), 2) AS era,
        ROUND(1.0 * (a.ha + a.bb) / NULLIF(a.outs / 3.0, 0), 2) AS whip,
        ROUND(1.0 * a.ha / NULLIF(a.ab, 0), 3) AS opp_avg,
        ROUND(1.0 * (a.ha - a.hra) / NULLIF(a.ab - a.k - a.hra + a.sf, 0), 3) AS opp_babip,
        ROUND(9.0 * a.hra / NULLIF(a.outs / 3.0, 0), 2) AS hr9,
        ROUND(9.0 * a.bb  / NULLIF(a.outs / 3.0, 0), 2) AS bb9,
        ROUND(9.0 * a.k   / NULLIF(a.outs / 3.0, 0), 2) AS k9,
        ROUND(1.0 * a.k / NULLIF(a.bb, 0), 2) AS k_per_bb,
        ROUND(1.0 * a.w / NULLIF(a.w + a.l, 0), 3) AS win_pct,
        -- SV%: OOTP uses sv / (sv + bs) — successful saves / save situations.
        ROUND(1.0 * a.sv / NULLIF(a.sv + a.bs, 0), 3) AS sv_pct,
        ROUND(1.0 * a.qs / NULLIF(a.gs, 0), 3) AS qs_pct,
        ROUND(1.0 * a.cg / NULLIF(a.gs, 0), 3) AS cg_pct,
        -- GO% as decimal fraction (OOTP convention: 0.17 = 17%)
        ROUND(1.0 * a.gb / NULLIF(a.gb + a.fb, 0), 3) AS go_pct,
        -- PPG: OOTP truncates (FLOOR), not rounds.
        FLOOR(1.0 * a.pitches_thrown / NULLIF(a.g, 0)) AS ppg,
        -- IRS%: inherited runners scored as % (decimal fraction).
        ROUND(1.0 * a.irs / NULLIF(a.ir, 0), 3) AS irs_pct,
        -- RA = relief appearances = G - GS.
        (a.g - a.gs) AS ra_relief,
        -- RSG: run support per START (not per game). For pure relievers (gs=0)
        -- this is null/0 — IE shows 0.0.
        COALESCE(ROUND(1.0 * a.rs_total / NULLIF(a.gs, 0), 1), 0.0) AS rsg,
        -- pLi: career_pit.li is the cumulative leverage-index sum across
        -- all batters faced; pLi = sum(li) / sum(bf). Verified empirically
        -- against IE for MLB-only pitchers (Crochet 706/735≈0.96; Lei 624/270≈2.31).
        ROUND(1.0 * a.li_cum / NULLIF(a.bf, 0), 2) AS p_li,
        -- ERA+: 100 * lg_ERA / player_ERA * park_adjustment.
        -- Park adjustment ~ 1 + (parks.avg - 1) * 0.8 (fits ~1.04 for Fenway,
        -- which gives Crochet 127, IE 127). Per-level lg_ERA from
        -- league_history_pitching_stats.
        ROUND(
            100.0 * lg_p.lg_era / NULLIF(9.0 * a.er / NULLIF(a.outs / 3.0, 0), 0)
            * (1.0 + (COALESCE(pp.park_avg, 1.0) - 1.0) * 0.8), 0
        ) AS era_plus,
        -- FIP: ((13*HR + 3*(BB+HBP) - 2*K) / IP) + cFIP, where cFIP is the
        -- league-calibrated constant: cFIP = lg_ERA - lg_(13*HR + 3*BB+HBP - 2*K)/lg_IP.
        -- For non-MLB pitchers OOTP returns the actual FIP (no 100 default).
        ROUND(
            (13.0*a.hra + 3.0*(a.bb + a.hp) - 2.0*a.k) / NULLIF(a.outs / 3.0, 0)
            + (lg_p.lg_era - (13.0*lg_p.lg_hra + 3.0*(lg_p.lg_bb + lg_p.lg_hp) - 2.0*lg_p.lg_k) / NULLIF(lg_p.lg_ip, 0)),
            2
        ) AS fip
    FROM agg a
    LEFT JOIN lg_p ON lg_p.league_id = a.primary_league AND lg_p.year = 2029 AND lg_p.level_id = a.primary_level
    LEFT JOIN pitcher_park pp ON pp.player_id = a.player_id
)
"""

PITCHING_STATS_1 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_stats_1.csv",
    short_name="pitching_stats_1",
    derived_cte=PITCHING_DERIVED_CTE,
    cols=[
        ColSpec("G",     "g",     "A"),
        ColSpec("GS",    "gs",    "A"),
        ColSpec("W",     "w",     "A"),
        ColSpec("L",     "l",     "A"),
        ColSpec("SV",    "sv",    "A"),
        ColSpec("HLD",   "hld",   "A"),
        ColSpec("IP",    "ip",    "B", tolerance=0.1),
        ColSpec("HA",    "ha",    "A"),
        ColSpec("HR",    "hra",   "A"),
        ColSpec("R",     "r",     "A"),
        ColSpec("ER",    "er",    "A"),
        ColSpec("BB",    "bb",    "A"),
        ColSpec("K",     "k",     "A"),
        ColSpec("HP",    "hp",    "A"),
        ColSpec("ERA",   "era",   "B", tolerance=0.05),
        ColSpec("AVG",   "opp_avg",  "B", tolerance=RATE_TOLERANCE),
        ColSpec("BABIP", "opp_babip","B", tolerance=RATE_TOLERANCE),
        ColSpec("WHIP",  "whip",  "B", tolerance=0.02),
        ColSpec("HR/9",  "hr9",   "B", tolerance=0.1),
        ColSpec("BB/9",  "bb9",   "B", tolerance=0.1),
        ColSpec("K/9",   "k9",    "B", tolerance=0.1),
        ColSpec("K/BB",  "k_per_bb", "B", tolerance=0.05),
        ColSpec("ERA+",  "era_plus", "B", tolerance=2,
                notes="100 * lg_ERA / pERA * (1 + (park.avg-1)*0.8); 100 default for non-MLB"),
        ColSpec("FIP",   "fip",   "B", tolerance=0.1,
                notes="(13*HR + 3*(BB+HBP) - 2*K)/IP + lg-calibrated cFIP"),
        # WAR off by 0.1 in some multi-org cases due to per-stint rounding cascade.
        ColSpec("WAR",   "ROUND(d.war, 1)", "A", tolerance=0.15,
                notes="career_pit.war (FIP-WAR), summed across stints"),
    ],
)


# Fielding career — sum across positions per player. Note: fielding uses split_id=0
# (no platoon splits for fielding) and aggregates across the full Red Sox org.
FIELDING_DERIVED_CTE = f"""
derived AS (
    SELECT
        cf.player_id,
        SUM(cf.g) AS g, SUM(cf.gs) AS gs,
        SUM(cf.tc) AS tc, SUM(cf.a) AS a, SUM(cf.po) AS po,
        SUM(cf.e) AS e, SUM(cf.dp) AS dp, SUM(cf.tp) AS tp,
        SUM(cf.pb) AS pb, SUM(cf.sba) AS sba, SUM(cf.rto) AS rto,
        SUM(cf.zr) AS zr, SUM(cf.framing) AS frm, SUM(cf.arm) AS arm,
        SUM(cf.ipf) AS ipf,
        ROUND(1.0 * SUM(cf.po + cf.a) / NULLIF(SUM(cf.po + cf.a + cf.e), 0), 3) AS pct
    FROM career_field cf
    WHERE cf.year = 2029 AND cf.split_id = 0
    GROUP BY cf.player_id
)
"""

FIELDING_STATS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_fielding_stats.csv",
    short_name="fielding_stats",
    derived_cte=FIELDING_DERIVED_CTE,
    cols=[
        ColSpec("G",   "g",   "A"),
        ColSpec("GS",  "gs",  "A"),
        ColSpec("TC",  "tc",  "A"),
        ColSpec("A",   "a",   "A"),
        ColSpec("PO",  "po",  "A"),
        ColSpec("E",   "e",   "A"),
        ColSpec("DP",  "dp",  "A"),
        ColSpec("PCT", "pct", "B", tolerance=RATE_TOLERANCE),
        ColSpec("ZR",  "zr",  "A", tolerance=0.5,
                notes="career_field.zr summed across positions"),
        ColSpec("PB",  "pb",  "A"),
        ColSpec("FRM", "frm", "A", tolerance=0.5),
        ColSpec("ARM", "arm", "A", tolerance=0.5),
    ],
)


# Ratings — 20-80 scale. Take the player's OWN org's scouting view (scouting_team_id=4 for Red Sox).
RATINGS_DERIVED_CTE = """
derived AS (
    SELECT
        sr.player_id,
        sr.overall_rating AS ovr_2080,    -- already 20-80 in dump
        sr.talent_rating  AS pot_2080,    -- already 20-80 in dump
        sr.batting_ratings_overall_contact      AS con,
        sr.batting_ratings_overall_gap          AS gap,
        sr.batting_ratings_overall_power        AS pow,
        sr.batting_ratings_overall_eye          AS eye,
        sr.batting_ratings_overall_strikeouts   AS k_rating,
        sr.batting_ratings_overall_babip        AS babip_rating,
        sr.batting_ratings_vsr_contact          AS con_vr,
        sr.batting_ratings_vsr_power            AS pow_vr,
        sr.batting_ratings_vsr_eye              AS eye_vr,
        sr.batting_ratings_vsl_contact          AS con_vl,
        sr.batting_ratings_vsl_power            AS pow_vl,
        sr.batting_ratings_vsl_eye              AS eye_vl,
        sr.batting_ratings_misc_bunt            AS bun,
        sr.batting_ratings_misc_bunt_for_hit    AS bfh,
        sr.running_ratings_speed                AS spe,
        sr.running_ratings_stealing             AS ste,
        sr.running_ratings_baserunning          AS run,
        -- DEF = the player's fielding rating at their primary position
        -- (sr.position is 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF).
        -- NOT max-of-positions; a 3B with strong 1B/LF backup ratings still
        -- shows the 3B number in IE.
        CASE sr.position
            WHEN 1 THEN sr.fielding_rating_pos1
            WHEN 2 THEN sr.fielding_rating_pos2
            WHEN 3 THEN sr.fielding_rating_pos3
            WHEN 4 THEN sr.fielding_rating_pos4
            WHEN 5 THEN sr.fielding_rating_pos5
            WHEN 6 THEN sr.fielding_rating_pos6
            WHEN 7 THEN sr.fielding_rating_pos7
            WHEN 8 THEN sr.fielding_rating_pos8
            WHEN 9 THEN sr.fielding_rating_pos9
        END AS def
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4    -- Red Sox view
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""

BATTING_RATINGS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_ratings.csv",
    short_name="batting_ratings",
    derived_cte=RATINGS_DERIVED_CTE,
    cols=[
        ColSpec("OVR",     "ovr_2080",   "A", tolerance=RATING_TOLERANCE,
                notes="dump.scouted_ratings.overall_rating (already 20-80)"),
        ColSpec("CON",     "con",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("BABIP",   "babip_rating", "A", tolerance=RATING_TOLERANCE),
        ColSpec("K's",     "k_rating",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("GAP",     "gap",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("POW",     "pow",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("EYE",     "eye",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("CON vL",  "con_vl",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("POW vL",  "pow_vl",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("EYE vL",  "eye_vl",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("CON vR",  "con_vr",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("POW vR",  "pow_vr",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("EYE vR",  "eye_vr",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("BUN",     "bun",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("BFH",     "bfh",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("SPE",     "spe",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("STE",     "ste",        "A", tolerance=RATING_TOLERANCE),
        ColSpec("DEF",     "def",        "A", tolerance=RATING_TOLERANCE,
                notes="fielding_rating_pos[player.position] — primary-position rating, not max"),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group A — Ratings & potential (5 files, all from `scouted_ratings`)
# ─────────────────────────────────────────────────────────────────────────────


# Reuses RATINGS_DERIVED_CTE base: pulls the Red Sox scouting-team view of every
# player at scouting_team_id=4. We just extend it with potential / pitching /
# fielding / per-pitch columns by referencing scouted_ratings directly.

POTENTIAL_DERIVED_CTE = """
derived AS (
    SELECT
        sr.player_id,
        sr.overall_rating AS ovr_2080,
        sr.talent_rating  AS pot_2080,
        -- Batting potential
        sr.batting_ratings_talent_contact      AS con_p,
        sr.batting_ratings_talent_gap          AS gap_p,
        sr.batting_ratings_talent_power        AS pow_p,
        sr.batting_ratings_talent_eye          AS eye_p,
        sr.batting_ratings_talent_strikeouts   AS k_p,
        sr.batting_ratings_talent_babip        AS ht_p,
        -- Running (no potential, take current)
        sr.running_ratings_speed               AS spe,
        sr.running_ratings_stealing            AS ste,
        sr.running_ratings_baserunning         AS run,
        -- DEF in batting_potential is the *current* primary-position rating
        -- (verified empirically; OOTP's potential view shows current DEF).
        CASE sr.position
            WHEN 1 THEN sr.fielding_rating_pos1
            WHEN 2 THEN sr.fielding_rating_pos2
            WHEN 3 THEN sr.fielding_rating_pos3
            WHEN 4 THEN sr.fielding_rating_pos4
            WHEN 5 THEN sr.fielding_rating_pos5
            WHEN 6 THEN sr.fielding_rating_pos6
            WHEN 7 THEN sr.fielding_rating_pos7
            WHEN 8 THEN sr.fielding_rating_pos8
            WHEN 9 THEN sr.fielding_rating_pos9
        END AS def
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""


BATTING_POTENTIAL = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_potential.csv",
    short_name="batting_potential",
    derived_cte=POTENTIAL_DERIVED_CTE,
    cols=[
        ColSpec("POT",   "pot_2080", "A", tolerance=RATING_TOLERANCE),
        ColSpec("CON P", "con_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("HT P",  "ht_p",     "A", tolerance=RATING_TOLERANCE,
                notes="best-guess: batting_ratings_talent_babip"),
        ColSpec("K P",   "k_p",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("GAP P", "gap_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("POW P", "pow_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("EYE P", "eye_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("SPE",   "spe",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("STE",   "ste",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("RUN",   "run",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("DEF",   "def",      "A", tolerance=RATING_TOLERANCE,
                notes="fielding_rating_pos[player.position] (current, not potential)"),
    ],
)


PITCHING_RATINGS_CTE = """
derived AS (
    SELECT
        sr.player_id,
        sr.overall_rating AS ovr_2080,
        sr.talent_rating  AS pot_2080,
        -- Pitching overall
        sr.pitching_ratings_overall_stuff      AS stu,
        sr.pitching_ratings_overall_movement   AS mov,
        sr.pitching_ratings_overall_hra        AS hra,
        sr.pitching_ratings_overall_pbabip     AS pbabip,
        sr.pitching_ratings_overall_control    AS con,
        sr.pitching_ratings_vsl_stuff          AS stu_vl,
        sr.pitching_ratings_vsr_stuff          AS stu_vr,
        -- Pitching talent
        sr.pitching_ratings_talent_stuff       AS stu_p,
        sr.pitching_ratings_talent_movement    AS mov_p,
        sr.pitching_ratings_talent_hra         AS hra_p,
        sr.pitching_ratings_talent_pbabip      AS pbabip_p,
        sr.pitching_ratings_talent_control     AS con_p,
        -- Misc — VELO and G/F translated to IE display strings.
        -- VELO is a 0-19 ordinal: 0 -> '-', 1 -> '75-80 Mph', then the band
        -- shifts: at velo=2 the floor jumps from 75 to 80, then advances
        -- by 1 mph per level. Verified 220/220 against IE pitching_ratings.
        CASE sr.pitching_ratings_misc_velocity
            WHEN 0 THEN NULL
            WHEN 1 THEN '75-80 Mph'
            WHEN 2 THEN '80-83 Mph'
            WHEN 3 THEN '83-85 Mph'
            WHEN 4 THEN '84-86 Mph' WHEN 5 THEN '85-87 Mph'
            WHEN 6 THEN '86-88 Mph' WHEN 7 THEN '87-89 Mph'
            WHEN 8 THEN '88-90 Mph' WHEN 9 THEN '89-91 Mph'
            WHEN 10 THEN '90-92 Mph' WHEN 11 THEN '91-93 Mph'
            WHEN 12 THEN '92-94 Mph' WHEN 13 THEN '93-95 Mph'
            WHEN 14 THEN '94-96 Mph' WHEN 15 THEN '95-97 Mph'
            WHEN 16 THEN '96-98 Mph' WHEN 17 THEN '97-99 Mph'
            WHEN 18 THEN '98-100 Mph' WHEN 19 THEN '99-101 Mph'
        END AS velo,
        sr.pitching_ratings_misc_stamina       AS stm,
        -- G/F: pitching_ratings_misc_ground_fly is 0-100 internal scale.
        -- Buckets verified empirically:  <44=EX FB, 44-48=FB, 49-58=NEU, 59-63=GB, >=64=EX GB.
        CASE
            WHEN sr.pitching_ratings_misc_ground_fly <  44 THEN 'EX FB'
            WHEN sr.pitching_ratings_misc_ground_fly <  49 THEN 'FB'
            WHEN sr.pitching_ratings_misc_ground_fly <  59 THEN 'NEU'
            WHEN sr.pitching_ratings_misc_ground_fly <  64 THEN 'GB'
            ELSE 'EX GB'
        END AS go_fly,
        sr.pitching_ratings_misc_hold          AS hld,
        sr.pitching_ratings_misc_arm_slot      AS arm_slot
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""


PITCHING_RATINGS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_ratings.csv",
    short_name="pitching_ratings",
    derived_cte=PITCHING_RATINGS_CTE,
    cols=[
        ColSpec("OVR",    "ovr_2080", "A", tolerance=RATING_TOLERANCE),
        ColSpec("STU",    "stu",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("MOV",    "mov",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("HRA",    "hra",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("PBABIP", "pbabip",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("CON",    "con",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("STU vL", "stu_vl",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("STU vR", "stu_vr",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("VELO",   "velo",     "A", notes="integer 0-19 -> '75-80 Mph' band string"),
        ColSpec("STM",    "stm",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("G/F",    "go_fly",   "A", notes="ground_fly 0-100 -> EX FB/FB/NEU/GB/EX GB buckets"),
        ColSpec("HLD",    "hld",      "A", tolerance=RATING_TOLERANCE),
    ],
)


PITCHING_POTENTIAL = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_potential.csv",
    short_name="pitching_potential",
    derived_cte=PITCHING_RATINGS_CTE,
    cols=[
        ColSpec("POT",      "pot_2080", "A", tolerance=RATING_TOLERANCE),
        ColSpec("STU P",    "stu_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("MOV P",    "mov_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("HRA P",    "hra_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("PBABIP P", "pbabip_p", "A", tolerance=RATING_TOLERANCE),
        ColSpec("CON P",    "con_p",    "A", tolerance=RATING_TOLERANCE),
        ColSpec("VELO",     "velo",     "A", notes="integer 0-19 -> '75-80 Mph' band string"),
        ColSpec("STM",      "stm",      "A", tolerance=RATING_TOLERANCE),
        ColSpec("G/F",      "go_fly",   "A", notes="ground_fly 0-100 -> EX FB/FB/NEU/GB/EX GB buckets"),
        ColSpec("HLD",      "hld",      "A", tolerance=RATING_TOLERANCE),
    ],
)


FIELDING_RATINGS_CTE = """
derived AS (
    SELECT
        sr.player_id,
        sr.fielding_ratings_catcher_ability    AS c_abi,
        sr.fielding_ratings_catcher_arm        AS c_arm,
        sr.fielding_ratings_infield_range      AS if_rng,
        sr.fielding_ratings_infield_error      AS if_err,
        sr.fielding_ratings_infield_arm        AS if_arm,
        sr.fielding_ratings_turn_doubleplay    AS tdp,
        sr.fielding_ratings_outfield_range     AS of_rng,
        sr.fielding_ratings_outfield_error     AS of_err,
        sr.fielding_ratings_outfield_arm       AS of_arm
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""


FIELDING_RATINGS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_fielding_ratings.csv",
    short_name="fielding_ratings",
    derived_cte=FIELDING_RATINGS_CTE,
    cols=[
        ColSpec("C ABI",  "c_abi",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("C ARM",  "c_arm",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("IF RNG", "if_rng",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("IF ERR", "if_err",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("IF ARM", "if_arm",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("TDP",    "tdp",     "A", tolerance=RATING_TOLERANCE),
        ColSpec("OF RNG", "of_rng",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("OF ERR", "of_err",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("OF ARM", "of_arm",  "A", tolerance=RATING_TOLERANCE),
    ],
)


PITCH_RATINGS_CTE = """
derived AS (
    SELECT
        sr.player_id,
        -- current
        sr.pitching_ratings_pitches_fastball     AS fb,
        sr.pitching_ratings_pitches_changeup     AS ch,
        sr.pitching_ratings_pitches_curveball    AS cb,
        sr.pitching_ratings_pitches_slider       AS sl,
        sr.pitching_ratings_pitches_sinker       AS si,
        sr.pitching_ratings_pitches_splitter     AS sp,
        sr.pitching_ratings_pitches_cutter       AS ct,
        sr.pitching_ratings_pitches_forkball     AS fo,
        sr.pitching_ratings_pitches_circlechange AS cc,
        sr.pitching_ratings_pitches_screwball    AS sc,
        sr.pitching_ratings_pitches_knucklecurve AS kc,
        sr.pitching_ratings_pitches_knuckleball  AS kn,
        -- potential
        sr.pitching_ratings_pitches_talent_fastball     AS fbp,
        sr.pitching_ratings_pitches_talent_changeup     AS chp,
        sr.pitching_ratings_pitches_talent_curveball    AS cbp,
        sr.pitching_ratings_pitches_talent_slider       AS slp,
        sr.pitching_ratings_pitches_talent_sinker       AS sip,
        sr.pitching_ratings_pitches_talent_splitter     AS spp,
        sr.pitching_ratings_pitches_talent_cutter       AS ctp,
        sr.pitching_ratings_pitches_talent_forkball     AS fop,
        sr.pitching_ratings_pitches_talent_circlechange AS ccp,
        sr.pitching_ratings_pitches_talent_screwball    AS scp,
        sr.pitching_ratings_pitches_talent_knucklecurve AS kcp,
        sr.pitching_ratings_pitches_talent_knuckleball  AS knp,
        CASE sr.pitching_ratings_misc_velocity
            WHEN 0 THEN NULL
            WHEN 1 THEN '75-80 Mph' WHEN 2 THEN '80-83 Mph' WHEN 3 THEN '83-85 Mph'
            WHEN 4 THEN '84-86 Mph' WHEN 5 THEN '85-87 Mph' WHEN 6 THEN '86-88 Mph'
            WHEN 7 THEN '87-89 Mph' WHEN 8 THEN '88-90 Mph' WHEN 9 THEN '89-91 Mph'
            WHEN 10 THEN '90-92 Mph' WHEN 11 THEN '91-93 Mph' WHEN 12 THEN '92-94 Mph'
            WHEN 13 THEN '93-95 Mph' WHEN 14 THEN '94-96 Mph' WHEN 15 THEN '95-97 Mph'
            WHEN 16 THEN '96-98 Mph' WHEN 17 THEN '97-99 Mph' WHEN 18 THEN '98-100 Mph'
            WHEN 19 THEN '99-101 Mph'
        END AS velo,
        sr.pitching_ratings_misc_stamina                 AS stm,
        -- PIT = count of non-zero pitch ratings
        (CASE WHEN sr.pitching_ratings_pitches_fastball  > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_changeup  > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_curveball > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_slider    > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_sinker    > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_splitter  > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_cutter    > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_forkball  > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_circlechange > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_screwball > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_knucklecurve > 0 THEN 1 ELSE 0 END
       + CASE WHEN sr.pitching_ratings_pitches_knuckleball  > 0 THEN 1 ELSE 0 END) AS pit
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""


INDIVIDUAL_PITCH_RATINGS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_individual_pitch_ratings.csv",
    short_name="individual_pitch_ratings",
    derived_cte=PITCH_RATINGS_CTE,
    cols=[
        ColSpec("FB",   "fb",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("CH",   "ch",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("CB",   "cb",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("SL",   "sl",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("SI",   "si",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("SP",   "sp",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("CT",   "ct",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("FO",   "fo",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("CC",   "cc",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("SC",   "sc",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("KC",   "kc",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("KN",   "kn",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("PIT",  "pit",  "A", notes="count of non-zero pitch ratings"),
        ColSpec("VELO", "velo", "A", notes="integer 0-19 -> '75-80 Mph' band string"),
        ColSpec("STM",  "stm",  "A", tolerance=RATING_TOLERANCE),
    ],
)


INDIVIDUAL_PITCH_POTENTIAL = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_individual_pitch_potential.csv",
    short_name="individual_pitch_potential",
    derived_cte=PITCH_RATINGS_CTE,
    cols=[
        ColSpec("FBP",  "fbp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("CHP",  "chp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("CBP",  "cbp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("SLP",  "slp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("SIP",  "sip",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("SPP",  "spp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("CTP",  "ctp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("FOP",  "fop",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("CCP",  "ccp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("SCP",  "scp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("KCP",  "kcp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("KNP",  "knp",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("PIT",  "pit",  "A", notes="count of non-zero pitch ratings"),
        ColSpec("VELO", "velo", "A", notes="integer 0-19 -> '75-80 Mph' band string"),
        ColSpec("STM",  "stm",  "A", tolerance=RATING_TOLERANCE),
    ],
)


POSITION_RATINGS_CTE = """
derived AS (
    SELECT
        sr.player_id,
        sr.fielding_rating_pos1 AS p,
        sr.fielding_rating_pos2 AS c,
        sr.fielding_rating_pos3 AS b1,
        sr.fielding_rating_pos4 AS b2,
        sr.fielding_rating_pos5 AS b3,
        sr.fielding_rating_pos6 AS ss,
        sr.fielding_rating_pos7 AS lf,
        sr.fielding_rating_pos8 AS cf,
        sr.fielding_rating_pos9 AS rf,
        CASE sr.position
            WHEN 1 THEN sr.fielding_rating_pos1
            WHEN 2 THEN sr.fielding_rating_pos2
            WHEN 3 THEN sr.fielding_rating_pos3
            WHEN 4 THEN sr.fielding_rating_pos4
            WHEN 5 THEN sr.fielding_rating_pos5
            WHEN 6 THEN sr.fielding_rating_pos6
            WHEN 7 THEN sr.fielding_rating_pos7
            WHEN 8 THEN sr.fielding_rating_pos8
            WHEN 9 THEN sr.fielding_rating_pos9
        END AS def
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4
    -- No league filter: each Red Sox-org player has exactly 1 row at
    -- team=4 across all leagues, so this widens the joined population
    -- from 24 (MLB only) to all 220 IE roster rows.
)
"""


POSITION_RATINGS = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_position_ratings.csv",
    short_name="position_ratings",
    derived_cte=POSITION_RATINGS_CTE,
    cols=[
        ColSpec("DEF", "def", "A", tolerance=RATING_TOLERANCE,
                notes="fielding_rating_pos[player.position]"),
        ColSpec("P",   "p",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("C",   "c",   "A", tolerance=RATING_TOLERANCE),
        ColSpec("1B",  "b1",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("2B",  "b2",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("3B",  "b3",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("SS",  "ss",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("LF",  "lf",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("CF",  "cf",  "A", tolerance=RATING_TOLERANCE),
        ColSpec("RF",  "rf",  "A", tolerance=RATING_TOLERANCE),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group B — pitching_stats_2 (career_pit-backed, extends PITCHING_DERIVED_CTE)
# ─────────────────────────────────────────────────────────────────────────────


PITCHING_STATS_2 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_stats_2.csv",
    short_name="pitching_stats_2",
    derived_cte=PITCHING_DERIVED_CTE,
    cols=[
        ColSpec("G",     "g",       "A"),
        ColSpec("WIN%",  "win_pct", "B", tolerance=RATE_TOLERANCE),
        ColSpec("SV%",   "sv_pct",  "B", tolerance=RATE_TOLERANCE,
                notes="OOTP uses sv / (sv + bs)"),
        ColSpec("BS",    "bs",      "A"),
        ColSpec("SD",    "sd",      "A"),
        ColSpec("MD",    "md",      "A"),
        ColSpec("IP",    "ip",      "B", tolerance=0.1),
        ColSpec("BF",    "bf",      "A"),
        ColSpec("DP",    "dp",      "A"),
        # RA = relief appearances = G - GS (verified empirically: Lei 64=64, Tolle 74=74)
        ColSpec("RA",    "ra_relief", "B", notes="g - gs (relief appearances)"),
        ColSpec("GF",    "gf",      "A"),
        ColSpec("IR",    "ir",      "A"),
        ColSpec("IRS%",  "ROUND(100.0 * d.irs / NULLIF(d.ir, 0), 1)", "B", tolerance=0.5),
        # pLi = SUM(li) / SUM(bf) where li is the cumulative leverage index sum
        # across batters faced. Verified Crochet 706/735~0.96, Lei 624/270~2.31.
        ColSpec("pLi",   "p_li",    "B", tolerance=0.05,
                notes="career_pit.li is cumulative LI sum across BFs; pLi = sum(li)/sum(bf)"),
        ColSpec("QS",    "qs",      "A"),
        ColSpec("QS%",   "qs_pct",  "B", tolerance=RATE_TOLERANCE),
        ColSpec("CG",    "cg",      "A"),
        ColSpec("CG%",   "cg_pct",  "B", tolerance=RATE_TOLERANCE),
        ColSpec("SHO",   "sho",     "A"),
        # PPG presented as integer in IE, derived as decimal — round to int.
        ColSpec("PPG",   "ROUND(d.ppg, 0)", "B"),
        # RSG = run support per START (rs / gs), not per game. Pure relievers
        # show 0.0. Verified Crochet 94/33=2.85 ~= IE 2.8.
        ColSpec("RSG",   "rsg",     "B", tolerance=0.05,
                notes="run support per start (rs/gs); 0.0 for pure relievers"),
        # GO% in IE is a decimal fraction with 2-decimal precision (0.17 = 17%).
        ColSpec("GO%",   "ROUND(d.go_pct, 2)", "B", tolerance=RATE_TOLERANCE),
        ColSpec("SIERA", "NULL",    "C", notes="complex sabermetric formula; needs custom impl"),
        ColSpec("SB",    "sb_against", "A"),
        ColSpec("CS",    "cs_against", "A"),
        ColSpec("WPA",   "ROUND(d.wpa, 1)", "A", tolerance=0.05),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group C — Statcast superstats_1 (at-bat-derived)
# ─────────────────────────────────────────────────────────────────────────────


# Batter Statcast: aggregate at-bat events per batter.
# AtBatResult codes: 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR.
# BIP = ground/fly outs + all hits (codes 4,5,6,7,8,9).
# Statcast values populated mainly for MLB at-bats (non-MLB at-bats lack EV/LA).
BATTING_SUPERSTATS_CTE = """
ab AS (
    -- Filter to regular-season at-bats (game_type=0) only — IE Statcast cols
    -- mirror PCB split_id=1 (regular-season-only); including spring training
    -- (g.game_type=2) and postseason (g.game_type=3) inflates BIP/EV/HHi
    -- by 5-15% for MLB regulars.
    --
    -- Join in batter's bats and pitcher's throws so we can decode spray
    -- direction. Switch hitters (bats=3) bat opposite to pitcher's throwing
    -- hand: vs RHP -> bats L, vs LHP -> bats R. hit_xy is a packed 16x16
    -- coord; x = hit_xy/16 with x in [0,4]=LF-side, [5,10]=CF, [11,15]=RF-side.
    SELECT
        a.player_id,
        a.result, a.exit_velo, a.launch_angle, a.hit_loc, a.sac, a.hit_xy,
        CASE
            WHEN bat.bats = 1 THEN 'R'
            WHEN bat.bats = 2 THEN 'L'
            WHEN bat.bats = 3 AND pit.throws = 1 THEN 'L'
            WHEN bat.bats = 3 AND pit.throws = 2 THEN 'R'
        END AS eff_bats,
        CASE
            WHEN a.hit_xy IS NULL THEN NULL
            WHEN FLOOR(a.hit_xy / 16) <= 4 THEN 'LF'
            WHEN FLOOR(a.hit_xy / 16) <= 10 THEN 'CF'
            ELSE 'RF'
        END AS spray_zone
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    LEFT JOIN players bat ON bat.player_id = a.player_id
    LEFT JOIN players pit ON pit.player_id = a.opponent_player_id
),
agg AS (
    SELECT
        player_id,
        -- BIP excludes sacrifices (sac=1 bunt, sac=2 SF) per OOTP convention.
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS bip,
        COUNT(*) FILTER (WHERE result = 9) AS hr,
        -- LA buckets (Statcast): GB <10, LD 10-25, FB 25-50, PU >50.
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle < 10) AS gb_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle BETWEEN 10 AND 25) AS ld_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle BETWEEN 25 AND 50) AS fb_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle > 50) AS pu_la,
        -- Spray counts (only BIP with hit_xy populated).
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND spray_zone = 'CF') AS cent,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0
                           AND ((eff_bats='R' AND spray_zone='LF')
                             OR (eff_bats='L' AND spray_zone='RF'))) AS pull,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0
                           AND ((eff_bats='R' AND spray_zone='RF')
                             OR (eff_bats='L' AND spray_zone='LF'))) AS oppo,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0
                           AND spray_zone IS NOT NULL AND eff_bats IS NOT NULL) AS spray_bip,
        -- EV buckets — calibrated against MLB-only Sox players: Soft<75 / Avg 75-95 / Solid>=95.
        -- (Original Statcast convention is 80/95; OOTP runs a hair lower on the soft cutoff.)
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo > 0 AND exit_velo < 75) AS soft,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo >= 75 AND exit_velo < 95) AS avg_ev,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo >= 95) AS solid,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo >= 95) AS hhi,
        -- Barrel — calibrated empirically. OOTP uses a simple flat threshold,
        -- not Statcast's expanding cone: EV>=100 AND LA in [10..42]. Grid-search
        -- over the 9 MLB-only Sox starters chose this as the lowest-error fit
        -- (4/9 exact, 6/9 within ±1).
        COUNT(*) FILTER (
            WHERE result IN (4,5,6,7,8,9) AND sac = 0
              AND exit_velo >= 100
              AND launch_angle BETWEEN 10 AND 42
        ) AS bar,
        AVG(exit_velo)    FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS avg_ev_v,
        MAX(exit_velo)    FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS max_ev_v,
        AVG(launch_angle) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS avg_la_v,
        -- Pop-ups (LA > 50, infield) approximate IFFB.
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle > 50) AS pu_count,
        -- Bunt indicator: sac > 0 (bunt-attempt set; sac=1 is bunt, sac=2 sac-fly)
        COUNT(*) FILTER (WHERE sac = 1 AND result IN (6,7,8,9)) AS buh,
        COUNT(*) FILTER (WHERE sac = 1) AS bunt_attempts
    FROM ab
    GROUP BY player_id
),
derived AS (
    SELECT
        a.player_id,
        a.bip,
        -- GB/FB using LA buckets (matches OOTP convention).
        ROUND(1.0 * a.gb_la / NULLIF(a.fb_la + a.pu_la, 0), 2)                           AS gb_fb,
        ROUND(100.0 * a.ld_la / NULLIF(a.bip, 0), 1)                                     AS ld_pct,
        ROUND(100.0 * a.gb_la / NULLIF(a.bip, 0), 1)                                     AS gb_pct,
        ROUND(100.0 * (a.fb_la + a.pu_la) / NULLIF(a.bip, 0), 1)                         AS fb_pct,
        -- IFFB as % of FB (matches IE display).
        ROUND(100.0 * a.pu_count / NULLIF(a.fb_la + a.pu_la, 0), 1)                      AS iffb_pct,
        ROUND(100.0 * a.hr / NULLIF(a.fb_la + a.pu_la, 0), 1)                            AS hr_fb,
        NULL                                                                              AS ifh_pct,
        ROUND(100.0 * a.buh / NULLIF(a.bunt_attempts, 0), 1)                             AS buh_pct,
        ROUND(100.0 * a.pull / NULLIF(a.spray_bip, 0), 1)                                AS pull_pct,
        ROUND(100.0 * a.cent / NULLIF(a.spray_bip, 0), 1)                                AS cent_pct,
        ROUND(100.0 * a.oppo / NULLIF(a.spray_bip, 0), 1)                                AS oppo_pct,
        ROUND(100.0 * a.soft   / NULLIF(a.bip, 0), 1)                                    AS soft_pct,
        ROUND(100.0 * a.avg_ev / NULLIF(a.bip, 0), 1)                                    AS avg_pct,
        ROUND(100.0 * a.solid  / NULLIF(a.bip, 0), 1)                                    AS solid_pct,
        ROUND(a.avg_ev_v, 1)                                                             AS ev,
        ROUND(a.max_ev_v, 1)                                                             AS m_ev,
        ROUND(a.avg_la_v, 1)                                                             AS la,
        a.bar,
        ROUND(100.0 * a.bar / NULLIF(a.bip, 0), 1)                                       AS bar_pct,
        a.hhi,
        ROUND(100.0 * a.hhi / NULLIF(a.bip, 0), 1)                                       AS hhi_pct
    FROM agg a
)
"""


BATTING_SUPERSTATS_1 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_superstats_1.csv",
    short_name="batting_superstats_1",
    derived_cte=BATTING_SUPERSTATS_CTE,
    cols=[
        ColSpec("BIP",   "bip",       "E"),
        ColSpec("GB/FB", "gb_fb",     "E", tolerance=0.05),
        ColSpec("LD%",   "ld_pct",    "E", tolerance=1.0),
        ColSpec("GB%",   "gb_pct",    "E", tolerance=1.0),
        ColSpec("FB%",   "fb_pct",    "E", tolerance=1.0),
        ColSpec("IFFB",  "iffb_pct",  "E", tolerance=2.0, notes="pop-ups (LA>50) as % of FB"),
        ColSpec("HR/FB", "hr_fb",     "E", tolerance=2.0),
        ColSpec("IFH%",  "ifh_pct",   "E", notes="needs hit_loc decoding"),
        ColSpec("BUH%",  "buh_pct",   "E", tolerance=2.0),
        ColSpec("Pull%", "pull_pct",  "E", tolerance=2.0,
                notes="hit_xy/16 spray with [0,4]/[5,10]/[11,15] x-bins; consistent ~5-10pp under-count vs IE — exact OOTP spray boundary still TBD"),
        ColSpec("Cent%", "cent_pct",  "E", tolerance=2.0),
        ColSpec("Oppo%", "oppo_pct",  "E", tolerance=2.0,
                notes="consistent ~5-10pp over-count vs IE — same boundary issue as Pull%"),
        ColSpec("Soft%", "soft_pct",  "E", tolerance=2.0, notes="EV cutoff approx — TBD"),
        ColSpec("Avg%",  "avg_pct",   "E", tolerance=2.0),
        ColSpec("Solid%","solid_pct", "E", tolerance=2.0),
        ColSpec("EV",    "ev",        "E", tolerance=0.5),
        ColSpec("mEV",   "m_ev",      "E", tolerance=0.5),
        ColSpec("LA",    "la",        "E", tolerance=0.5),
        ColSpec("BAR",   "bar",       "E"),
        ColSpec("BAR%",  "bar_pct",   "E", tolerance=1.0),
        ColSpec("HHi",   "hhi",       "E"),
        ColSpec("HHi%",  "hhi_pct",   "E", tolerance=1.0),
        ColSpec("xBA",   "NULL",      "D", notes="modeled from EV/LA — not implemented"),
        ColSpec("xSLG",  "NULL",      "D"),
        ColSpec("xwOBA", "NULL",      "D"),
    ],
)


# Pitcher Statcast — same metrics but joined via opponent_player_id.
# Filtered to regular-season at-bats only (game_type=0); EV buckets calibrated
# to Soft<75 / Med 75-95 / Solid>=95 to match OOTP's IE convention.
PITCHING_SUPERSTATS_CTE = """
ab AS (
    SELECT
        a.opponent_player_id AS player_id,
        a.result, a.exit_velo, a.launch_angle, a.hit_loc, a.sac
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
),
agg AS (
    SELECT
        player_id,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS bip,
        COUNT(*) FILTER (WHERE result = 9) AS hr,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle < 10) AS gb_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle BETWEEN 10 AND 25) AS ld_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle BETWEEN 25 AND 50) AS fb_la,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle > 50) AS pu_la,
        -- EV buckets calibrated 2026-05-04 (75/95 cutoffs match IE far better than 85/100).
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo > 0 AND exit_velo < 75) AS soft,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo >= 75 AND exit_velo < 95) AS med_ev,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND exit_velo >= 95) AS solid,
        COUNT(*) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0 AND launch_angle > 50) AS pu_count,
        AVG(exit_velo) FILTER (WHERE result IN (4,5,6,7,8,9) AND sac = 0) AS avg_ev_v
    FROM ab
    WHERE player_id IS NOT NULL
    GROUP BY player_id
),
gp AS (
    SELECT player_id, SUM(g) AS g, SUM(gs) AS gs
    FROM career_pit
    WHERE year = 2029 AND split_id = 1
    GROUP BY player_id
),
derived AS (
    SELECT
        COALESCE(a.player_id, gp.player_id) AS player_id,
        gp.g, gp.gs,
        a.bip,
        ROUND(1.0 * a.gb_la / NULLIF(a.fb_la + a.pu_la, 0), 2)                AS gb_fb,
        ROUND(100.0 * a.ld_la / NULLIF(a.bip, 0), 1)                          AS ld_pct,
        ROUND(100.0 * a.gb_la / NULLIF(a.bip, 0), 1)                          AS gb_pct,
        ROUND(100.0 * (a.fb_la + a.pu_la) / NULLIF(a.bip, 0), 1)              AS fb_pct,
        ROUND(100.0 * a.pu_count / NULLIF(a.fb_la + a.pu_la, 0), 1)           AS iffb_pct,
        ROUND(100.0 * a.hr / NULLIF(a.fb_la + a.pu_la, 0), 1)                 AS hr_fb,
        ROUND(100.0 * a.soft   / NULLIF(a.bip, 0), 1)                         AS soft_pct,
        ROUND(100.0 * a.med_ev / NULLIF(a.bip, 0), 1)                         AS med_pct,
        ROUND(100.0 * a.solid  / NULLIF(a.bip, 0), 1)                         AS solid_pct,
        ROUND(a.avg_ev_v, 1)                                                  AS ev
    FROM gp
    LEFT JOIN agg a ON a.player_id = gp.player_id
)
"""


PITCHING_SUPERSTATS_1 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_superstats_1.csv",
    short_name="pitching_superstats_1",
    derived_cte=PITCHING_SUPERSTATS_CTE,
    cols=[
        ColSpec("G",     "g",         "A"),
        ColSpec("GS",    "gs",        "A"),
        ColSpec("BIP",   "bip",       "E"),
        ColSpec("GB/FB", "gb_fb",     "E", tolerance=0.05),
        ColSpec("LD%",   "ld_pct",    "E", tolerance=1.0),
        ColSpec("GB%",   "gb_pct",    "E", tolerance=1.0),
        ColSpec("FB%",   "fb_pct",    "E", tolerance=1.0),
        ColSpec("IFFB",  "iffb_pct",  "E", tolerance=2.0, notes="pop-ups (LA>50) as % of FB"),
        ColSpec("HR/FB", "hr_fb",     "E", tolerance=2.0),
        ColSpec("Soft%", "soft_pct",  "E", tolerance=2.0, notes="EV cutoff approx"),
        ColSpec("Med%",  "med_pct",   "E", tolerance=2.0),
        ColSpec("Solid%","solid_pct", "E", tolerance=2.0),
        ColSpec("EV",    "ev",        "E", tolerance=0.5),
        ColSpec("xBA",   "NULL",      "D"),
        ColSpec("xSLG",  "NULL",      "D"),
        ColSpec("xwOBA", "NULL",      "D"),
        ColSpec("xERA",  "NULL",      "D"),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group D — F-tier plate-discipline files (skip per Decision D5)
# ─────────────────────────────────────────────────────────────────────────────


F_TIER_CTE = """
derived AS (
    SELECT player_id FROM scouted_ratings WHERE 1=0
)
"""


BATTING_SUPERSTATS_2 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_batting_superstats_2.csv",
    short_name="batting_superstats_2",
    derived_cte=F_TIER_CTE,
    notes="All F-tier per Decision D5 — needs per-pitch zone/type data not in dump",
    cols=[
        ColSpec(c, "NULL", "F", notes="per-pitch zone/type data not in dump")
        for c in ("PI", "WH%", "CH%", "Z%", "CL%", "OS%", "ZS%", "SW%", "OC%",
                 "ZC%", "CTC%", "FF%", "BR%", "OFF%", "RV-FB", "RV-BR", "RV-OFF", "RV")
    ],
)


PITCHING_SUPERSTATS_2 = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_pitching_superstats_2.csv",
    short_name="pitching_superstats_2",
    derived_cte=F_TIER_CTE,
    notes="All F-tier per Decision D5",
    cols=[
        ColSpec(c, "NULL", "F", notes="per-pitch zone/type data not in dump")
        for c in ("PI", "SW", "WH", "CH", "OS%", "ZS%", "SW%", "OC%", "ZC%",
                 "Z%", "WH%", "CH%", "CL%", "RV-FB", "RV-BR", "RV-OFF", "RV")
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group E — Player metadata (default, popularity, personality)
# ─────────────────────────────────────────────────────────────────────────────


# `default` joins players (bio, morale, popularity) with scouted_ratings (OVR/POT)
# and contracts (SLR/YL). String fields like ORG/LG/Lev/NAT/HT/WT need lookup
# tables and aren't worth full reconciliation; we focus on numeric fields.
DEFAULT_DERIVED_CTE = """
sr AS (
    SELECT player_id, overall_rating, talent_rating, scouting_accuracy
    FROM scouted_ratings
    WHERE scouting_team_id = 4
    -- No league filter; each Red Sox-org player has 1 row at team=4
),
ct AS (
    SELECT player_id, salary0 AS slr, years AS yl, current_year AS cy
    FROM contracts
),
derived AS (
    SELECT
        p.player_id,
        p.age,
        sr.overall_rating AS ovr,
        sr.talent_rating  AS pot,
        ct.slr,
        (ct.yl - ct.cy + 1) AS yl,
        p.weight, p.height
    FROM players p
    LEFT JOIN sr ON sr.player_id = p.player_id
    LEFT JOIN ct ON ct.player_id = p.player_id
)
"""


DEFAULT = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_default.csv",
    short_name="default",
    derived_cte=DEFAULT_DERIVED_CTE,
    notes="Bio + ratings + contract overview. ORG/LG/Lev/NAT/HT/WT need string lookups (deferred).",
    cols=[
        ColSpec("Age", "age", "A"),
        ColSpec("OVR", "ovr", "A", tolerance=RATING_TOLERANCE),
        ColSpec("POT", "pot", "A", tolerance=RATING_TOLERANCE),
        # SLR formatted as "$X XXX XXX" string in IE; numeric compare not viable as-is
        ColSpec("SLR", "slr", "F", notes="formatted '$28 800 000' in IE — string mismatch by design"),
        ColSpec("YL",  "yl",  "F", notes="formatted '3' or '1 (auto.)' in IE — string mismatch"),
        ColSpec("MLY", "NULL", "F", notes="major-league years — derivation TBD"),
    ],
)


POPULARITY_DERIVED_CTE = """
sr AS (
    SELECT player_id, overall_rating, talent_rating, scouting_accuracy
    FROM scouted_ratings
    WHERE scouting_team_id = 4
),
derived AS (
    SELECT
        p.player_id,
        p.age,
        -- local_pop / national_pop are 0-6 ints; IE shows the label string
        CASE p.local_pop
            WHEN 0 THEN 'Unknown' WHEN 1 THEN 'Insignificant' WHEN 2 THEN 'Fair'
            WHEN 3 THEN 'Well Known' WHEN 4 THEN 'Popular' WHEN 5 THEN 'Very Popular'
            WHEN 6 THEN 'Extremely Popular'
        END AS local_pop,
        CASE p.national_pop
            WHEN 0 THEN 'Unknown' WHEN 1 THEN 'Insignificant' WHEN 2 THEN 'Fair'
            WHEN 3 THEN 'Well Known' WHEN 4 THEN 'Popular' WHEN 5 THEN 'Very Popular'
            WHEN 6 THEN 'Extremely Popular'
        END AS national_pop,
        -- scouting_accuracy 1-5 -> V.Low/Low/Avg/High/V.High
        CASE sr.scouting_accuracy
            WHEN 1 THEN 'V.Low' WHEN 2 THEN 'Low' WHEN 3 THEN 'Avg'
            WHEN 4 THEN 'High' WHEN 5 THEN 'V.High'
        END AS sct_acc,
        sr.overall_rating AS ovr,
        sr.talent_rating  AS pot
    FROM players p
    LEFT JOIN sr ON sr.player_id = p.player_id
)
"""


POPULARITY_INFO = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_popularity_info.csv",
    short_name="popularity_info",
    derived_cte=POPULARITY_DERIVED_CTE,
    cols=[
        ColSpec("Age", "age", "A"),
        ColSpec("Nat. Pop.", "national_pop", "A",
                notes="players.national_pop 0-6 -> Unknown/Insignificant/Fair/Well Known/Popular/Very Popular/Extremely Popular"),
        ColSpec("Loc. Pop.", "local_pop", "A",
                notes="players.local_pop 0-6 -> same 7-bucket scale"),
        ColSpec("OVR", "ovr", "A", tolerance=RATING_TOLERANCE),
        ColSpec("POT", "pot", "A", tolerance=RATING_TOLERANCE),
        ColSpec("SctAcc", "sct_acc", "A",
                notes="scouted_ratings.scouting_accuracy 1-5 -> V.Low/Low/Avg/High/V.High"),
    ],
)


PERSONALITY_DERIVED_CTE = """
derived AS (
    SELECT
        p.player_id,
        p.age,
        -- 0-200 personality values bucket as <60='Low', 60-139='Normal', >=140='High'.
        -- IE shows 'Unknown' for ~4 newly-acquired-2029 players the org hasn't
        -- fully scouted yet (experience<=1, acquired_date in current year);
        -- the bucket logic still produces a hard label for them and they'll
        -- show up as a small mismatch.
        CASE WHEN p.personality_leader      < 60 THEN 'Low'
             WHEN p.personality_leader      < 140 THEN 'Normal'
             ELSE 'High' END AS lea,
        CASE WHEN p.personality_loyalty     < 60 THEN 'Low'
             WHEN p.personality_loyalty     < 140 THEN 'Normal'
             ELSE 'High' END AS loy,
        CASE WHEN p.personality_greed       < 60 THEN 'Low'
             WHEN p.personality_greed       < 140 THEN 'Normal'
             ELSE 'High' END AS fin,
        CASE WHEN p.personality_work_ethic  < 60 THEN 'Low'
             WHEN p.personality_work_ethic  < 140 THEN 'Normal'
             ELSE 'High' END AS we,
        CASE WHEN p.personality_intelligence < 60 THEN 'Low'
             WHEN p.personality_intelligence < 140 THEN 'Normal'
             ELSE 'High' END AS int_rating
    FROM players p
)
"""


PERSONALITY_MORALE = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_personality___morale.csv",
    short_name="personality___morale",
    derived_cte=PERSONALITY_DERIVED_CTE,
    notes="LEA/LOY/FIN/WE/INT bucketed Low/Normal/High; morale columns (Inf/Txn/Tm/Perf/Role/Chem/Mor) are NULL in IE for org rosters",
    cols=[
        ColSpec("Age",  "age",         "A"),
        ColSpec("LEA",  "lea",         "A", notes="personality_leader bucketed (<60/60-139/>=140)"),
        ColSpec("LOY",  "loy",         "A", notes="personality_loyalty bucketed"),
        ColSpec("FIN",  "fin",         "A", notes="personality_greed bucketed"),
        ColSpec("WE",   "we",          "A", notes="personality_work_ethic bucketed"),
        ColSpec("INT",  "int_rating",  "A", notes="personality_intelligence bucketed"),
    ],
)


# ─────────────────────────────────────────────────────────────────────────────
# Group F — financial_info (contracts-backed)
# ─────────────────────────────────────────────────────────────────────────────


FINANCIAL_DERIVED_CTE = """
ct AS (
    SELECT
        player_id, salary0, years, current_year,
        salary0 + COALESCE(salary1,0) + COALESCE(salary2,0) + COALESCE(salary3,0)
                + COALESCE(salary4,0) + COALESCE(salary5,0) + COALESCE(salary6,0)
                + COALESCE(salary7,0) AS contract_value
    FROM contracts
),
derived AS (
    SELECT
        p.player_id,
        p.age,
        ct.salary0     AS slr,
        ct.years       AS ty,
        ct.current_year,
        (ct.years - ct.current_year + 1) AS yl,
        ct.contract_value AS cv
    FROM players p
    LEFT JOIN ct ON ct.player_id = p.player_id
)
"""


FINANCIAL_INFO = FileSpec(
    ie_filename="boston_red_sox_organization_-_roster_financial_info.csv",
    short_name="financial_info",
    derived_cte=FINANCIAL_DERIVED_CTE,
    notes="SLR/CV formatted as '$X XXX XXX' strings in IE — numeric compare won't match",
    cols=[
        ColSpec("Age", "age", "A"),
        ColSpec("SLR", "slr", "F", notes="dollar-formatted string in IE"),
        ColSpec("YL",  "yl",  "F", notes="formatted '3' or '1 (auto.)' in IE"),
        ColSpec("CV",  "cv",  "F", notes="dollar-formatted string in IE"),
        ColSpec("TY",  "ty",  "A", notes="contract years total"),
        ColSpec("ECV", "NULL", "C", notes="extension contract value — needs contract_extension table"),
        ColSpec("ETY", "NULL", "C", notes="extension years"),
        ColSpec("MLY", "NULL", "C", notes="major-league years"),
        ColSpec("SECY","NULL", "C"),
        ColSpec("OPT", "NULL", "C", notes="option years remaining"),
        ColSpec("OY",  "NULL", "C"),
        ColSpec("ON40","NULL", "C", notes="on 40-man roster — needs roster_status decode"),
    ],
)


ALL_FILES = [
    BATTING_STATS_1, BATTING_STATS_2, PITCHING_STATS_1, FIELDING_STATS, BATTING_RATINGS,
    # Group A
    BATTING_POTENTIAL, PITCHING_RATINGS, PITCHING_POTENTIAL, FIELDING_RATINGS,
    INDIVIDUAL_PITCH_RATINGS, INDIVIDUAL_PITCH_POTENTIAL, POSITION_RATINGS,
    # Group B
    PITCHING_STATS_2,
    # Group C
    BATTING_SUPERSTATS_1, PITCHING_SUPERSTATS_1,
    # Group D
    BATTING_SUPERSTATS_2, PITCHING_SUPERSTATS_2,
    # Group E
    DEFAULT, POPULARITY_INFO, PERSONALITY_MORALE,
    # Group F
    FINANCIAL_INFO,
]


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


def _csv(path: Path) -> str:
    return f"'{path.as_posix()}'"


def _connect(save: SaveConfig, dump: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    csvs = {
        "career_bat":     "players_career_batting_stats.csv",
        "career_pit":     "players_career_pitching_stats.csv",
        "career_field":   "players_career_fielding_stats.csv",
        "scouted_ratings": "players_scouted_ratings.csv",
        "player_value":   "players_value.csv",
        "players":        "players.csv",
        "games":          "games.csv",
        "at_bats":        "players_at_bat_batting_stats.csv",
        "contracts":      "players_contract.csv",
        "roster_status":  "players_roster_status.csv",
        "teams":          "teams.csv",
        "leagues":        "leagues.csv",
        "nations":        "nations.csv",
        "parks":          "parks.csv",
        "league_history_batting_stats":  "league_history_batting_stats.csv",
        "league_history_pitching_stats": "league_history_pitching_stats.csv",
    }
    csv_dir = save.csv_dir(dump)
    for view, fname in csvs.items():
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(csv_dir / fname)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


def _is_match(ie_val, derived_val, tol: float) -> bool | None:
    """Return True/False, or None if either side is null/empty.

    IE files use a few presentation conventions we need to normalize before
    comparing:
      - "-"  : "no value" sentinel (treat as null)
      - "9.1%" : trailing percent suffix (strip)
      - "$28 800 000" : currency with thousands-space (strip $ and spaces)
      - "1 (auto.)" : auto-renewal annotation on contract years (strip suffix)
    """
    if ie_val is None or derived_val is None:
        return None
    s_ie = str(ie_val).strip()
    s_dv = str(derived_val).strip()
    if s_ie in ("-", "", "nan", "NaN"):
        return None
    # Try numeric compare with IE-side normalization
    try:
        ie_clean = (s_ie
                    .replace("(auto.)", "")
                    .replace(",", "")
                    .replace(" ", "")
                    .replace("$", "")
                    .rstrip("%")
                    .strip())
        ie_f = float(ie_clean) if ie_clean else float("nan")
        dv_f = float(derived_val)
    except (ValueError, TypeError):
        return s_ie == s_dv
    import math
    if math.isnan(ie_f) or math.isnan(dv_f):
        return None
    return abs(ie_f - dv_f) <= max(tol, 1e-9)


def reconcile_file(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    spec: FileSpec,
) -> dict:
    """Run reconciliation for a single import_export file. Returns scorecard dict."""
    ie_path = save.import_export_dir / spec.ie_filename
    if not ie_path.exists():
        console.print(f"[red]Missing import_export file: {ie_path}[/red]")
        return {"file": spec.short_name, "error": "missing"}

    # Build the derivation query (all aliases quoted to allow digits/special chars).
    # Qualify bare identifiers with d. to avoid case-insensitive collisions with ie."G" etc.
    derived_select_cols = ",\n            ".join(
        f'{_qualify_bare(col.derived_sql)} AS "{_safe_name(col.ie_name)}"'
        for col in spec.cols
    )
    ie_select_cols = ", ".join(
        f'ie."{c.ie_name}" AS "ie_{_safe_name(c.ie_name)}"' for c in spec.cols
    )
    sql = f"""
    WITH ie AS (
        SELECT * FROM read_csv_auto({_csv(ie_path)}, sample_size=-1, ignore_errors=true)
    ),
    {spec.derived_cte}
    SELECT
        ie.ID AS player_id,
        ie."Name" AS name,
        {ie_select_cols},
        {derived_select_cols}
    FROM ie
    LEFT JOIN derived d ON ie.ID = d.player_id
    """
    rows = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]

    # Per-column scoring
    col_scores: list[dict] = []
    for col in spec.cols:
        safe = _safe_name(col.ie_name)
        ie_idx = cols.index(f"ie_{safe}")
        dv_idx = cols.index(safe)
        matches = mismatches = nulls = 0
        sample_mismatches: list[tuple] = []
        for row in rows:
            ie_val = row[ie_idx]
            dv_val = row[dv_idx]
            verdict = _is_match(ie_val, dv_val, col.tolerance)
            if verdict is None:
                nulls += 1
            elif verdict:
                matches += 1
            else:
                mismatches += 1
                if len(sample_mismatches) < 3:
                    sample_mismatches.append((row[1], ie_val, dv_val))
        scored = matches + mismatches
        col_scores.append(
            {
                "col": col.ie_name,
                "tier": col.tier,
                "match": matches,
                "miss": mismatches,
                "null": nulls,
                "rate": f"{(100 * matches / scored):.0f}%" if scored else "n/a",
                "sample_mismatch": sample_mismatches,
                "notes": col.notes,
            }
        )

    return {
        "file": spec.short_name,
        "rows": len(rows),
        "col_scores": col_scores,
    }


def _qualify_bare(expr: str) -> str:
    """If `expr` is a bare identifier (or NULL), return it unchanged or with `d.` prefix.

    Anything containing parens / operators / commas is assumed to be already qualified
    by the ColSpec author. Used to avoid case-insensitive collisions in the SELECT.
    """
    s = expr.strip()
    if not s or s.upper() == "NULL":
        return s
    if any(ch in s for ch in "()+-*/ ,'\""):
        return s
    return f"d.{s}"


def _safe_name(name: str) -> str:
    """Make an import_export column name safe to use as a SQL identifier."""
    return (
        name.replace("/", "_")
        .replace("%", "pct")
        .replace("+", "plus")
        .replace("'", "")
        .replace("'s", "s")
        .replace(" ", "_")
        .replace("(", "")
        .replace(")", "")
        .lower()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────


TIER_DESC = {
    "A": "direct dump column",
    "B": "trivial calc",
    "C": "needs league constants",
    "D": "needs modeled stats",
    "E": "at-bat aggregation",
    "F": "cannot replicate",
    "G": "needs scale conversion",
}


def _fmt_scorecard_row(s: dict) -> str:
    samples = ""
    if s["sample_mismatch"]:
        samples = " ; ".join(
            f"`{n}`: ie={ie} vs derived={dv}"
            for (n, ie, dv) in s["sample_mismatch"][:2]
        )
    return f"| `{s['col']}` | {s['tier']} | {s['rate']} | {s['match']}/{s['miss']}/{s['null']} | {samples or s['notes']} |"


def write_report(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md = [
        "# OOTP Reconciliation Audit",
        "",
        "_Per-column comparison: `import_export` Red Sox roster files vs derivations from monthly dump CSVs._",
        "",
        "## Tiers",
        "",
        "| Tier | Meaning |",
        "| --- | --- |",
        *[f"| **{t}** | {d} |" for t, d in TIER_DESC.items()],
        "",
        "## Summary scorecard",
        "",
        "| File | rows | A | B | C | D | E | F | G | total cols |",
        "| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in results:
        if "error" in r:
            md.append(f"| `{r['file']}` | — | — | — | — | — | — | — | — | error: {r['error']} |")
            continue
        tier_counts = {t: 0 for t in TIER_DESC}
        for s in r["col_scores"]:
            tier_counts[s["tier"]] += 1
        md.append(
            f"| `{r['file']}` | {r['rows']} | "
            + " | ".join(str(tier_counts[t]) for t in "ABCDEFG")
            + f" | {len(r['col_scores'])} |"
        )
    md.append("")

    md.append("## Per-file detail")
    md.append("")
    for r in results:
        if "error" in r:
            continue
        md.append(f"### `{r['file']}`  ({r['rows']} players)")
        md.append("")
        md.append("| col | tier | match% | match/miss/null | sample mismatch / notes |")
        md.append("| --- | --- | --: | --: | --- |")
        for s in r["col_scores"]:
            md.append(_fmt_scorecard_row(s))
        md.append("")
    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Report written:[/green] {output_path}")


def _print_console_summary(results: list[dict]) -> None:
    t = Table(title="Reconciliation summary", show_lines=False)
    t.add_column("file")
    t.add_column("rows", justify="right")
    for tier in "ABCDEFG":
        t.add_column(tier, justify="right")
    t.add_column("total", justify="right")
    for r in results:
        if "error" in r:
            t.add_row(r["file"], "—", "—", "—", "—", "—", "—", "—", "—", r["error"])
            continue
        counts = {x: 0 for x in "ABCDEFG"}
        for s in r["col_scores"]:
            counts[s["tier"]] += 1
        t.add_row(
            r["file"],
            str(r["rows"]),
            *[str(counts[x]) for x in "ABCDEFG"],
            str(len(r["col_scores"])),
        )
    console.print(t)


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    dump: str | None = None,
    output_path: Path | None = None,
) -> Path:
    dump = dump or save.latest_dump_name()
    output_path = output_path or Path("audit_output") / "reconciliation_report.md"
    console.rule(f"[bold cyan]Reconciliation audit — {save.save_name} / {dump}")

    con = _connect(save, dump)
    results = []
    for spec in ALL_FILES:
        console.print(f"  - {spec.short_name}")
        results.append(reconcile_file(con, save, spec))

    console.print()
    _print_console_summary(results)
    write_report(results, output_path)
    return output_path


if __name__ == "__main__":
    run()
