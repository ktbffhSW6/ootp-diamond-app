"""Records leaderboards — `diamond records` CLI.

Reads the L3 `f_record_player` table (built by `diamond.schema.l3`)
and renders top-N leaderboards per (scope × discipline × category).

Scope is hardcoded to MLB (league_id=203, level_id=1) at the L3
build layer; this module is just presentation. Foreign / minor
records can be unlocked later by parameterizing RECORD_LEAGUE_ID /
RECORD_LEVEL_ID in `schema/l3.py` and rebuilding L3.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


# Display-friendly category names per discipline (a category that exists in
# both season and career scopes uses the same display label in both).
SEASON_BAT_CATEGORIES = ["HR", "RBI", "R", "H", "BB", "SB", "2B", "3B", "PA", "WAR"]
CAREER_BAT_CATEGORIES = ["HR", "RBI", "R", "H", "BB", "SB", "PA", "WAR"]
SEASON_PIT_CATEGORIES = ["W", "S", "K", "IP", "SHO", "CG", "QS", "WAR"]
CAREER_PIT_CATEGORIES = ["W", "S", "K", "IP", "SHO", "CG", "WAR"]


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


def _categories_for(scope: str, discipline: str) -> list[str]:
    if scope == "season" and discipline == "batting":
        return SEASON_BAT_CATEGORIES
    if scope == "career" and discipline == "batting":
        return CAREER_BAT_CATEGORIES
    if scope == "season" and discipline == "pitching":
        return SEASON_PIT_CATEGORIES
    if scope == "career" and discipline == "pitching":
        return CAREER_PIT_CATEGORIES
    return []


def _format_value(category: str, value: float) -> str:
    """Render a stat value to display form. IP is stored as outs."""
    if category == "IP":
        outs = int(value)
        return f"{outs // 3}.{outs % 3}"
    if category == "WAR":
        return f"{value:.1f}"
    return f"{int(value)}"


def _fetch_leaderboard(
    con: duckdb.DuckDBPyConnection,
    scope: str,
    discipline: str,
    category: str,
    limit: int,
) -> list[dict]:
    rel = con.execute(
        """
        SELECT rp.rank, rp.value, rp.year, rp.player_id, rp.team_id,
               p.first_name, p.last_name, t.abbr AS team_abbr
        FROM f_record_player rp
        LEFT JOIN players_current p ON p.player_id = rp.player_id
        LEFT JOIN teams t            ON t.team_id  = rp.team_id
        WHERE rp.scope = ?
          AND rp.discipline = ?
          AND rp.category = ?
          AND rp.rank <= ?
        ORDER BY rp.rank
        """,
        [scope, discipline, category, limit],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _render_leaderboard(
    rows: list[dict],
    scope: str,
    discipline: str,
    category: str,
) -> None:
    title = f"All-time MLB {scope} {discipline} — {category}"
    console.rule(f"[bold cyan]{title}")
    if not rows:
        console.print("[yellow]No records found for this category.[/yellow]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("rank", justify="right")
    t.add_column("player")
    if scope == "season":
        t.add_column("year", justify="right")
        t.add_column("team")
    t.add_column(category, justify="right")

    for r in rows:
        name = f"{r['first_name']} {r['last_name']}" if r["first_name"] else f"#{r['player_id']}"
        val = _format_value(category, r["value"])
        if scope == "season":
            t.add_row(
                str(r["rank"]),
                name,
                str(r["year"]) if r["year"] is not None else "",
                r["team_abbr"] or "",
                val,
            )
        else:
            t.add_row(str(r["rank"]), name, val)

    console.print(t)


def _write_markdown(
    rows: list[dict],
    scope: str,
    discipline: str,
    category: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    md = [
        f"# Records — MLB {scope} {discipline} {category}",
        "",
        f"_Top {len(rows)} all-time. Built from `f_record_player` (L3)._",
        "",
    ]
    if not rows:
        md.append("_No records._")
        output_path.write_text("\n".join(md), encoding="utf-8")
        return
    if scope == "season":
        md.append("| rank | player | year | team | " + category + " |")
        md.append("| ---: | --- | ---: | --- | ---: |")
    else:
        md.append("| rank | player | " + category + " |")
        md.append("| ---: | --- | ---: |")
    for r in rows:
        name = f"{r['first_name']} {r['last_name']}" if r["first_name"] else f"#{r['player_id']}"
        val = _format_value(category, r["value"])
        if scope == "season":
            md.append(
                f"| {r['rank']} | {name} | {r['year']} | {r['team_abbr'] or ''} | {val} |"
            )
        else:
            md.append(f"| {r['rank']} | {name} | {val} |")
    md.append("")
    output_path.write_text("\n".join(md), encoding="utf-8")


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    scope: str = "career",
    discipline: str = "batting",
    category: str | None = None,
    limit: int = 10,
    output_path: Path | None = None,
) -> Path:
    """Render one record category, or all categories for the given scope+discipline."""
    if scope not in ("season", "career"):
        raise ValueError(f"scope must be 'season' or 'career', got {scope!r}")
    if discipline not in ("batting", "pitching"):
        raise ValueError(f"discipline must be 'batting' or 'pitching', got {discipline!r}")

    output_path = output_path or Path("audit_output") / f"records_{scope}_{discipline}.md"
    con = _connect(save)
    try:
        if category is not None:
            cats = [category]
        else:
            cats = _categories_for(scope, discipline)

        all_md: list[str] = [
            f"# Records — MLB {scope} {discipline}",
            "",
            f"_All-time top {limit} per category. Built from `f_record_player` (L3)._",
            "",
        ]
        for cat in cats:
            rows = _fetch_leaderboard(con, scope, discipline, cat, limit)
            _render_leaderboard(rows, scope, discipline, cat)
            # Append category section to consolidated markdown
            all_md.append(f"## {cat}")
            all_md.append("")
            if not rows:
                all_md.append("_No records._")
                all_md.append("")
                continue
            if scope == "season":
                all_md.append("| rank | player | year | team | " + cat + " |")
                all_md.append("| ---: | --- | ---: | --- | ---: |")
            else:
                all_md.append("| rank | player | " + cat + " |")
                all_md.append("| ---: | --- | ---: |")
            for r in rows:
                name = (
                    f"{r['first_name']} {r['last_name']}"
                    if r["first_name"] else f"#{r['player_id']}"
                )
                val = _format_value(cat, r["value"])
                if scope == "season":
                    all_md.append(
                        f"| {r['rank']} | {name} | {r['year']} | "
                        f"{r['team_abbr'] or ''} | {val} |"
                    )
                else:
                    all_md.append(f"| {r['rank']} | {name} | {val} |")
            all_md.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(all_md), encoding="utf-8")
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()

    return output_path
