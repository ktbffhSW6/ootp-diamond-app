"""Streak leaderboards — `diamond streaks` CLI.

Reads the L3 `f_player_streak` table and renders top-N leaderboards
per (streak_id × scope).

Two scopes:
  - `--active`    (default) — streaks alive in the latest dump
  - `--all-time`            — every streak (active + finished) in
                              the latest dump's `players_streak.csv`

OOTP retains finished streaks in `players_streak.csv` indefinitely,
so the all-time view captures every notable streak observed across
the save's history without requiring multi-dump joins.

The `--category <id>` flag filters to a single streak_id (see
`diamond.constants.StreakId` for the enum); without it the CLI
walks every category present in the table.

Note: streak labels in `f_player_streak.streak_label` come from
the `StreakId` IntEnum, whose names are best-guess derived from
max-value ranges + holder type (pitcher vs batter). They render
as a sensible header for each leaderboard but the underlying
integer code is what's authoritative.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


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


def _fetch_leaderboard(
    con: duckdb.DuckDBPyConnection,
    streak_id: int,
    scope: str,
    limit: int,
) -> list[dict]:
    rel = con.execute(
        """
        SELECT rank_in_scope, display_name, value, started, ended,
               has_ended, team_abbr, streak_label
        FROM f_player_streak
        WHERE streak_id = ? AND scope = ?
        ORDER BY rank_in_scope
        LIMIT ?
        """,
        [streak_id, scope, limit],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _all_streak_ids(con: duckdb.DuckDBPyConnection, scope: str) -> list[tuple[int, str]]:
    return con.execute(
        """
        SELECT DISTINCT streak_id, streak_label
        FROM f_player_streak
        WHERE scope = ?
        ORDER BY streak_id
        """,
        [scope],
    ).fetchall()


def _render_leaderboard(rows: list[dict], scope: str) -> None:
    if not rows:
        return
    label = rows[0]["streak_label"]
    scope_word = "active" if scope == "active" else "all-time"
    console.rule(f"[bold cyan]{label} — top {len(rows)} {scope_word}")
    t = Table(show_header=True, header_style="bold")
    t.add_column("rank", justify="right")
    t.add_column("player")
    t.add_column("len", justify="right")
    t.add_column("started")
    if scope == "all_time":
        t.add_column("ended")
        t.add_column("active")
    t.add_column("team")
    for r in rows:
        cells = [
            str(r["rank_in_scope"]),
            r["display_name"] or "—",
            str(r["value"]),
            str(r["started"]) if r["started"] else "",
        ]
        if scope == "all_time":
            cells.append(r["ended"] or "")
            cells.append("active" if not r["has_ended"] else "")
        cells.append(r["team_abbr"] or "")
        t.add_row(*cells)
    console.print(t)


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    scope: str = "active",
    category: int | None = None,
    limit: int = 10,
    output_path: Path | None = None,
) -> Path:
    """Render streaks leaderboards.

    Args:
        scope: 'active' (alive in latest dump) or 'all_time' (every
               streak observed across the save).
        category: Optional streak_id to filter to a single category;
                  None walks every category present.
    """
    if scope not in ("active", "all_time"):
        raise ValueError(f"scope must be 'active' or 'all_time', got {scope!r}")
    output_path = output_path or Path("audit_output") / f"streaks_{scope}.md"
    con = _connect(save)
    try:
        if category is not None:
            categories = [(category, None)]
        else:
            categories = _all_streak_ids(con, scope)

        md: list[str] = [
            f"# Streaks — {scope.replace('_', ' ')}  (top {limit} per category)",
            "",
            "_Built from `f_player_streak` (L3) → `streak_event` (L1) → "
            "latest dump's `players_streak.csv`. Labels are best-guess from "
            "the `StreakId` IntEnum._",
            "",
        ]
        for sid, _label in categories:
            rows = _fetch_leaderboard(con, sid, scope, limit)
            if not rows:
                continue
            _render_leaderboard(rows, scope)
            label = rows[0]["streak_label"]
            md.append(f"## {label}  (id={sid})")
            md.append("")
            cols = ["rank", "player", "len", "started"]
            seps = ["---:", "---", "---:", "---"]
            if scope == "all_time":
                cols += ["ended", "active"]
                seps += ["---", "---"]
            cols.append("team")
            seps.append("---")
            md.append("| " + " | ".join(cols) + " |")
            md.append("| " + " | ".join(seps) + " |")
            for r in rows:
                cells = [
                    str(r["rank_in_scope"]),
                    r["display_name"] or "—",
                    str(r["value"]),
                    str(r["started"]) if r["started"] else "",
                ]
                if scope == "all_time":
                    cells.append(r["ended"] or "")
                    cells.append("active" if not r["has_ended"] else "")
                cells.append(r["team_abbr"] or "")
                md.append("| " + " | ".join(cells) + " |")
            md.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(md), encoding="utf-8")
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()
    return output_path
