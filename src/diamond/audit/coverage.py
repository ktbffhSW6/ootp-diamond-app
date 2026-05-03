"""Feature-coverage audit for the OOTP monthly dumps.

For each user-facing feature the warehouse needs to support, this module:
  1. Identifies the dump CSV(s) that carry the data
  2. Profiles the table (rows, distinct entities, year coverage, etc.)
  3. Samples a few records to verify structure
  4. Notes any quirks or gaps

Output: audit_output/coverage_report.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
from rich.console import Console

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _csv(p: Path) -> str:
    return f"'{p.as_posix()}'"


def _connect(save: SaveConfig, dump: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    csvs = {
        # Core entities
        "players":          "players.csv",
        "teams":            "teams.csv",
        "leagues":          "leagues.csv",
        "divisions":        "divisions.csv",
        "sub_leagues":      "sub_leagues.csv",
        "games":            "games.csv",
        # Stats
        "career_bat":       "players_career_batting_stats.csv",
        "career_pit":       "players_career_pitching_stats.csv",
        "career_field":     "players_career_fielding_stats.csv",
        # Movement / trades
        "trade_history":    "trade_history.csv",
        "team_roster":      "team_roster.csv",
        "roster_status":    "players_roster_status.csv",
        # League / team standings + history
        "team_record":      "team_record.csv",
        "team_history_record": "team_history_record.csv",
        "team_history":     "team_history.csv",
        "league_history":   "league_history.csv",
        "league_history_all_star": "league_history_all_star.csv",
        # Playoffs
        "playoffs":         "league_playoffs.csv",
        "playoff_fixtures": "league_playoff_fixtures.csv",
        # Awards / HOF
        "awards":           "players_awards.csv",
        "league_leaders":   "players_league_leader.csv",
        # Streaks / injuries
        "streaks":          "players_streak.csv",
        "injuries":         "players_injury_history.csv",
        # Manager
        "human_managers":   "human_managers.csv",
    }
    csv_dir = save.csv_dir(dump)
    for view, fname in csvs.items():
        path = csv_dir / fname
        if not path.exists():
            continue
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(path)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


def _rows(rel) -> list[dict]:
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _md_table(rows: list[dict], max_rows: int = 10) -> str:
    if not rows:
        return "_(no rows)_\n"
    rows = rows[:max_rows]
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(v) if v is not None else "—" for v in row.values()) + " |")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Feature probes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FeatureReport:
    feature: str
    sources: list[str]
    profile: list[dict]
    samples: list[dict]
    notes: list[str]


def probe_standings(con) -> FeatureReport:
    """Standings — current + historical."""
    profile = _rows(con.execute("""
        SELECT
            (SELECT COUNT(*) FROM team_record)                       AS current_rows,
            (SELECT COUNT(*) FROM team_history_record)               AS history_rows,
            (SELECT COUNT(DISTINCT year) FROM team_history_record)   AS distinct_years,
            (SELECT MIN(year) FROM team_history_record)              AS first_year,
            (SELECT MAX(year) FROM team_history_record)              AS last_year
    """))
    # 2029 MLB standings — show a clean view
    samples = _rows(con.execute("""
        SELECT t.name, t.abbr, sl.name AS league, d.name AS division,
               r.g, r.w, r.l, r.pct, r.gb, r.streak
        FROM team_history_record r
        JOIN teams       t  ON r.team_id = t.team_id
        JOIN sub_leagues sl ON r.league_id = sl.league_id AND r.sub_league_id = sl.sub_league_id
        JOIN divisions   d  ON r.league_id = d.league_id AND r.sub_league_id = d.sub_league_id
                           AND r.division_id = d.division_id
        WHERE r.year = 2029 AND r.league_id = 203
        ORDER BY sl.sub_league_id, d.division_id, r.pct DESC
    """))
    notes = []
    if any(s["pct"] is None for s in samples):
        notes.append("some rows have NULL pct — non-MLB or playoff anomaly")
    return FeatureReport("standings", ["team_record", "team_history_record"], profile, samples, notes)


def probe_playoffs(con) -> FeatureReport:
    """Playoffs — bracket + fixture-level results."""
    profile = _rows(con.execute("""
        SELECT
            (SELECT COUNT(*) FROM playoffs)         AS playoff_meta_rows,
            (SELECT COUNT(*) FROM playoff_fixtures) AS fixture_rows,
            (SELECT COUNT(DISTINCT league_id) FROM playoff_fixtures) AS leagues_with_postseason,
            (SELECT COUNT(DISTINCT round) FROM playoff_fixtures WHERE league_id = 203) AS mlb_rounds
    """))
    # 2029 MLB postseason fixtures
    samples = _rows(con.execute("""
        SELECT pf.round,
               t0.abbr AS team0, t1.abbr AS team1,
               pf.result0, pf.result1,
               CASE WHEN pf.winner = pf.team_id0 THEN t0.abbr
                    WHEN pf.winner = pf.team_id1 THEN t1.abbr ELSE '?' END AS winner,
               pf.best_of, pf.played, pf.finished
        FROM playoff_fixtures pf
        LEFT JOIN teams t0 ON pf.team_id0 = t0.team_id
        LEFT JOIN teams t1 ON pf.team_id1 = t1.team_id
        WHERE pf.league_id = 203
        ORDER BY pf.round, pf.team_id0
    """))
    return FeatureReport(
        "playoffs", ["league_playoffs", "league_playoff_fixtures"], profile, samples, []
    )


def probe_awards(con) -> FeatureReport:
    """Awards — MVP, CY, RoY, GG, AS, etc."""
    profile = _rows(con.execute("""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT player_id) AS distinct_players,
            COUNT(DISTINCT award_id)  AS distinct_awards,
            COUNT(DISTINCT year)      AS years_covered,
            MIN(year)                 AS first_year,
            MAX(year)                 AS last_year
        FROM awards WHERE league_id = 203
    """))
    # award_id catalog with example winner
    samples = _rows(con.execute("""
        SELECT award_id,
               COUNT(*) AS times_given,
               MAX(year) AS last_year_given,
               (SELECT p.first_name || ' ' || p.last_name
                  FROM awards aa JOIN players p ON aa.player_id = p.player_id
                 WHERE aa.award_id = a.award_id AND aa.league_id = 203
                   AND aa.year = (SELECT MAX(year) FROM awards WHERE award_id = a.award_id AND league_id = 203)
                 LIMIT 1) AS most_recent_winner
        FROM awards a WHERE league_id = 203
        GROUP BY award_id
        ORDER BY award_id
    """))
    notes = ["award_id is an integer code — needs decoding (likely: MVP, CY, RoY, GG_pos1..9, SS, RoY)"]
    return FeatureReport("awards", ["players_awards"], profile, samples, notes)


def probe_league_leaders(con) -> FeatureReport:
    """League leaders — top N per stat per league-year."""
    profile = _rows(con.execute("""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT category) AS distinct_categories,
            COUNT(DISTINCT year)     AS years_covered,
            MIN(year) AS first_year, MAX(year) AS last_year
        FROM league_leaders WHERE league_id = 203
    """))
    # Categories
    samples = _rows(con.execute("""
        SELECT category,
               COUNT(*) AS rows,
               (SELECT p.first_name || ' ' || p.last_name
                  FROM league_leaders l JOIN players p ON l.player_id = p.player_id
                 WHERE l.category = ll.category AND l.league_id = 203 AND l.year = 2029 AND l.place = 1
                 LIMIT 1) AS leader_2029,
               MAX(CASE WHEN year = 2029 AND place = 1 THEN amount END) AS leader_2029_amount
        FROM league_leaders ll WHERE league_id = 203
        GROUP BY category
        ORDER BY category
    """))
    notes = ["category is an integer code (HR=?, AVG=?, K=?, ERA=?...) — needs decoding"]
    return FeatureReport("leaders", ["players_league_leader"], profile, samples, notes)


def probe_streaks(con) -> FeatureReport:
    """Streaks — hitting, on-base, win, etc."""
    profile = _rows(con.execute("""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT player_id) AS distinct_players,
            COUNT(DISTINCT streak_id) AS distinct_streak_types,
            SUM(CASE WHEN has_ended THEN 1 ELSE 0 END) AS ended_streaks,
            SUM(CASE WHEN NOT has_ended THEN 1 ELSE 0 END) AS active_streaks
        FROM streaks WHERE league_id = 203
    """))
    samples = _rows(con.execute("""
        SELECT streak_id,
               COUNT(*) AS instances,
               MAX(value) AS max_value,
               ROUND(AVG(value), 1) AS avg_value
        FROM streaks WHERE league_id = 203
        GROUP BY streak_id ORDER BY streak_id
    """))
    notes = ["streak_id is an integer — types likely: HIT, OB, HR_in_consecutive, K, etc."]
    return FeatureReport("streaks", ["players_streak"], profile, samples, notes)


def probe_hall_of_fame(con) -> FeatureReport:
    """Hall of Fame status — direct boolean on players + induction tracking."""
    profile = _rows(con.execute("""
        SELECT
            SUM(CASE WHEN hall_of_fame THEN 1 ELSE 0 END)              AS hof_players,
            SUM(CASE WHEN inducted THEN 1 ELSE 0 END)                  AS inducted_players,
            SUM(CASE WHEN hall_of_fame AND retired THEN 1 ELSE 0 END)  AS hof_retired
        FROM players
    """))
    samples = _rows(con.execute("""
        SELECT first_name || ' ' || last_name AS name, age, retired, hall_of_fame, inducted
        FROM players
        WHERE hall_of_fame OR inducted
        LIMIT 10
    """))
    notes = ["players.csv has hall_of_fame + inducted booleans only — induction year/details "
             "must come from players_awards (HOF award_id) — to confirm in awards probe"]
    return FeatureReport("hall_of_fame", ["players", "players_awards"], profile, samples, notes)


def probe_movements(con) -> FeatureReport:
    """Player movements — single-dump view (full timeline needs cross-month diffs)."""
    profile = _rows(con.execute("""
        SELECT
            (SELECT COUNT(*) FROM trade_history) AS total_trades,
            (SELECT COUNT(*) FROM trade_history WHERE EXTRACT(YEAR FROM date) = 2029) AS trades_2029,
            (SELECT COUNT(DISTINCT player_id) FROM career_bat
              WHERE year = 2029 AND split_id = 1) AS distinct_players_with_2029_bat,
            (SELECT COUNT(*) FROM (
                SELECT player_id, year FROM career_bat
                WHERE year = 2029 AND split_id = 1
                GROUP BY player_id, year HAVING COUNT(DISTINCT team_id) > 1
            )) AS players_who_changed_teams_within_2029_via_career_bat
    """))
    # Sample 2029 trades with player names
    samples = _rows(con.execute("""
        SELECT date, summary,
               t0.abbr AS team0, t1.abbr AS team1
        FROM trade_history th
        LEFT JOIN teams t0 ON th.team_id_0 = t0.team_id
        LEFT JOIN teams t1 ON th.team_id_1 = t1.team_id
        WHERE EXTRACT(YEAR FROM th.date) = 2029
        ORDER BY th.date DESC
        LIMIT 8
    """))
    notes = [
        "trade_history is append-only and full-detail (up to 10 players + draft picks + cash + iafa per side)",
        "intra-org movements (call-up/demote) are NOT in trade_history — they're inferred from monthly snapshots of players.team_id and team_roster",
        "career_*.stint column captures multi-team within a season",
    ]
    return FeatureReport("movements", ["trade_history", "players (snapshots)", "career_bat.stint"], profile, samples, notes)


def probe_records(con) -> FeatureReport:
    """Records — derived. Show top single-season HR and career HR (in-save) as a sanity check."""
    profile = _rows(con.execute("""
        SELECT
            (SELECT COUNT(DISTINCT player_id) FROM career_bat WHERE league_id = 203) AS distinct_players_in_mlb_career_bat,
            (SELECT COUNT(DISTINCT year)      FROM career_bat WHERE league_id = 203) AS years_of_data,
            (SELECT MIN(year) FROM career_bat WHERE league_id = 203) AS first_year,
            (SELECT MAX(year) FROM career_bat WHERE league_id = 203) AS last_year
    """))
    samples = _rows(con.execute("""
        SELECT 'single_season_hr' AS record_type, p.first_name || ' ' || p.last_name AS name,
               c.year, c.hr AS value
        FROM career_bat c JOIN players p ON c.player_id = p.player_id
        WHERE c.league_id = 203 AND c.split_id = 1
        ORDER BY c.hr DESC LIMIT 5
    """))
    samples += _rows(con.execute("""
        WITH career_hr AS (
            SELECT player_id, SUM(hr) AS career_hr
            FROM career_bat WHERE league_id = 203 AND split_id = 1
            GROUP BY player_id
        )
        SELECT 'career_hr_in_save' AS record_type,
               p.first_name || ' ' || p.last_name AS name,
               NULL AS year, c.career_hr AS value
        FROM career_hr c JOIN players p ON c.player_id = p.player_id
        ORDER BY c.career_hr DESC LIMIT 5
    """))
    notes = ["records are derived views, not stored — built from career_bat / career_pit aggregates"]
    return FeatureReport("records", ["players_career_*_stats (derived)"], profile, samples, notes)


def probe_all_stars(con) -> FeatureReport:
    """All-Star teams per year."""
    profile = _rows(con.execute("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT year) AS years_covered
        FROM league_history_all_star WHERE league_id = 203
    """))
    samples = _rows(con.execute("""
        SELECT a.year, a.sub_league_id, a.all_star_pos,
               p.first_name || ' ' || p.last_name AS name
        FROM league_history_all_star a
        LEFT JOIN players p ON a.all_star = p.player_id
        WHERE a.league_id = 203 AND a.year = 2029
        ORDER BY a.sub_league_id, a.all_star_pos LIMIT 20
    """))
    notes = ["league_history_all_star uses one row per (year × position × team) — long format"]
    return FeatureReport("all_stars", ["league_history_all_star"], profile, samples, notes)


