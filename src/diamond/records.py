"""Records leaderboards — `diamond records` CLI.

Reads the L3 `f_record_player` table (built by `diamond.schema.l3`)
and renders top-N leaderboards per (scope × discipline × category).

Two sources are joined:

  - `save`   — the user's OOTP save (MLB only, league_id=203 / level_id=1)
  - `lahman` — real-life MLB stats 1871–~2024, loaded by
               `diamond fetch-history` from the Lahman archive

The `--era` flag picks which source to surface:
  - `--era all`     unified across both (default)
  - `--era save`    save data only — the user's simulated continuation
  - `--era lahman`  real-life only — actual MLB history

Stored ranks are within-source; the CLI re-ranks dynamically when
rendering all-era so the unified column reads cleanly.

Counting stats only for v1; rate stats (AVG/OBP/SLG/ERA/FIP) need
PA/IP gates and surface via the advanced stats library when needed.
WAR and QS are save-only categories — Lahman doesn't carry them, so
`--era lahman --category WAR` returns empty.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


SEASON_BAT_CATEGORIES = [
    "HR", "RBI", "R", "H", "BB", "SB", "2B", "3B", "PA", "WAR",
    # Statcast batting season categories
    "MAX_EV", "AVG_EV", "HARD_HIT_PCT", "BARREL_PCT", "SWEET_SPOT_PCT", "MAX_DIST",
]
CAREER_BAT_CATEGORIES = [
    "HR", "RBI", "R", "H", "BB", "SB", "PA", "WAR",
    # Statcast career — peak metrics only (rate-stat career rollups skipped)
    "MAX_EV", "MAX_DIST",
]
SEASON_PIT_CATEGORIES = ["W", "S", "K", "IP", "SHO", "CG", "QS", "WAR"]
CAREER_PIT_CATEGORIES = ["W", "S", "K", "IP", "SHO", "CG", "WAR"]

# Categories that only have data in source='statcast' (i.e., empty in
# 'save' or 'lahman'). The CLI uses this to give a clearer empty-state
# hint when --era=save|lahman with a Statcast-only category.
STATCAST_ONLY_CATEGORIES = {
    "MAX_EV", "AVG_EV", "HARD_HIT_PCT", "BARREL_PCT", "SWEET_SPOT_PCT", "MAX_DIST",
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
    if category == "IP":
        outs = int(value)
        return f"{outs // 3}.{outs % 3}"
    if category == "WAR":
        return f"{value:.1f}"
    if category in ("MAX_EV", "AVG_EV"):
        return f"{value:.1f} mph"
    if category in ("HARD_HIT_PCT", "BARREL_PCT", "SWEET_SPOT_PCT"):
        return f"{value:.1f}%"
    if category == "MAX_DIST":
        return f"{int(value)} ft"
    return f"{int(value)}"


def _fetch_leaderboard(
    con: duckdb.DuckDBPyConnection,
    scope: str,
    discipline: str,
    category: str,
    era: str,
    limit: int,
) -> list[dict]:
    """Pull the leaderboard rows for one category, era-filtered.

    For `era=all` we union both sources and re-rank by value DESC.
    For `era=save` / `era=lahman` we filter to that source and use
    the stored within-source rank.
    """
    where_era = ""
    if era in ("save", "lahman", "bref", "statcast"):
        where_era = f"AND source = '{era}'"
    elif era != "all":
        raise ValueError(
            f"era must be one of 'all' / 'save' / 'lahman' / 'bref' / 'statcast', "
            f"got {era!r}"
        )

    rel = con.execute(
        f"""
        SELECT
            ROW_NUMBER() OVER (ORDER BY value DESC, display_name) AS rank,
            value, year, team_abbr, display_name, source,
            player_id, external_id
        FROM f_record_player
        WHERE scope = ?
          AND discipline = ?
          AND category = ?
          {where_era}
        ORDER BY value DESC
        LIMIT ?
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
    era: str,
) -> None:
    era_label = {
        "all": "all eras", "save": "save only",
        "lahman": "Lahman (1871-2019)", "bref": "BREF (2020-2025)",
        "statcast": "Statcast era",
    }[era]
    title = f"MLB {scope} {discipline} — {category}  [{era_label}]"
    console.rule(f"[bold cyan]{title}")
    if not rows:
        console.print(
            f"[yellow]No {category} records found for era={era!r}.[/yellow]"
        )
        if era == "lahman" and category in ("WAR", "QS"):
            console.print(
                "[dim](Lahman doesn't carry WAR or QS — try --era save or all.)[/dim]"
            )
        if era in ("save", "lahman") and category in STATCAST_ONLY_CATEGORIES:
            console.print(
                f"[dim]({category} is Statcast-only — try --era statcast or all.)[/dim]"
            )
        if era == "statcast" and category not in STATCAST_ONLY_CATEGORIES:
            console.print(
                f"[dim]({category} is a counting stat — try --era save / lahman / all.)[/dim]"
            )
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("rank", justify="right")
    t.add_column("player")
    if scope == "season":
        t.add_column("year", justify="right")
        t.add_column("team")
    t.add_column(category, justify="right")
    if era == "all":
        t.add_column("source")

    for r in rows:
        name = r["display_name"] or "—"
        val = _format_value(category, r["value"])
        cells = [str(r["rank"]), name]
        if scope == "season":
            cells.append(str(r["year"]) if r["year"] is not None else "")
            cells.append(r["team_abbr"] or "")
        cells.append(val)
        if era == "all":
            color = {
                "save": "cyan", "lahman": "magenta",
                "bref": "blue", "statcast": "yellow",
            }.get(r["source"], "white")
            cells.append(f"[{color}]{r['source']}[/{color}]")
        t.add_row(*cells)

    console.print(t)


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    scope: str = "career",
    discipline: str = "batting",
    category: str | None = None,
    era: str = "all",
    limit: int = 10,
    output_path: Path | None = None,
) -> Path:
    """Render one record category, or all categories for the given scope+discipline.

    Args:
        era: 'all' (default — unified save+lahman), 'save' (OOTP only),
             or 'lahman' (real-life MLB history only).
    """
    if scope not in ("season", "career"):
        raise ValueError(f"scope must be 'season' or 'career', got {scope!r}")
    if discipline not in ("batting", "pitching"):
        raise ValueError(f"discipline must be 'batting' or 'pitching', got {discipline!r}")
    if era not in ("all", "save", "lahman", "bref", "statcast"):
        raise ValueError(
            f"era must be one of 'all' / 'save' / 'lahman' / 'bref' / 'statcast', "
            f"got {era!r}"
        )

    output_path = output_path or (
        Path("audit_output") / f"records_{era}_{scope}_{discipline}.md"
    )
    con = _connect(save)
    try:
        cats = [category] if category is not None else _categories_for(scope, discipline)

        era_label = {
        "all": "all eras", "save": "save only",
        "lahman": "Lahman (1871-2019)", "bref": "BREF (2020-2025)",
        "statcast": "Statcast era",
    }[era]
        all_md: list[str] = [
            f"# Records — MLB {scope} {discipline}  ({era_label})",
            "",
            f"_Top {limit} per category. Built from `f_record_player` (L3)._",
            "",
        ]
        for cat in cats:
            rows = _fetch_leaderboard(con, scope, discipline, cat, era, limit)
            _render_leaderboard(rows, scope, discipline, cat, era)
            all_md.append(f"## {cat}")
            all_md.append("")
            if not rows:
                all_md.append("_No records._")
                if era == "lahman" and cat in ("WAR", "QS"):
                    all_md.append("")
                    all_md.append("_(Lahman doesn't carry WAR or QS.)_")
                all_md.append("")
                continue
            header_cols = ["rank", "player"]
            sep_cols = ["---:", "---"]
            if scope == "season":
                header_cols += ["year", "team"]
                sep_cols  += ["---:", "---"]
            header_cols.append(cat)
            sep_cols.append("---:")
            if era == "all":
                header_cols.append("source")
                sep_cols.append("---")
            all_md.append("| " + " | ".join(header_cols) + " |")
            all_md.append("| " + " | ".join(sep_cols) + " |")
            for r in rows:
                name = r["display_name"] or "—"
                val = _format_value(cat, r["value"])
                cells = [str(r["rank"]), name]
                if scope == "season":
                    cells.append(str(r["year"]) if r["year"] is not None else "")
                    cells.append(r["team_abbr"] or "")
                cells.append(val)
                if era == "all":
                    cells.append(r["source"])
                all_md.append("| " + " | ".join(cells) + " |")
            all_md.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(all_md), encoding="utf-8")
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()

    return output_path
