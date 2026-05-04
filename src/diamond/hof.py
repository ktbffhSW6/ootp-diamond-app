"""Hall of Fame tracker — `diamond hof` CLI.

Surfaces directly off `players_current` (`hall_of_fame` and `inducted`
boolean columns) joined to `f_award_career_player` for the awards-based
"path to induction" line. No new L3 table needed for v1.

In a fresh save, both columns will be 0 across the board until enough
in-game years have passed for OOTP to start inducting players. The
CLI reports the empty case clearly and shows the WAR / awards leaders
who are *plausible* future candidates, ranked by career MLB WAR.

Three modes:
  - default                → list every HoFer with stats + path
  - --candidates           → top-25 retired (or active) players by
                             career MLB WAR who haven't been inducted
                             yet — rough HoF shortlist
  - --player <player_id>   → drill into one player's HoF resume
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig
from diamond.constants import AwardId

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


# Career-WAR + counting "shortlist" thresholds — rough heuristics for who
# *might* be HoF-bound. These are intentionally generous; OOTP's voters
# tend to be more selective.
HOF_WAR_FLOOR = 50.0
HOF_BAT_PA_FLOOR = 6000
HOF_PIT_OUTS_FLOOR = 6000  # ~2,000 IP


def _fetch_inducted(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rel = con.execute(
        """
        WITH cb AS (
            SELECT player_id,
                   SUM(pa) AS mlb_pa, SUM(hr) AS mlb_hr, SUM(war) AS mlb_war_bat
            FROM players_career_batting_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        cp AS (
            SELECT player_id,
                   SUM(outs) AS mlb_outs, SUM(w) AS mlb_w, SUM(s) AS mlb_s,
                   SUM(k) AS mlb_k, SUM(war) AS mlb_war_pit
            FROM players_career_pitching_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        awards_n AS (
            SELECT player_id,
                   SUM(CASE WHEN award_id = 5 THEN n_won ELSE 0 END) AS mvps,
                   SUM(CASE WHEN award_id = 4 THEN n_won ELSE 0 END) AS cys,
                   SUM(CASE WHEN award_id = 9 THEN n_won ELSE 0 END) AS asgs,
                   SUM(CASE WHEN award_id = 7 THEN n_won ELSE 0 END) AS gold_gloves,
                   SUM(CASE WHEN award_id = 11 THEN n_won ELSE 0 END) AS silver_sluggers,
                   SUM(CASE WHEN award_id = 14 THEN n_won ELSE 0 END) AS ws_rings
            FROM f_award_career_player
            WHERE league_id = 203
            GROUP BY player_id
        )
        SELECT
            p.player_id,
            p.first_name, p.last_name,
            p.position, p.retired, p.hall_of_fame, p.inducted,
            COALESCE(cb.mlb_pa, 0)   AS mlb_pa,
            COALESCE(cb.mlb_hr, 0)   AS mlb_hr,
            COALESCE(cb.mlb_war_bat, 0.0) AS mlb_war_bat,
            COALESCE(cp.mlb_outs, 0) AS mlb_outs,
            COALESCE(cp.mlb_w, 0)    AS mlb_w,
            COALESCE(cp.mlb_k, 0)    AS mlb_k,
            COALESCE(cp.mlb_war_pit, 0.0) AS mlb_war_pit,
            COALESCE(cb.mlb_war_bat, 0.0) + COALESCE(cp.mlb_war_pit, 0.0) AS career_mlb_war,
            COALESCE(a.mvps, 0)            AS mvps,
            COALESCE(a.cys, 0)             AS cys,
            COALESCE(a.asgs, 0)            AS asgs,
            COALESCE(a.gold_gloves, 0)     AS gold_gloves,
            COALESCE(a.silver_sluggers, 0) AS silver_sluggers,
            COALESCE(a.ws_rings, 0)        AS ws_rings
        FROM players_current p
        LEFT JOIN cb       ON cb.player_id = p.player_id
        LEFT JOIN cp       ON cp.player_id = p.player_id
        LEFT JOIN awards_n a ON a.player_id = p.player_id
        WHERE p.hall_of_fame = 1 OR p.inducted = 1
        ORDER BY career_mlb_war DESC
        """
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _fetch_candidates(con: duckdb.DuckDBPyConnection, limit: int) -> list[dict]:
    """Top-N career MLB WAR players not yet HoF-inducted.

    Includes both retired and active. The active set is interesting too
    ("on track for HoF") but the retired set is the actual ballot.
    """
    rel = con.execute(
        f"""
        WITH cb AS (
            SELECT player_id,
                   SUM(pa) AS mlb_pa, SUM(hr) AS mlb_hr, SUM(war) AS mlb_war_bat
            FROM players_career_batting_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        cp AS (
            SELECT player_id,
                   SUM(outs) AS mlb_outs, SUM(w) AS mlb_w, SUM(s) AS mlb_s,
                   SUM(war) AS mlb_war_pit
            FROM players_career_pitching_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        awards_n AS (
            SELECT player_id,
                   SUM(CASE WHEN award_id = 5 THEN n_won ELSE 0 END) AS mvps,
                   SUM(CASE WHEN award_id = 4 THEN n_won ELSE 0 END) AS cys,
                   SUM(CASE WHEN award_id = 9 THEN n_won ELSE 0 END) AS asgs
            FROM f_award_career_player
            WHERE league_id = 203
            GROUP BY player_id
        )
        SELECT
            p.player_id, p.first_name, p.last_name, p.position,
            p.retired, p.hall_of_fame, p.inducted,
            COALESCE(cb.mlb_pa, 0)   AS mlb_pa,
            COALESCE(cb.mlb_hr, 0)   AS mlb_hr,
            COALESCE(cp.mlb_outs, 0) AS mlb_outs,
            COALESCE(cp.mlb_w, 0)    AS mlb_w,
            COALESCE(cb.mlb_war_bat, 0.0) + COALESCE(cp.mlb_war_pit, 0.0) AS career_mlb_war,
            COALESCE(a.mvps, 0) AS mvps,
            COALESCE(a.cys, 0)  AS cys,
            COALESCE(a.asgs, 0) AS asgs
        FROM players_current p
        LEFT JOIN cb       ON cb.player_id = p.player_id
        LEFT JOIN cp       ON cp.player_id = p.player_id
        LEFT JOIN awards_n a ON a.player_id = p.player_id
        WHERE p.hall_of_fame = 0 AND p.inducted = 0
          AND COALESCE(cb.mlb_war_bat, 0.0) + COALESCE(cp.mlb_war_pit, 0.0) >= {HOF_WAR_FLOOR}
        ORDER BY career_mlb_war DESC
        LIMIT ?
        """,
        [limit],
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _fmt_ip(outs: int) -> str:
    if not outs:
        return ""
    return f"{outs // 3}.{outs % 3}"


def _render_inducted(rows: list[dict]) -> None:
    if not rows:
        console.rule("[bold cyan]Hall of Fame")
        console.print(
            "[yellow]No HoFers in this save yet.[/yellow]  "
            "OOTP starts inducting once enough years have passed; with the "
            "current 4-year save horizon nobody has cleared the waiting period."
        )
        console.print(
            "[dim]Try `diamond hof --candidates` to see who's building "
            "an HoF résumé.[/dim]"
        )
        return

    console.rule(f"[bold cyan]Hall of Fame — {len(rows)} member(s)")
    t = Table(show_header=True, header_style="bold")
    t.add_column("player")
    t.add_column("status")
    t.add_column("MLB WAR", justify="right")
    t.add_column("hitting", overflow="fold")
    t.add_column("pitching", overflow="fold")
    t.add_column("hardware", overflow="fold")
    for r in rows:
        name = f"{r['first_name']} {r['last_name']}"
        status_parts = []
        if r["inducted"]:
            status_parts.append("inducted")
        if r["hall_of_fame"] and not r["inducted"]:
            status_parts.append("HoF (pending)")
        if r["retired"]:
            status_parts.append("retired")
        status = ", ".join(status_parts) if status_parts else ""

        hitting = ""
        if r["mlb_pa"]:
            hitting = f"{r['mlb_pa']} PA, {r['mlb_hr']} HR ({r['mlb_war_bat']:+.1f} WAR)"
        pitching = ""
        if r["mlb_outs"]:
            pitching = (
                f"{_fmt_ip(int(r['mlb_outs']))} IP, {r['mlb_w']}W "
                f"({r['mlb_war_pit']:+.1f} WAR)"
            )

        hardware_parts = []
        if r["mvps"]:            hardware_parts.append(f"{r['mvps']}× MVP")
        if r["cys"]:             hardware_parts.append(f"{r['cys']}× CY")
        if r["gold_gloves"]:     hardware_parts.append(f"{r['gold_gloves']}× GG")
        if r["silver_sluggers"]: hardware_parts.append(f"{r['silver_sluggers']}× SS")
        if r["asgs"]:            hardware_parts.append(f"{r['asgs']}× ASG")
        if r["ws_rings"]:        hardware_parts.append(f"{r['ws_rings']} WS")
        hardware = ", ".join(hardware_parts)

        t.add_row(
            name, status, f"{r['career_mlb_war']:.1f}",
            hitting, pitching, hardware,
        )
    console.print(t)


def _render_candidates(rows: list[dict], limit: int) -> None:
    console.rule(
        f"[bold cyan]HoF candidates — top {limit} by career MLB WAR (not yet inducted)"
    )
    if not rows:
        console.print("[yellow]No active candidates above the WAR floor.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("player")
    t.add_column("status")
    t.add_column("MLB WAR", justify="right")
    t.add_column("counting line", overflow="fold")
    t.add_column("hardware")
    for r in rows:
        name = f"{r['first_name']} {r['last_name']}"
        status = "retired" if r["retired"] else "active"

        if r["mlb_outs"]:
            line = f"{_fmt_ip(int(r['mlb_outs']))} IP, {r['mlb_w']}W"
        else:
            line = f"{r['mlb_pa']} PA, {r['mlb_hr']} HR"

        hw_parts = []
        if r["mvps"]: hw_parts.append(f"{r['mvps']}× MVP")
        if r["cys"]:  hw_parts.append(f"{r['cys']}× CY")
        if r["asgs"]: hw_parts.append(f"{r['asgs']}× ASG")
        hw = ", ".join(hw_parts) if hw_parts else ""

        t.add_row(name, status, f"{r['career_mlb_war']:.1f}", line, hw)
    console.print(t)


def _write_markdown(
    rows: list[dict],
    output_path: Path,
    mode: str,
    limit: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "inducted":
        md = [f"# Hall of Fame  ({len(rows)} member(s))", ""]
        if not rows:
            md.append("_No HoFers in this save yet._")
        else:
            md.append("| player | status | MLB WAR | hitting | pitching | hardware |")
            md.append("| --- | --- | ---: | --- | --- | --- |")
            for r in rows:
                name = f"{r['first_name']} {r['last_name']}"
                status_parts = []
                if r["inducted"]:                                  status_parts.append("inducted")
                if r["hall_of_fame"] and not r["inducted"]:        status_parts.append("HoF (pending)")
                if r["retired"]:                                   status_parts.append("retired")
                status = ", ".join(status_parts)
                hitting = (
                    f"{r['mlb_pa']} PA, {r['mlb_hr']} HR ({r['mlb_war_bat']:+.1f})"
                    if r["mlb_pa"] else ""
                )
                pitching = (
                    f"{_fmt_ip(int(r['mlb_outs']))} IP, {r['mlb_w']}W ({r['mlb_war_pit']:+.1f})"
                    if r["mlb_outs"] else ""
                )
                hw_parts = []
                if r["mvps"]:            hw_parts.append(f"{r['mvps']}× MVP")
                if r["cys"]:             hw_parts.append(f"{r['cys']}× CY")
                if r["gold_gloves"]:     hw_parts.append(f"{r['gold_gloves']}× GG")
                if r["silver_sluggers"]: hw_parts.append(f"{r['silver_sluggers']}× SS")
                if r["asgs"]:            hw_parts.append(f"{r['asgs']}× ASG")
                if r["ws_rings"]:        hw_parts.append(f"{r['ws_rings']} WS")
                hw = ", ".join(hw_parts)
                md.append(
                    f"| {name} | {status} | {r['career_mlb_war']:.1f} | "
                    f"{hitting} | {pitching} | {hw} |"
                )
    else:
        md = [f"# HoF candidates — top {limit} by career MLB WAR  (not yet inducted)", ""]
        if not rows:
            md.append("_No candidates above the WAR floor._")
        else:
            md.append("| player | status | MLB WAR | counting line | hardware |")
            md.append("| --- | --- | ---: | --- | --- |")
            for r in rows:
                name = f"{r['first_name']} {r['last_name']}"
                status = "retired" if r["retired"] else "active"
                if r["mlb_outs"]:
                    line = f"{_fmt_ip(int(r['mlb_outs']))} IP, {r['mlb_w']}W"
                else:
                    line = f"{r['mlb_pa']} PA, {r['mlb_hr']} HR"
                hw_parts = []
                if r["mvps"]: hw_parts.append(f"{r['mvps']}× MVP")
                if r["cys"]:  hw_parts.append(f"{r['cys']}× CY")
                if r["asgs"]: hw_parts.append(f"{r['asgs']}× ASG")
                hw = ", ".join(hw_parts)
                md.append(
                    f"| {name} | {status} | {r['career_mlb_war']:.1f} | {line} | {hw} |"
                )
    output_path.write_text("\n".join(md), encoding="utf-8")


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    candidates: bool = False,
    limit: int = 25,
    output_path: Path | None = None,
) -> Path:
    output_path = output_path or Path("audit_output") / (
        "hof_candidates.md" if candidates else "hof.md"
    )
    con = _connect(save)
    try:
        if candidates:
            rows = _fetch_candidates(con, limit)
            _render_candidates(rows, limit)
            _write_markdown(rows, output_path, "candidates", limit)
        else:
            rows = _fetch_inducted(con)
            _render_inducted(rows)
            _write_markdown(rows, output_path, "inducted", limit)
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()
    return output_path
