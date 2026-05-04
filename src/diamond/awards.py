"""Awards leaderboards — `diamond awards` CLI.

Three views, all backed by L3:
  - Career-leaders board: who has won an award the most times across the save
  - Per-player career: every award a single player has won
  - Per-franchise totals: which orgs have collected the most of each award

Uses `f_award_career_player` (per player) and `f_award_franchise` (per
team — rolled up to MLB org via parent_team_id) tables.

Note: `f_award_event` is event-shaped — it only contains awards from
dumps captured during the save (2026 onward in the current Sox save).
Pre-save historical awards (e.g., real-life MVPs from 2021) are not
in the per-dump CSVs OOTP exports, so any "career MVP leaderboard"
here only counts wins since the save started.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig
from diamond.constants import AwardId

console = Console()


# Award display labels — match the AwardId enum
AWARD_LABEL: dict[int, str] = {
    AwardId.PLAYER_OF_THE_WEEK:    "Player of the Week",
    AwardId.PITCHER_OF_THE_MONTH:  "Pitcher of the Month",
    AwardId.HITTER_OF_THE_MONTH:   "Hitter of the Month",
    AwardId.ROOKIE_OF_THE_MONTH:   "Rookie of the Month",
    AwardId.CY_YOUNG:              "Cy Young (top-3)",
    AwardId.MVP:                   "MVP (top-3)",
    AwardId.ROOKIE_OF_THE_YEAR:    "Rookie of the Year (top-3)",
    AwardId.GOLD_GLOVE:            "Gold Glove",
    AwardId.ALL_STAR:              "All-Star",
    AwardId.SILVER_SLUGGER:        "Silver Slugger",
    AwardId.RELIEVER_OF_THE_YEAR:  "Reliever of the Year",
    AwardId.WS_CHAMPION_ROSTER:    "WS Champion (roster)",
    AwardId.POSTSEASON_SERIES_MVP: "Postseason Series MVP",
}


def _connect(save: SaveConfig) -> duckdb.DuckDBPyConnection:
    db_path = save.save_dir / "diamond" / "diamond.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(
            f"Warehouse DB not found at {db_path}. Run `diamond ingest --all` first."
        )
    con = duckdb.connect()
    con.execute(f"ATTACH '{db_path.as_posix()}' AS wh (READ_ONLY)")
    con.execute("USE wh")
    return con


def _award_label(award_id: int) -> str:
    return AWARD_LABEL.get(award_id, f"award_id={award_id}")


def _fetch_player_leaderboard(
    con: duckdb.DuckDBPyConnection,
    award_id: int,
    league_id: int,
    limit: int,
) -> list[dict]:
    rel = con.execute(
        """
        SELECT acp.player_id, acp.n_won, acp.first_year, acp.last_year,
               acp.last_team_id,
               p.first_name, p.last_name,
               t.abbr AS last_team_abbr
        FROM f_award_career_player acp
        LEFT JOIN players_current p ON p.player_id = acp.player_id
        LEFT JOIN teams t           ON t.team_id   = acp.last_team_id
        WHERE acp.award_id = ?
          AND acp.league_id = ?
        ORDER BY acp.n_won DESC, acp.last_year DESC
        LIMIT ?
        """,
        [award_id, league_id, limit],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _fetch_player_career(
    con: duckdb.DuckDBPyConnection, player_id: int, league_id: int
) -> list[dict]:
    rel = con.execute(
        """
        SELECT award_id, n_won, first_year, last_year
        FROM f_award_career_player
        WHERE player_id = ? AND league_id = ?
        ORDER BY n_won DESC, last_year DESC, award_id
        """,
        [player_id, league_id],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _fetch_franchise(
    con: duckdb.DuckDBPyConnection, team_id: int, league_id: int
) -> list[dict]:
    rel = con.execute(
        """
        SELECT award_id, n_won, first_year, last_year
        FROM f_award_franchise
        WHERE team_id = ? AND league_id = ?
        ORDER BY n_won DESC, award_id
        """,
        [team_id, league_id],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _player_name(con: duckdb.DuckDBPyConnection, player_id: int) -> str:
    r = con.execute(
        "SELECT first_name || ' ' || last_name FROM players_current WHERE player_id = ?",
        [player_id],
    ).fetchone()
    return r[0] if r else f"player_id={player_id}"


def _team_name(con: duckdb.DuckDBPyConnection, team_id: int) -> str:
    r = con.execute(
        "SELECT name FROM teams WHERE team_id = ?", [team_id]
    ).fetchone()
    return r[0] if r else f"team_id={team_id}"


def _render_player_leaderboard(
    rows: list[dict], award_id: int, league_id: int
) -> None:
    label = _award_label(award_id)
    console.rule(f"[bold cyan]Career leaders — {label}  (league {league_id})")
    if not rows:
        console.print("[yellow]No winners on record.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("player")
    t.add_column("n", justify="right")
    t.add_column("years")
    t.add_column("last team")
    for r in rows:
        name = (
            f"{r['first_name']} {r['last_name']}"
            if r["first_name"] else f"#{r['player_id']}"
        )
        years = (
            f"{r['first_year']}–{r['last_year']}"
            if r["first_year"] != r["last_year"] else str(r["first_year"])
        )
        t.add_row(name, str(r["n_won"]), years, r["last_team_abbr"] or "")
    console.print(t)


def _render_player_career(
    con: duckdb.DuckDBPyConnection, rows: list[dict], player_id: int, league_id: int
) -> None:
    name = _player_name(con, player_id)
    console.rule(f"[bold cyan]Career awards — {name}  (league {league_id})")
    if not rows:
        console.print("[yellow]No awards on record.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("award")
    t.add_column("n", justify="right")
    t.add_column("years")
    for r in rows:
        years = (
            f"{r['first_year']}–{r['last_year']}"
            if r["first_year"] != r["last_year"] else str(r["first_year"])
        )
        t.add_row(_award_label(r["award_id"]), str(r["n_won"]), years)
    console.print(t)


def _render_franchise(
    con: duckdb.DuckDBPyConnection, rows: list[dict], team_id: int, league_id: int
) -> None:
    name = _team_name(con, team_id)
    console.rule(f"[bold cyan]Franchise awards — {name}  (league {league_id})")
    if not rows:
        console.print("[yellow]No awards on record.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("award")
    t.add_column("n", justify="right")
    t.add_column("years")
    for r in rows:
        years = (
            f"{r['first_year']}–{r['last_year']}"
            if r["first_year"] != r["last_year"] else str(r["first_year"])
        )
        t.add_row(_award_label(r["award_id"]), str(r["n_won"]), years)
    console.print(t)


def _write_markdown_leaderboard(
    rows: list[dict], award_id: int, league_id: int, output_path: Path
) -> None:
    label = _award_label(award_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md = [f"# Career leaders — {label}  (league {league_id})", ""]
    if not rows:
        md.append("_No winners on record._")
    else:
        md.append("| player | n | years | last team |")
        md.append("| --- | ---: | --- | --- |")
        for r in rows:
            name = (
                f"{r['first_name']} {r['last_name']}"
                if r["first_name"] else f"#{r['player_id']}"
            )
            years = (
                f"{r['first_year']}–{r['last_year']}"
                if r["first_year"] != r["last_year"] else str(r["first_year"])
            )
            md.append(
                f"| {name} | {r['n_won']} | {years} | {r['last_team_abbr'] or ''} |"
            )
    output_path.write_text("\n".join(md), encoding="utf-8")


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    award_id: int | None = None,
    player_id: int | None = None,
    team_id: int | None = None,
    league_id: int = 203,
    limit: int = 15,
    output_path: Path | None = None,
) -> Path:
    """Three modes, in priority order:
      - player_id provided  → render that player's full career-awards table
      - team_id provided    → render franchise totals
      - award_id provided   → render top-N players for that award
      - none → render top-N for *every* award (the default catalog view)
    """
    output_path = output_path or Path("audit_output") / "awards.md"
    con = _connect(save)
    try:
        if player_id is not None:
            rows = _fetch_player_career(con, player_id, league_id)
            _render_player_career(con, rows, player_id, league_id)
            md = [
                f"# Career awards — {_player_name(con, player_id)}  (league {league_id})",
                "",
            ]
            if not rows:
                md.append("_No awards on record._")
            else:
                md.append("| award | n | years |")
                md.append("| --- | ---: | --- |")
                for r in rows:
                    years = (
                        f"{r['first_year']}–{r['last_year']}"
                        if r["first_year"] != r["last_year"] else str(r["first_year"])
                    )
                    md.append(f"| {_award_label(r['award_id'])} | {r['n_won']} | {years} |")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(md), encoding="utf-8")
        elif team_id is not None:
            rows = _fetch_franchise(con, team_id, league_id)
            _render_franchise(con, rows, team_id, league_id)
            md = [
                f"# Franchise awards — {_team_name(con, team_id)}  (league {league_id})",
                "",
            ]
            if not rows:
                md.append("_No awards on record._")
            else:
                md.append("| award | n | years |")
                md.append("| --- | ---: | --- |")
                for r in rows:
                    years = (
                        f"{r['first_year']}–{r['last_year']}"
                        if r["first_year"] != r["last_year"] else str(r["first_year"])
                    )
                    md.append(f"| {_award_label(r['award_id'])} | {r['n_won']} | {years} |")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(md), encoding="utf-8")
        elif award_id is not None:
            rows = _fetch_player_leaderboard(con, award_id, league_id, limit)
            _render_player_leaderboard(rows, award_id, league_id)
            _write_markdown_leaderboard(rows, award_id, league_id, output_path)
        else:
            # Catalog view — leaderboard for every award_id observed
            seen = [
                r[0] for r in con.execute(
                    """
                    SELECT DISTINCT award_id
                    FROM f_award_career_player
                    WHERE league_id = ?
                    ORDER BY award_id
                    """,
                    [league_id],
                ).fetchall()
            ]
            md = [f"# Career awards leaderboard catalog  (league {league_id})", ""]
            for aid in seen:
                rows = _fetch_player_leaderboard(con, aid, league_id, limit)
                _render_player_leaderboard(rows, aid, league_id)
                md.append(f"## {_award_label(aid)}")
                md.append("")
                if not rows:
                    md.append("_No winners on record._")
                    md.append("")
                    continue
                md.append("| player | n | years | last team |")
                md.append("| --- | ---: | --- | --- |")
                for r in rows:
                    name = (
                        f"{r['first_name']} {r['last_name']}"
                        if r["first_name"] else f"#{r['player_id']}"
                    )
                    years = (
                        f"{r['first_year']}–{r['last_year']}"
                        if r["first_year"] != r["last_year"] else str(r["first_year"])
                    )
                    md.append(
                        f"| {name} | {r['n_won']} | {years} | "
                        f"{r['last_team_abbr'] or ''} |"
                    )
                md.append("")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n".join(md), encoding="utf-8")
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()
    return output_path
