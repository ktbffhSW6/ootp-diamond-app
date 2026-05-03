"""Decode the four pending OOTP integer codebooks via empirical analysis.

  - players_awards.award_id              (13 distinct values)
  - players_league_leader.category       (60 distinct values)
  - players_streak.streak_id             (21 distinct values)
  - players_injury_history.body_part     (integer)

Strategies:
  - award_id: cross-reference winners with `league_history.best_*_id` fields
              (best_hitter=MVP, best_pitcher=CY, best_rookie=RoY, best_fielder=GG),
              date-of-award patterns (d=1 monthly, d=14/m=7 = ASG, d=11/m=11 = CY),
              winner counts (1=monthly so 6/league/year, 7=positional so 9/league/year),
              and single-position pos field (Gold Glove + Silver Slugger).
  - leaders.category: for each category, find the place=1 leader for each year +
              sub_league. Look up that player's career stats. Whichever stat
              column equals the reported amount = the category's meaning.
  - streak_id: profile each streak by (a) % of holders who are pitchers vs hitters,
              (b) max value, (c) average length. Cross-reference with known
              streak patterns (hit ~30+, K ~10-15, etc).
  - body_part: frequency + length distribution.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from rich.console import Console

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────


def _csv(p: Path) -> str:
    return f"'{p.as_posix()}'"


def _connect(save: SaveConfig, dump: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    csvs = {
        "awards":       "players_awards.csv",
        "leaders":      "players_league_leader.csv",
        "streaks":      "players_streak.csv",
        "injuries":     "players_injury_history.csv",
        "league_history": "league_history.csv",
        "league_history_all_star": "league_history_all_star.csv",
        "career_bat":   "players_career_batting_stats.csv",
        "career_pit":   "players_career_pitching_stats.csv",
        "career_field": "players_career_fielding_stats.csv",
        "players":      "players.csv",
    }
    csv_dir = save.csv_dir(dump)
    for view, fname in csvs.items():
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(csv_dir / fname)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


def _rows(rel) -> list[dict]:
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _md_table(rows: list[dict], max_rows: int = 60) -> str:
    if not rows:
        return "_(no rows)_\n"
    rows = rows[:max_rows]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(v) if v is not None else "—" for v in row.values()) + " |")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Codebook 1: award_id
# ─────────────────────────────────────────────────────────────────────────────


def decode_award_id(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Profile each award_id's winners + cross-reference league_history.

    Profile signals:
      - winners_per_year_per_league (frequency)
      - distinct_dates (1 = annual, 6 = monthly, 26 = weekly)
      - day-month patterns
      - has_pos_field (positional awards have pos=1-9 like Gold Glove)
      - hitter_pct vs pitcher_pct of winners
      - matches_best_hitter / best_pitcher / best_rookie of league_history
    """
    return _rows(con.execute("""
        WITH base AS (
            SELECT a.award_id, a.year, a.sub_league_id, a.day, a.month, a.position,
                   a.player_id, p.position AS player_position
            FROM awards a JOIN players p ON a.player_id = p.player_id
            WHERE a.league_id = 203
        ),
        per_award AS (
            SELECT
                award_id,
                COUNT(*) AS total_rows,
                COUNT(DISTINCT year) AS years_with,
                ROUND(1.0 * COUNT(*) / COUNT(DISTINCT year) / 2, 1) AS avg_per_year_per_league,
                COUNT(DISTINCT day || '-' || month) AS distinct_dates,
                MIN(day || '/' || month) AS sample_date,
                MAX(day || '/' || month) AS sample_date_2,
                COUNT(DISTINCT position) AS distinct_pos_values,
                MAX(position) AS max_pos,
                ROUND(100.0 * COUNT(*) FILTER (WHERE player_position = 1) / NULLIF(COUNT(*), 0), 0)
                                                                  AS pct_pitchers,
                ROUND(100.0 * COUNT(*) FILTER (WHERE player_position > 1) / NULLIF(COUNT(*), 0), 0)
                                                                  AS pct_hitters,
                COUNT(DISTINCT sub_league_id) AS sub_leagues_with_award
            FROM base
            GROUP BY award_id
        ),
        cross_ref AS (
            SELECT
                lh.year, lh.sub_league_id,
                lh.best_hitter_id, lh.best_pitcher_id, lh.best_rookie_id, lh.best_manager_id
            FROM league_history lh WHERE league_id = 203
        ),
        match_cnts AS (
            SELECT
                a.award_id,
                COUNT(*) FILTER (WHERE a.player_id = cr.best_hitter_id)  AS matches_best_hitter,
                COUNT(*) FILTER (WHERE a.player_id = cr.best_pitcher_id) AS matches_best_pitcher,
                COUNT(*) FILTER (WHERE a.player_id = cr.best_rookie_id)  AS matches_best_rookie
            FROM awards a
            LEFT JOIN cross_ref cr
                   ON a.year = cr.year AND a.sub_league_id = cr.sub_league_id
            WHERE a.league_id = 203
            GROUP BY a.award_id
        )
        SELECT
            p.award_id,
            p.total_rows, p.years_with, p.avg_per_year_per_league,
            p.distinct_dates, p.sample_date, p.distinct_pos_values, p.max_pos,
            p.pct_pitchers, p.pct_hitters, p.sub_leagues_with_award,
            m.matches_best_hitter, m.matches_best_pitcher, m.matches_best_rookie
        FROM per_award p
        LEFT JOIN match_cnts m USING (award_id)
        ORDER BY p.award_id
    """))