def probe_league_history(con) -> FeatureReport:
    """Annual best-player highlights per league-year (MVPs, GG winners, etc.)."""
    profile = _rows(con.execute("""
        SELECT COUNT(*) AS rows,
               COUNT(DISTINCT year) AS years
        FROM league_history WHERE league_id = 203
    """))
    samples = _rows(con.execute("""
        SELECT lh.year,
               (SELECT first_name || ' ' || last_name FROM players WHERE player_id = lh.best_hitter_id)  AS best_hitter,
               (SELECT first_name || ' ' || last_name FROM players WHERE player_id = lh.best_pitcher_id) AS best_pitcher,
               (SELECT first_name || ' ' || last_name FROM players WHERE player_id = lh.best_rookie_id)  AS best_rookie,
               (SELECT first_name || ' ' || last_name FROM players WHERE player_id = lh.best_manager_id) AS best_manager
        FROM league_history lh WHERE league_id = 203
        ORDER BY year DESC, sub_league_id
        LIMIT 12
    """))
    return FeatureReport("league_history", ["league_history"], profile, samples, [])


def probe_injuries(con) -> FeatureReport:
    """Injuries — historical log of past injuries."""
    profile = _rows(con.execute("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT player_id) AS distinct_players,
               MIN(date) AS first, MAX(date) AS last
        FROM injuries
    """))
    samples = _rows(con.execute("""
        SELECT i.date, p.first_name || ' ' || p.last_name AS player,
               i.length, i.body_part, i.day_to_day
        FROM injuries i JOIN players p ON i.player_id = p.player_id
        ORDER BY i.date DESC LIMIT 10
    """))
    return FeatureReport("injuries", ["players_injury_history"], profile, samples, [])


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────


PROBES = [
    probe_standings,
    probe_playoffs,
    probe_awards,
    probe_league_leaders,
    probe_streaks,
    probe_hall_of_fame,
    probe_movements,
    probe_records,
    probe_all_stars,
    probe_league_history,
    probe_injuries,
]


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    dump: str | None = None,
    output_path: Path | None = None,
) -> Path:
    dump = dump or save.latest_dump_name()
    output_path = output_path or Path("audit_output") / "coverage_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    console.rule(f"[bold cyan]Coverage audit — {save.save_name} / {dump}")
    con = _connect(save, dump)

    md = [
        "# OOTP Feature Coverage Audit",
        "",
        f"- **Save**: `{save.save_name}`",
        f"- **Dump**: `{dump}`",
        f"- **Scope**: MLB (`league_id = 203`) where applicable",
        "",
        "_For each user-facing feature, this audit identifies the dump CSVs that carry it, "
        "profiles row counts and time coverage, and samples a few records to verify structure._",
        "",
    ]

    for probe in PROBES:
        try:
            r = probe(con)
        except Exception as e:
            md.append(f"## {probe.__name__}\n\n**ERROR**: `{e}`\n")
            console.print(f"[red]  ! {probe.__name__}: {e}[/red]")
            continue
        console.print(f"  - {r.feature}: {len(r.profile)} profile rows, {len(r.samples)} samples")
        md.append(f"## {r.feature}")
        md.append("")
        md.append(f"**Source(s)**: {', '.join(f'`{s}`' for s in r.sources)}")
        md.append("")
        md.append("**Profile**:")
        md.append("")
        md.append(_md_table(r.profile))
        md.append("")
        md.append("**Sample records**:")
        md.append("")
        md.append(_md_table(r.samples))
        md.append("")
        if r.notes:
            md.append("**Notes**:")
            for n in r.notes:
                md.append(f"- {n}")
            md.append("")

    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Report written:[/green] {output_path}")
    return output_path


if __name__ == "__main__":
    run()
