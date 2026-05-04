"""Hall of Fame tracker — `diamond hof` CLI.

Two HoF sources:

  - **Save HoF**: `players_current.hall_of_fame` / `players_current.inducted`
    booleans, populated by OOTP as players retire and clear the waiting
    period. Empty in fresh saves until ~5 years of sim have passed.
  - **Lahman HoF**: real-life Cooperstown inductees (1936–save_start-1)
    from `history_lahman_hof`, voted in by BBWAA / Veterans Committee /
    Negro Leagues / Old Timers. ~340 inductees.

Modes:
  - `diamond hof`                    → save HoFers + Lahman inductees,
                                       both with stats + hardware
  - `diamond hof --era save`         → save HoFers only (currently empty)
  - `diamond hof --era lahman`       → real Cooperstown only
  - `diamond hof --candidates`       → top career-WAR players (in OOTP
                                       save) not yet inducted — shortlist
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


def _fetch_lahman_inducted(con: duckdb.DuckDBPyConnection, limit: int) -> list[dict]:
    """Real Cooperstown inductees from Lahman, with career stats joined.

    Lahman HoF tracks every ballot vote — we filter to `inducted = 'Y'`
    and group by (playerID, category) to get one row per inducted person
    (a few players are inducted as both Player and Manager — rare).
    """
    rel = con.execute(
        f"""
        WITH inducted AS (
            SELECT playerID,
                   ANY_VALUE(yearid) AS year_inducted,
                   ANY_VALUE(votedBy) AS voted_by,
                   ANY_VALUE(category) AS category
            FROM history_lahman_hof
            WHERE inducted = 'Y'
            GROUP BY playerID
        ),
        cb AS (
            SELECT playerID,
                   SUM(AB) AS ab, SUM(H) AS h, SUM(HR) AS hr, SUM(RBI) AS rbi
            FROM history_lahman_batting
            WHERE lgID IN ('AL', 'NL')
            GROUP BY playerID
        ),
        cp AS (
            SELECT playerID,
                   SUM(W) AS w, SUM(SO) AS so, SUM(SV) AS sv,
                   SUM(IPouts) AS ipouts
            FROM history_lahman_pitching
            WHERE lgID IN ('AL', 'NL')
            GROUP BY playerID
        )
        SELECT
            i.playerID, i.year_inducted, i.voted_by, i.category,
            p.nameFirst || ' ' || p.nameLast AS name,
            COALESCE(cb.ab, 0)  AS ab,
            COALESCE(cb.h, 0)   AS h,
            COALESCE(cb.hr, 0)  AS hr,
            COALESCE(cb.rbi, 0) AS rbi,
            COALESCE(cp.w, 0)   AS w,
            COALESCE(cp.so, 0)  AS so,
            COALESCE(cp.sv, 0)  AS sv,
            COALESCE(cp.ipouts, 0) AS ipouts
        FROM inducted i
        LEFT JOIN history_lahman_people p ON p.playerID = i.playerID
        LEFT JOIN cb ON cb.playerID = i.playerID
        LEFT JOIN cp ON cp.playerID = i.playerID
        ORDER BY i.year_inducted DESC, name
        LIMIT {limit}
        """
    )
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


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


def _render_lahman_inducted(rows: list[dict]) -> None:
    console.rule(f"[bold cyan]Real-life Cooperstown — {len(rows)} most recent inductees")
    if not rows:
        console.print("[yellow]No Lahman HoF data loaded — run `diamond fetch-history`.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("year", justify="right")
    t.add_column("name")
    t.add_column("category")
    t.add_column("voted by")
    t.add_column("hitting", overflow="fold")
    t.add_column("pitching", overflow="fold")
    for r in rows:
        hitting = ""
        if r["ab"] and int(r["ab"]) > 0:
            hitting = f"{int(r['h'])} H, {int(r['hr'])} HR, {int(r['rbi'])} RBI"
        pitching = ""
        if r["ipouts"] and int(r["ipouts"]) > 0:
            ipouts = int(r["ipouts"])
            ip = f"{ipouts // 3}.{ipouts % 3}"
            pitching = f"{ip} IP, {int(r['w'])}W, {int(r['so'])}K, {int(r['sv'])}S"
        t.add_row(
            str(r["year_inducted"]), r["name"] or "—",
            r["category"] or "", r["voted_by"] or "",
            hitting, pitching,
        )
    console.print(t)


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    candidates: bool = False,
    era: str = "all",
    limit: int = 25,
    output_path: Path | None = None,
) -> Path:
    """Render HoF view (default) or candidate shortlist (--candidates).

    Args:
        era: 'all' (save + lahman), 'save' (OOTP only), 'lahman' (real Cooperstown).
             Only affects the default mode; `--candidates` is always save-side.
    """
    if era not in ("all", "save", "lahman"):
        raise ValueError(f"era must be 'all', 'save', or 'lahman', got {era!r}")
    output_path = output_path or Path("audit_output") / (
        "hof_candidates.md" if candidates else "hof.md"
    )
    con = _connect(save)
    try:
        if candidates:
            rows = _fetch_candidates(con, limit)
            _render_candidates(rows, limit)
            _write_markdown(rows, output_path, "candidates", limit)
            console.print(f"\n[green]Report written:[/green] {output_path}")
            return output_path

        # Default mode — render save HoF and/or Lahman HoF per era flag.
        save_rows = _fetch_inducted(con) if era in ("all", "save") else []
        if era in ("all", "save"):
            _render_inducted(save_rows)
        lahman_present = bool(con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'history_lahman_hof'
        """).fetchone()[0])
        lahman_rows: list[dict] = []
        if era in ("all", "lahman") and lahman_present:
            lahman_rows = _fetch_lahman_inducted(con, limit)
            _render_lahman_inducted(lahman_rows)

        # Markdown — combined output
        md: list[str] = []
        if era in ("all", "save"):
            md.append(f"# Hall of Fame — save  ({len(save_rows)} member(s))")
            md.append("")
            if not save_rows:
                md.append("_No HoFers in this save yet._")
            else:
                md.append("| player | status | MLB WAR |")
                md.append("| --- | --- | ---: |")
                for r in save_rows:
                    name = f"{r['first_name']} {r['last_name']}"
                    status = "inducted" if r["inducted"] else "HoF (pending)"
                    md.append(f"| {name} | {status} | {r['career_mlb_war']:.1f} |")
            md.append("")
        if era in ("all", "lahman") and lahman_present:
            md.append(f"# Real-life Cooperstown — {len(lahman_rows)} recent inductees")
            md.append("")
            md.append("| year | name | category | voted by | hitting | pitching |")
            md.append("| ---: | --- | --- | --- | --- | --- |")
            for r in lahman_rows:
                hitting = (
                    f"{int(r['h'])} H, {int(r['hr'])} HR, {int(r['rbi'])} RBI"
                    if int(r['ab'] or 0) > 0 else ""
                )
                if int(r["ipouts"] or 0) > 0:
                    ipouts = int(r["ipouts"])
                    pitching = f"{ipouts // 3}.{ipouts % 3} IP, {int(r['w'])}W"
                else:
                    pitching = ""
                md.append(
                    f"| {r['year_inducted']} | {r['name'] or ''} | "
                    f"{r['category'] or ''} | {r['voted_by'] or ''} | "
                    f"{hitting} | {pitching} |"
                )
            md.append("")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(md), encoding="utf-8")
        console.print(f"\n[green]Report written:[/green] {output_path}")
    finally:
        con.close()
    return output_path