# Hand-curated mapping based on the empirical profile + the clear patterns we
# decoded by inspection in the audit chat. Verified against league_history.
AWARD_ID_DECODED = {
    0:  "PLAYER_OF_THE_WEEK",
    1:  "PITCHER_OF_THE_MONTH",
    2:  "HITTER_OF_THE_MONTH",
    3:  "ROOKIE_OF_THE_MONTH",
    4:  "CY_YOUNG",                # top-3 voted
    5:  "MVP",                     # top-3 voted
    6:  "ROOKIE_OF_THE_YEAR",      # top-3 voted
    7:  "GOLD_GLOVE",              # one per position (pos field 1=P..9=RF)
    9:  "ALL_STAR",                # ASG roster (~30-40/league/year)
    11: "SILVER_SLUGGER",          # one per position pos=2..10 (10=DH)
    13: "RELIEVER_OF_THE_YEAR",    # top-3 voted
    14: "WS_CHAMPION_ROSTER",      # only winning league's sub_league_id
    15: "POSTSEASON_SERIES_MVP",   # WC/DS/CS/WS MVP per series
}


# ─────────────────────────────────────────────────────────────────────────────
# Codebook 2: leaders.category
# ─────────────────────────────────────────────────────────────────────────────


def decode_leader_category(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Empirically match each `category` to a known stat by aligning the
    place=1 leader's `amount` with their stat-line for that year."""
    # Gather all (category, year, sub_league_id, leader_player_id, amount) for place=1
    leaders = con.execute("""
        SELECT category, year, sub_league_id, player_id, amount
        FROM leaders
        WHERE league_id = 203 AND place = 1
        ORDER BY category, year, sub_league_id
    """).fetchall()
    # Group by category
    by_cat: dict[int, list[tuple]] = defaultdict(list)
    for cat, year, sl, pid, amt in leaders:
        by_cat[cat].append((year, sl, pid, amt))

    # Build a per-(player,year) stat map for batting and pitching (split_id=1)
    bat_stats = {}
    for r in con.execute("""
        SELECT player_id, year, SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
               SUM(d) AS d2b, SUM(t) AS t3b, SUM(hr) AS hr, SUM(r) AS r,
               SUM(rbi) AS rbi, SUM(sb) AS sb, SUM(cs) AS cs, SUM(bb) AS bb,
               SUM(ibb) AS ibb, SUM(hp) AS hp, SUM(k) AS k, SUM(sh) AS sh,
               SUM(sf) AS sf, SUM(gdp) AS gdp, SUM(g) AS g,
               SUM(pitches_seen) AS pitches_seen, SUM(wpa) AS wpa, SUM(war) AS war
        FROM career_bat
        WHERE league_id = 203 AND split_id = 1
        GROUP BY player_id, year
    """).fetchall():
        pid, yr = r[0], r[1]
        d = dict(zip(["player_id","year","PA","AB","H","2B","3B","HR","R","RBI","SB","CS","BB","IBB","HBP","K","SH","SF","GDP","G","pitches_seen","WPA","WAR"], r))
        # Derived rate stats
        if d["AB"]:
            d["AVG"] = round(d["H"] / d["AB"], 4)
            d["SLG"] = round((d["H"] + d["2B"] + 2 * d["3B"] + 3 * d["HR"]) / d["AB"], 4)
        if d["AB"] + d["BB"] + d["HBP"] + d["SF"]:
            d["OBP"] = round((d["H"] + d["BB"] + d["HBP"]) / (d["AB"] + d["BB"] + d["HBP"] + d["SF"]), 4)
        if "OBP" in d and "SLG" in d:
            d["OPS"] = round(d["OBP"] + d["SLG"], 4)
        if d["AB"]:
            d["TB"] = (d["H"] - d["2B"] - d["3B"] - d["HR"]) + 2 * d["2B"] + 3 * d["3B"] + 4 * d["HR"]
            d["XBH"] = d["2B"] + d["3B"] + d["HR"]
            d["ISO"] = round(d.get("SLG", 0) - d.get("AVG", 0), 4)
        if d["AB"] - d["K"] - d["HR"] + d["SF"]:
            d["BABIP"] = round((d["H"] - d["HR"]) / (d["AB"] - d["K"] - d["HR"] + d["SF"]), 4)
        bat_stats[(pid, yr)] = d

    pit_stats = {}
    for r in con.execute("""
        SELECT player_id, year, SUM(outs) AS outs, SUM(g) AS g, SUM(gs) AS gs,
               SUM(w) AS w, SUM(l) AS l, SUM(s) AS sv, SUM(hld) AS hld,
               SUM(ha) AS ha, SUM(hra) AS hra, SUM(r) AS r, SUM(er) AS er,
               SUM(bb) AS bb, SUM(k) AS k, SUM(hp) AS hp, SUM(bf) AS bf,
               SUM(qs) AS qs, SUM(cg) AS cg, SUM(sho) AS sho,
               SUM(svo) AS svo, SUM(bs) AS bs,
               SUM(wp) AS wp, SUM(bk) AS bk, SUM(iw) AS iw,
               SUM(ab) AS pit_ab,
               SUM(war) AS war, SUM(ra9war) AS ra9war
        FROM career_pit
        WHERE league_id = 203 AND split_id = 1
        GROUP BY player_id, year
    """).fetchall():
        pid, yr = r[0], r[1]
        d = dict(zip(["player_id","year","outs","Pit_G","Pit_GS","W","L","SV","HLD",
                      "HA","HRA","Pit_R","ER","Pit_BB","Pit_K","Pit_HP","BF","QS","CG","SHO",
                      "SVO","BS","WP","BK","IBBgiven","Pit_AB","Pit_WAR","Pit_RA9WAR"], r))
        if d["outs"]:
            ip = d["outs"] / 3.0
            d["IP"] = round(ip, 1)
            d["ERA"] = round(9.0 * d["ER"] / ip, 2)
            d["WHIP"] = round((d["HA"] + d["Pit_BB"]) / ip, 2)
            d["K9"] = round(9.0 * d["Pit_K"] / ip, 2)
            d["BB9"] = round(9.0 * d["Pit_BB"] / ip, 2)
            d["HR9"] = round(9.0 * d["HRA"] / ip, 2)
            if d["Pit_AB"]:
                d["Opp_AVG"] = round(d["HA"] / d["Pit_AB"], 4)
        if d["Pit_BB"]:
            d["K_BB"] = round(d["Pit_K"] / d["Pit_BB"], 2)
        pit_stats[(pid, yr)] = d

    # For each category, find which stat the leader's amount matches across years
    out: list[dict] = []
    for cat in sorted(by_cat):
        leader_recs = by_cat[cat]
        match_counter: Counter[str] = Counter()
        sample_leader, sample_amount, sample_year, sample_match = None, None, None, None
        for year, sl, pid, amt in leader_recs:
            stats = {**bat_stats.get((pid, year), {}), **pit_stats.get((pid, year), {})}
            for stat, val in stats.items():
                if stat in ("player_id", "year", "outs", "Pit_AB"):
                    continue
                if val is None:
                    continue
                try:
                    if abs(float(val) - float(amt)) < 0.001:
                        match_counter[stat] += 1
                        if sample_match is None:
                            sample_leader, sample_amount, sample_year, sample_match = pid, amt, year, stat
                except (TypeError, ValueError):
                    continue
        best_match, best_count = (match_counter.most_common(1) + [(None, 0)])[0]
        out.append({
            "category": cat,
            "n_leaders": len(leader_recs),
            "best_match_stat": best_match,
            "match_count": best_count,
            "match_pct": round(100.0 * best_count / max(len(leader_recs), 1), 0),
            "sample_amount": sample_amount,
            "sample_year": sample_year,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Codebook 3: streak_id
# ─────────────────────────────────────────────────────────────────────────────


def decode_streak_id(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Profile each streak by holder population + max value + active rate."""
    return _rows(con.execute("""
        WITH base AS (
            SELECT s.streak_id, s.value, s.has_ended, p.position AS pos
            FROM streaks s JOIN players p ON s.player_id = p.player_id
            WHERE s.league_id = 203
        )
        SELECT
            streak_id,
            COUNT(*)                                                AS instances,
            COUNT(*) FILTER (WHERE NOT has_ended)                   AS active,
            COUNT(*) FILTER (WHERE has_ended)                       AS ended,
            MAX(value)                                              AS max_value,
            ROUND(AVG(value), 1)                                    AS avg_value,
            ROUND(100.0 * COUNT(*) FILTER (WHERE pos = 1) / COUNT(*), 0) AS pct_pitchers,
            ROUND(100.0 * COUNT(*) FILTER (WHERE pos > 1) / COUNT(*), 0) AS pct_hitters
        FROM base
        GROUP BY streak_id
        ORDER BY streak_id
    """))


# ─────────────────────────────────────────────────────────────────────────────
# Codebook 4: body_part
# ─────────────────────────────────────────────────────────────────────────────


def decode_body_part(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Profile each body_part by frequency + length distribution + day-to-day rate."""
    return _rows(con.execute("""
        SELECT
            body_part,
            COUNT(*)                                                AS injuries,
            COUNT(DISTINCT player_id)                               AS distinct_players,
            ROUND(AVG(length), 1)                                   AS avg_length_days,
            MAX(length)                                             AS max_length,
            ROUND(100.0 * SUM(CASE WHEN day_to_day THEN 1 ELSE 0 END) / COUNT(*), 0)
                                                                    AS pct_day_to_day,
            ROUND(AVG(setbacks), 2)                                 AS avg_setbacks
        FROM injuries
        GROUP BY body_part
        ORDER BY injuries DESC
    """))


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    dump: str | None = None,
    output_path: Path | None = None,
) -> Path:
    dump = dump or save.latest_dump_name()
    output_path = output_path or Path("audit_output") / "codes_decoder_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold cyan]Codebook decoding — {save.save_name} / {dump}")
    con = _connect(save, dump)

    console.print("  - decoding award_id...")
    aw = decode_award_id(con)
    for row in aw:
        row["decoded"] = AWARD_ID_DECODED.get(row["award_id"], "UNKNOWN")

    console.print("  - decoding leaders.category (60 categories × 4 years × 2 leagues)...")
    cat = decode_leader_category(con)

    console.print("  - decoding streak_id...")
    sk = decode_streak_id(con)

    console.print("  - decoding body_part...")
    bp = decode_body_part(con)

    md = [
        "# OOTP Pending Codebooks Decoder Report",
        "",
        f"- **Save**: `{save.save_name}`",
        f"- **Dump**: `{dump}`",
        f"- **Scope**: MLB (`league_id = 203`)",
        "",
        "## 1. `players_awards.award_id`",
        "",
        "Profile + cross-reference with `league_history.best_*_id`. Decoded names "
        "in the rightmost column verified against winner counts, dates, position "
        "field, and player-type distribution.",
        "",
        _md_table(aw),
        "",
        "## 2. `players_league_leader.category`",
        "",
        "For each category, the place=1 leader's `amount` was matched against every "
        "stat column in `career_bat` / `career_pit` for that player-year. The most-common "
        "matching stat across leader-years is reported as `best_match_stat`.",
        "",
        "Categories with `match_pct = 100` (or close) are confidently decoded. Any with "
        "low match rate need manual investigation (likely a derived stat we don't compute).",
        "",
        _md_table(cat),
        "",
        "## 3. `players_streak.streak_id`",
        "",
        "Profile by holder type (pitcher % vs hitter %), max value, average length, "
        "and active-vs-ended distribution. Pitcher-dominated streaks with low max → "
        "win/loss streaks. Hitter-dominated with high max → hitting / on-base streaks.",
        "",
        _md_table(sk),
        "",
        "## 4. `players_injury_history.body_part`",
        "",
        "Frequency + average length + day-to-day rate. Common body parts (arm, back, "
        "leg, shoulder) will dominate the count; severe injuries (UCL tear) have "
        "high `avg_length_days` and low `pct_day_to_day`.",
        "",
        _md_table(bp),
        "",
    ]

    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Report written:[/green] {output_path}")
    return output_path


if __name__ == "__main__":
    run()
