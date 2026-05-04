"""Draft analyzer — `diamond draft <year>` CLI.

Reads from the L3 `f_draft_class` table (built by `diamond.schema.l3`)
and renders a per-class summary plus a pick-by-pick markdown table.

Outcome buckets (set in the L3 build):
  - mlb_star      ever-MLB and career_mlb_war >= 5.0
  - mlb_regular   ever-MLB and career_mlb_war >= 1.0
  - mlb_callup    ever-MLB and career_mlb_war <  1.0
  - in_draft_org  never-MLB, still in original org
  - traded_away   never-MLB, now in different org
  - released      never-MLB, no team
  - retired       retired flag set

Reads the warehouse READ_ONLY so it can run alongside other consumers
(e.g., a UI watching the same DB).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig
# Position + level codebooks live in `diamond.constants` (canonical home for
# OOTP integer mappings per CLAUDE.md). Re-imported here so existing call
# sites (`POSITION_NAMES`, `LEVEL_NAMES`) keep working without churn.
from diamond.constants import LEVEL_NAMES, POSITION_NAMES  # noqa: F401

console = Console()


# Outcome ordering — best to worst, used for sort + display
OUTCOME_ORDER = [
    "mlb_star",
    "mlb_regular",
    "mlb_callup",
    "in_draft_org",
    "traded_away",
    "released",
    "retired",
]


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


def _fetch_class(
    con: duckdb.DuckDBPyConnection,
    year: int,
    team_id: int | None,
) -> list[dict]:
    """Fetch f_draft_class rows for the given year (and optional team)."""
    where = "draft_year = ?"
    params: list = [year]
    if team_id is not None:
        where += " AND draft_team_id = ?"
        params.append(team_id)

    rel = con.execute(
        f"""
        SELECT
            draft_round, draft_overall_pick, draft_supplemental,
            first_name, last_name, position, bats, throws,
            draft_age, college,
            draft_team_id, draft_team_name,
            current_team_id, current_team_name, current_level_id,
            retired, free_agent,
            ever_made_mlb, first_mlb_date,
            mlb_g, mlb_pa, mlb_hr, mlb_war_bat,
            mlb_g_pit, mlb_outs, mlb_w, mlb_l, mlb_s, mlb_war_pit,
            career_mlb_war, outcome, years_since_draft
        FROM f_draft_class
        WHERE {where}
        ORDER BY draft_overall_pick
        """,
        params,
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _summarize(rows: list[dict]) -> dict:
    """Roll up the headline stats for a draft class."""
    if not rows:
        return {"n": 0}
    n = len(rows)
    counts: dict[str, int] = {o: 0 for o in OUTCOME_ORDER}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    n_mlb = counts["mlb_star"] + counts["mlb_regular"] + counts["mlb_callup"]
    war_total = sum(r["career_mlb_war"] or 0 for r in rows)
    war_top = max((r["career_mlb_war"] or 0 for r in rows), default=0)
    return {
        "n": n,
        "by_outcome": counts,
        "n_mlb": n_mlb,
        "mlb_pct": (100 * n_mlb / n) if n else 0,
        "class_war": war_total,
        "war_top": war_top,
        "years_since_draft": rows[0]["years_since_draft"],
    }


def _format_player_line(r: dict) -> tuple[str, str, str, str, str, str, str, str]:
    """One row's columns for the rich table / md table.

    Returns: (pick, name, pos, age, current, status, war, line)
    """
    pos = POSITION_NAMES.get(r["position"], str(r["position"]))
    bats = {1: "R", 2: "L", 3: "S"}.get(r["bats"], "?")
    throws = {1: "R", 2: "L"}.get(r["throws"], "?")
    name = f"{r['first_name']} {r['last_name']}"

    # Pick number with supp suffix
    pick = f"{r['draft_round']}.{r['draft_overall_pick']}"
    if r["draft_supplemental"]:
        pick += "s"

    # Current placement
    if r["current_team_id"] in (None, 0):
        current = "Free agent" if not r["retired"] else "Retired"
    else:
        level = LEVEL_NAMES.get(r["current_level_id"], f"L{r['current_level_id']}")
        current = f"{r['current_team_name']} ({level})"

    # WAR display: include both bat + pit when both nonzero
    bat_w = r["mlb_war_bat"] or 0
    pit_w = r["mlb_war_pit"] or 0
    if bat_w and pit_w:
        war = f"{r['career_mlb_war']:.1f} ({bat_w:+.1f}b/{pit_w:+.1f}p)"
    elif r["position"] == 1:
        war = f"{pit_w:+.1f}" if pit_w else "—"
    else:
        war = f"{bat_w:+.1f}" if bat_w else "—"

    # Counting stat hint (PA for hitters, IP for pitchers)
    if r["position"] == 1 and r["mlb_outs"]:
        ip_int = r["mlb_outs"] // 3
        ip_frac = r["mlb_outs"] % 3
        line = f"{ip_int}.{ip_frac} IP"
    elif r["position"] != 1 and r["mlb_pa"]:
        line = f"{r['mlb_pa']} PA, {r['mlb_hr']} HR"
    else:
        line = ""

    age = str(r["draft_age"])
    handedness = f"{bats}/{throws}" if pos != "P" else throws
    pos_full = f"{pos} ({handedness})"
    status = r["outcome"].replace("_", " ")

    return (pick, name, pos_full, age, current, status, war, line)


def _print_console(year: int, summary: dict, rows: list[dict], team_filter: str | None) -> None:
    """Render the rich-table summary on stdout."""
    title = f"Draft class {year}"
    if team_filter:
        title += f" — {team_filter}"
    console.rule(f"[bold cyan]{title}")

    if not rows:
        console.print("[yellow]No draftees match this filter.[/yellow]")
        return

    yrs = summary["years_since_draft"]
    console.print(
        f"[bold]{summary['n']}[/bold] picks · "
        f"{summary['n_mlb']} reached MLB ({summary['mlb_pct']:.0f}%) · "
        f"class WAR {summary['class_war']:+.1f} · "
        f"top WAR {summary['war_top']:+.1f} · "
        f"{yrs}yr since draft"
    )
    counts = summary["by_outcome"]
    parts = [f"{counts[o]} {o.replace('_', ' ')}" for o in OUTCOME_ORDER if counts[o]]
    console.print("[dim]" + "  ·  ".join(parts) + "[/dim]\n")

    t = Table(show_header=True, header_style="bold", show_lines=False)
    t.add_column("pick", justify="right", style="cyan")
    t.add_column("player")
    t.add_column("pos")
    t.add_column("age", justify="right")
    t.add_column("current", overflow="fold")
    t.add_column("status")
    t.add_column("MLB WAR", justify="right")
    t.add_column("MLB line", overflow="fold")

    for r in rows:
        pick, name, pos, age, current, status, war, line = _format_player_line(r)
        # Color status by outcome
        color = {
            "mlb star":     "bold green",
            "mlb regular":  "green",
            "mlb callup":   "yellow",
            "in draft org": "white",
            "traded away":  "magenta",
            "released":     "red",
            "retired":      "dim",
        }.get(status, "white")
        t.add_row(pick, name, pos, age, current, f"[{color}]{status}[/{color}]", war, line)

    console.print(t)


def _write_markdown(
    year: int,
    summary: dict,
    rows: list[dict],
    team_filter: str | None,
    output_path: Path,
) -> None:
    """Write the same content as a markdown report."""
    title = f"Draft class {year}"
    if team_filter:
        title += f" — {team_filter}"

    md = [f"# {title}", ""]

    if not rows:
        md.append("_No draftees match this filter._")
        output_path.write_text("\n".join(md), encoding="utf-8")
        return

    md.append(
        f"- **Picks**: {summary['n']}"
    )
    md.append(
        f"- **Reached MLB**: {summary['n_mlb']} ({summary['mlb_pct']:.0f}%)"
    )
    md.append(f"- **Class career MLB WAR**: {summary['class_war']:+.1f}")
    md.append(f"- **Top WAR**: {summary['war_top']:+.1f}")
    md.append(f"- **Years since draft**: {summary['years_since_draft']}")
    md.append("")
    md.append("**Outcome breakdown**")
    md.append("")
    md.append("| outcome | n |")
    md.append("| --- | --: |")
    for o in OUTCOME_ORDER:
        c = summary["by_outcome"].get(o, 0)
        if c:
            md.append(f"| {o.replace('_', ' ')} | {c} |")
    md.append("")

    md.append("## Pick by pick")
    md.append("")
    md.append("| pick | player | pos | age | current | status | MLB WAR | MLB line |")
    md.append("| --- | --- | --- | --: | --- | --- | --: | --- |")
    for r in rows:
        pick, name, pos, age, current, status, war, line = _format_player_line(r)
        md.append(f"| {pick} | {name} | {pos} | {age} | {current} | {status} | {war} | {line} |")
    md.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(md), encoding="utf-8")


def run(
    year: int,
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    team_id: int | None = None,
    output_path: Path | None = None,
) -> Path:
    """Render the draft analyzer for one year (and optional team)."""
    output_path = output_path or Path("audit_output") / f"draft_{year}.md"

    con = _connect(save)
    try:
        rows = _fetch_class(con, year, team_id)
        team_filter: str | None = None
        if team_id is not None:
            r = con.execute(
                "SELECT name FROM teams WHERE team_id = ?", [team_id]
            ).fetchone()
            team_filter = r[0] if r else f"team_id={team_id}"

        summary = _summarize(rows)
        _print_console(year, summary, rows, team_filter)
        _write_markdown(year, summary, rows, team_filter, output_path)
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()

    return output_path
