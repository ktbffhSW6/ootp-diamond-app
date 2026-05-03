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
        SUM(war) AS war
    FROM career_bat
    WHERE year = 2029 AND split_id = 1
    GROUP BY player_id
),
derived AS (
    SELECT
        a.player_id,
        a.g, a.gs, a.pa, a.ab, a.h, a.k, a.bb, a.ibb, a.hp,
        a.d, a.t, a.hr, a.r, a.rbi, a.sb, a.cs, a.gdp, a.sh, a.sf, a.ci,
        a.pitches_seen, a.wpa, a.war,
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
        ROUND(1.0 * a.pitches_seen / NULLIF(a.pa, 0), 2) AS pi_per_pa
    FROM agg a
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
        # OPS = OBP + SLG, but presented as a 3-decimal — just sum
        ColSpec("OPS", "ROUND(d.obp + d.slg, 3)", "B", tolerance=RATE_TOLERANCE),
        # OPS+ needs league constants — TODO C tier
        ColSpec("OPS+", "NULL", "C", notes="needs league constants (avg-of-OPS, park factor)"),
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
        ColSpec("RC",  "NULL",     "C", notes="Bill James RC formula — needs league context"),
        ColSpec("RC/27", "NULL",   "C", notes="needs RC + outs"),
        ColSpec("ISO", "iso",      "B", tolerance=RATE_TOLERANCE),
        ColSpec("wOBA", "NULL",    "C", notes="needs league linear weights"),
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
        SUM(g) AS g, SUM(gs) AS gs, SUM(w) AS w, SUM(l) AS l, SUM(s) AS sv, SUM(hld) AS hld,
        SUM(outs) AS outs,
        SUM(ha) AS ha, SUM(hra) AS hra, SUM(r) AS r, SUM(er) AS er,
        SUM(bb) AS bb, SUM(k) AS k, SUM(hp) AS hp, SUM(bf) AS bf,
        SUM(ab) AS ab, SUM(tb) AS tb, SUM(gb) AS gb, SUM(fb) AS fb, SUM(pi) AS pitches_thrown,
        SUM(dp) AS dp, SUM(qs) AS qs, SUM(svo) AS svo, SUM(bs) AS bs, SUM(ra) AS ra,
        SUM(cg) AS cg, SUM(sho) AS sho,
        SUM(sb) AS sb_against, SUM(cs) AS cs_against, SUM(iw) AS iw, SUM(wp) AS wp, SUM(bk) AS bk,
        SUM(ir) AS ir, SUM(irs) AS irs, SUM(wpa) AS wpa, SUM(li) AS li,
        SUM(sd) AS sd, SUM(md) AS md, SUM(war) AS war, SUM(ra9war) AS ra9war,
        SUM(sf) AS sf
    FROM career_pit
    WHERE year = 2029 AND split_id = 1
    GROUP BY player_id
),
derived AS (
    SELECT
        a.player_id,
        a.g, a.gs, a.w, a.l, a.sv, a.hld, a.outs,
        a.ha, a.hra, a.r, a.er, a.bb, a.k, a.hp, a.bf, a.ab, a.tb,
        a.gb, a.fb, a.pitches_thrown, a.dp, a.qs, a.svo, a.bs, a.ra, a.cg, a.sho,
        a.sb_against, a.cs_against, a.iw, a.wp, a.bk, a.ir, a.irs, a.wpa, a.li,
        a.sd, a.md, a.war, a.ra9war,
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
        ROUND(1.0 * a.sv / NULLIF(a.svo, 0), 3) AS sv_pct,
        ROUND(1.0 * a.qs / NULLIF(a.gs, 0), 3) AS qs_pct,
        ROUND(100.0 * a.gb / NULLIF(a.gb + a.fb, 0), 1) AS go_pct,
        ROUND(1.0 * a.pitches_thrown / NULLIF(a.g, 0), 1) AS ppg
    FROM agg a
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
        ColSpec("HR/9",  "hr9",   "B", tolerance=0.05),
        ColSpec("BB/9",  "bb9",   "B", tolerance=0.05),
        ColSpec("K/9",   "k9",    "B", tolerance=0.05),
        ColSpec("K/BB",  "k_per_bb", "B", tolerance=0.05),
        ColSpec("ERA+",  "NULL",  "C", notes="needs league ERA + park factor"),
        ColSpec("FIP",   "NULL",  "C", notes="needs league FIP constant"),
        ColSpec("WAR",   "ROUND(d.war, 1)", "A", tolerance=0.1,
                notes="career_pit.war (BIP-WAR)"),
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
        -- DEF in import_export = highest fielding pos rating? Or running_baserunning? TBD
        GREATEST(
            COALESCE(sr.fielding_rating_pos2, 0),
            COALESCE(sr.fielding_rating_pos3, 0),
            COALESCE(sr.fielding_rating_pos4, 0),
            COALESCE(sr.fielding_rating_pos5, 0),
            COALESCE(sr.fielding_rating_pos6, 0),
            COALESCE(sr.fielding_rating_pos7, 0),
            COALESCE(sr.fielding_rating_pos8, 0),
            COALESCE(sr.fielding_rating_pos9, 0)
        ) AS def
    FROM scouted_ratings sr
    WHERE sr.scouting_team_id = 4    -- Red Sox view
      AND sr.league_id = 203
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
        ColSpec("DEF",     "def",        "G", tolerance=RATING_TOLERANCE,
                notes="best of fielding_rating_pos2..9 — formula TBD"),
    ],
)


ALL_FILES = [BATTING_STATS_1, BATTING_STATS_2, PITCHING_STATS_1, FIELDING_STATS, BATTING_RATINGS]


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
    }
    csv_dir = save.csv_dir(dump)
    for view, fname in csvs.items():
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(csv_dir / fname)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


def _is_match(ie_val, derived_val, tol: float) -> bool | None:
    """Return True/False, or None if either side is null/empty."""
    if ie_val is None or derived_val is None:
        return None
    # Strings that look numeric: try numeric compare
    try:
        ie_f = float(str(ie_val).replace(",", "").strip() or "nan")
        dv_f = float(derived_val)
    except (ValueError, TypeError):
        return str(ie_val).strip() == str(derived_val).strip()
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
