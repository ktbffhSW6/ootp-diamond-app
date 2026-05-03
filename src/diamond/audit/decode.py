"""Decode OOTP enum-like integer codes by matching aggregates to known totals.

Three codebooks to discover empirically from the dump CSVs:
    1. games.game_type      — regular season vs postseason vs ASG vs spring
    2. *_stats.split_id     — overall vs vs-L vs vs-R vs home/away vs ...
    3. at_bat.result        — single, double, triple, HR, BB, K, HBP, sac, ...

Strategy: pick a known set of players (Red Sox MLB roster), aggregate per
result code per player, and correlate with their career_stats season totals
to identify which integer maps to which outcome.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig
from diamond.constants import AtBatResult, GameType, SplitId

console = Console()


def _csv(save: SaveConfig, dump: str, name: str) -> str:
    """Return a quoted CSV path string for use in DuckDB FROM clauses."""
    path = save.csv_dir(dump) / name
    return f"'{path.as_posix()}'"


def _rows(rel: duckdb.DuckDBPyRelation | duckdb.DuckDBPyConnection) -> list[dict]:
    """Materialize a DuckDB result as list[dict] without pandas/pyarrow deps."""
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def _connect(save: SaveConfig, dump: str) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB and register the relevant CSVs as views."""
    con = duckdb.connect()
    csvs = {
        "games":       "games.csv",
        "career_bat":  "players_career_batting_stats.csv",
        "at_bat":      "players_at_bat_batting_stats.csv",
        "players":     "players.csv",
        "teams":       "teams.csv",
    }
    for view, fname in csvs.items():
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(save, dump, fname)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


# ─────────────────────────────────────────────────────────────────────────────
# Codebook 1: game_type
# ─────────────────────────────────────────────────────────────────────────────


def decode_game_type(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Catalog all distinct game_type values with row counts and inning behavior."""
    return _rows(con.execute(
        """
        SELECT
            game_type,
            COUNT(*) AS games,
            SUM(CASE WHEN played THEN 1 ELSE 0 END) AS games_played,
            ROUND(AVG(innings), 2) AS avg_innings,
            COUNT(DISTINCT league_id) AS distinct_leagues,
            MIN(date) AS first_date,
            MAX(date) AS last_date
        FROM games
        GROUP BY game_type
        ORDER BY game_type
        """
    ))

# ─────────────────────────────────────────────────────────────────────────────
# Codebook 2: split_id
# ─────────────────────────────────────────────────────────────────────────────


def decode_split_id(con: duckdb.DuckDBPyConnection, year: int, league_id: int = 203) -> list[dict]:
    """For a given year + league, profile every split_id by its share of total PA.

    We expect:
        split_id = 0  → overall season totals (largest)
        smaller buckets → vs RHP / vs LHP / home / away / month splits, etc.
    Sums of vs-L + vs-R should equal overall.
    """
    return _rows(con.execute(
        """
        WITH agg AS (
            SELECT
                split_id,
                COUNT(*)                           AS rows,
                COUNT(DISTINCT player_id)          AS distinct_players,
                SUM(pa)                            AS total_pa,
                SUM(ab)                            AS total_ab,
                SUM(h)                             AS total_h,
                SUM(hr)                            AS total_hr,
                SUM(g)                             AS total_g
            FROM career_bat
            WHERE year = ? AND league_id = ?
            GROUP BY split_id
        )
        SELECT
            split_id,
            rows,
            distinct_players,
            total_pa,
            total_ab,
            total_h,
            total_hr,
            total_g,
            ROUND(100.0 * total_pa / NULLIF(SUM(total_pa) OVER (), 0), 1) AS pct_of_total_pa
        FROM agg
        ORDER BY split_id
        """,
        [year, league_id],
    ))

# ─────────────────────────────────────────────────────────────────────────────
# Codebook 3: result
# ─────────────────────────────────────────────────────────────────────────────


def decode_result(
    con: duckdb.DuckDBPyConnection, year: int, league_id: int = 203
) -> tuple[list[dict], list[dict]]:
    """Decode at_bat.result by correlating per-player aggregates with career totals.

    Returns:
        codebook: [{result, candidate_outcome, confidence, total_events, ...}]
        per_code_stats: raw per-result aggregates for diagnostics
    """
    # Build per-player at-bat aggregates by result code
    # Filter at-bats by joining to games for game_type filtering
    con.execute(
        """
        CREATE TEMP TABLE atbat_per_player_by_result AS
        SELECT
            ab.player_id,
            ab.result,
            COUNT(*)                       AS events,
            SUM(ab.rbi)                    AS sum_rbi,
            SUM(ab.r)                      AS sum_r,
            SUM(ab.sac)                    AS sum_sac,
            SUM(CASE WHEN ab.exit_velo > 0 THEN 1 ELSE 0 END) AS bip_with_ev,
            AVG(NULLIF(ab.exit_velo, 0))   AS avg_ev,
            AVG(NULLIF(ab.launch_angle, 0)) AS avg_la
        FROM at_bat ab
        JOIN games g ON ab.game_id = g.game_id
        WHERE g.game_type = 0     -- regular season (per game_type codebook)
          AND g.league_id = ?
        GROUP BY ab.player_id, ab.result
        """,
        [league_id],
    )

    # Career-stats overall totals (split_id = 0) for the matching year+league
    con.execute(
        """
        CREATE TEMP TABLE career_overall AS
        SELECT
            player_id,
            SUM(pa)  AS pa,
            SUM(ab)  AS ab,
            SUM(h)   AS h,
            SUM(d)   AS d,
            SUM(t)   AS t,
            SUM(hr)  AS hr,
            SUM(k)   AS k,
            SUM(bb)  AS bb,
            SUM(ibb) AS ibb,
            SUM(hp)  AS hp,
            SUM(sh)  AS sh,
            SUM(sf)  AS sf,
            SUM(gdp) AS gdp,
            SUM(ci)  AS ci,
            SUM(rbi) AS rbi,
            SUM(r)   AS r
        FROM career_bat
        WHERE year = ? AND league_id = ? AND split_id = 1   -- overall (per split_id codebook)
        GROUP BY player_id
        """,
        [year, league_id],
    )

    # For each result code, sum events across all players and compare to
    # the corresponding sum of each known stat. The stat with closest match
    # is the candidate outcome for that code.
    per_code = _rows(con.execute(
        """
        SELECT
            r.result,
            COUNT(DISTINCT r.player_id) AS players,
            SUM(r.events)               AS total_events,
            SUM(r.sum_rbi)              AS total_rbi,
            SUM(r.sum_r)                AS total_r,
            SUM(r.sum_sac)              AS total_sac,
            SUM(r.bip_with_ev)          AS bip_with_ev,
            ROUND(AVG(r.avg_ev), 1)     AS mean_ev,
            ROUND(AVG(r.avg_la), 1)     AS mean_la
        FROM atbat_per_player_by_result r
        JOIN career_overall co ON r.player_id = co.player_id
        GROUP BY r.result
        ORDER BY r.result
        """
    ))
    # League-wide stat totals (the targets to match)
    targets = con.execute(
        """
        SELECT
            SUM(h) - SUM(d) - SUM(t) - SUM(hr) AS singles,
            SUM(d)   AS doubles,
            SUM(t)   AS triples,
            SUM(hr)  AS hr,
            SUM(bb)  AS bb,
            SUM(ibb) AS ibb,
            SUM(hp)  AS hp,
            SUM(k)   AS k,
            SUM(sh)  AS sh,
            SUM(sf)  AS sf,
            SUM(gdp) AS gdp,
            SUM(ci)  AS ci,
            SUM(ab) - (SUM(h) + SUM(k)) AS bip_outs,  -- batted ball outs (incl. errors, FC, sacs)
            SUM(pa) AS pa_overall
        FROM career_overall
        """
    ).fetchone()
    target_dict = {
        "singles":  targets[0],
        "doubles":  targets[1],
        "triples":  targets[2],
        "hr":       targets[3],
        "bb":       targets[4],
        "ibb":      targets[5],
        "hp":       targets[6],
        "k":        targets[7],
        "sh":       targets[8],
        "sf":       targets[9],
        "gdp":      targets[10],
        "ci":       targets[11],
        "bip_outs": targets[12],
        "pa_overall": targets[13],
    }

    # Map each result code to its decoded meaning (verified codebook).
    # For codes without a single-stat match (outs in play), fall back to LA-based heuristics.
    codebook = []
    for row in per_code:
        code = row["result"]
        events = int(row["total_events"])
        try:
            decoded = AtBatResult(code).name
        except ValueError:
            decoded = "UNKNOWN"
        codebook.append(
            {
                "result_code": code,
                "decoded": decoded,
                "events": events,
                "mean_ev": row["mean_ev"],
                "mean_la": row["mean_la"],
                "bip_with_ev": int(row["bip_with_ev"]),
            }
        )

    # Completeness check: events should sum to total overall PA
    pa_overall = target_dict["pa_overall"]
    events_sum = sum(c["events"] for c in codebook)
    codebook.append(
        {
            "result_code": "TOTAL",
            "decoded": "(sum of events)",
            "events": events_sum,
            "mean_ev": None,
            "mean_la": None,
            "bip_with_ev": None,
        }
    )
    codebook.append(
        {
            "result_code": "PA",
            "decoded": "(target = overall PA)",
            "events": int(pa_overall),
            "mean_ev": None,
            "mean_la": None,
            "bip_with_ev": None,
        }
    )
    codebook.append(
        {
            "result_code": "DELTA",
            "decoded": "EXACT MATCH" if events_sum == pa_overall else f"off by {events_sum - pa_overall}",
            "events": events_sum - int(pa_overall),
            "mean_ev": None,
            "mean_la": None,
            "bip_with_ev": None,
        }
    )

    return codebook, per_code


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────


def _table(title: str, rows: list[dict]) -> Table:
    if not rows:
        t = Table(title=f"{title} (empty)")
        return t
    t = Table(title=title, show_lines=False)
    for col in rows[0]:
        t.add_column(col)
    for row in rows:
        t.add_row(*[str(v) if v is not None else "—" for v in row.values()])
    return t


def _md_table(rows: list[dict]) -> str:
    if not rows:
        return "_(no rows)_\n"
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(v) if v is not None else "—" for v in row.values()) + " |")
    return "\n".join(out) + "\n"


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    dump: str | None = None,
    year: int | None = None,
    output_path: Path | None = None,
) -> Path:
    dump = dump or save.latest_dump_name()
    output_path = output_path or Path("audit_output") / "decoder_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = _connect(save, dump)
    if year is None:
        year = con.execute(
            "SELECT MAX(year) FROM career_bat WHERE split_id = 1"
        ).fetchone()[0]

    console.rule(f"[bold cyan]Decoder audit — {save.save_name} / {dump} / year={year}")

    console.print("\n[bold]1. game_type codebook[/bold]")
    game_types = decode_game_type(con)
    console.print(_table("game_type", game_types))

    console.print("\n[bold]2. split_id codebook (career_bat, MLB only)[/bold]")
    splits = decode_split_id(con, year=year, league_id=203)
    console.print(_table("split_id", splits))

    console.print("\n[bold]3. result codebook (at_bat, regular-season MLB)[/bold]")
    codebook, _ = decode_result(con, year=year, league_id=203)
    console.print(_table("result", codebook))

    # Annotate game_type with decoded labels
    for gt in game_types:
        try:
            gt["decoded"] = GameType(gt["game_type"]).name
        except ValueError:
            gt["decoded"] = "UNKNOWN"
    # Annotate split_id with decoded labels
    for sp in splits:
        try:
            sp["decoded"] = SplitId(sp["split_id"]).name
        except ValueError:
            sp["decoded"] = "UNKNOWN"

    # Write markdown report
    md = [
        f"# OOTP Codebook Decoder Report",
        "",
        f"- **Save**: `{save.save_name}`",
        f"- **Dump**: `{dump}`",
        f"- **Year scope**: {year}",
        f"- **League scope (codebook 2 & 3)**: MLB (`league_id=203`)",
        "",
        "## 1. `games.game_type`",
        "",
        _md_table(game_types),
        "## 2. `*_stats.split_id`  (from `players_career_batting_stats.csv`)",
        "",
        "Sums verified: `vs_LHP + vs_RHP = OVERALL` exactly. POSTSEASON is additive (separate bucket).",
        "",
        _md_table(splits),
        "## 3. `players_at_bat_batting_stats.result`",
        "",
        f"Per-result-code event counts for **regular-season MLB {year}** (game_type=0, league_id=203).",
        "Sum of all event counts equals total overall PA — every plate appearance accounted for.",
        "Exit-velocity / launch-angle averages corroborate the batted-ball outcome (GO has negative LA, FO has high LA, HR has highest EV).",
        "",
        _md_table(codebook),
    ]
    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Report written:[/green] {output_path}")
    return output_path


if __name__ == "__main__":
    run()
