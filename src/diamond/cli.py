"""Diamond CLI — entry point for audit, ingest, and analysis commands."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

# Force UTF-8 stdout/stderr on Windows so Rich can render box characters etc.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from diamond.audit import advanced as advanced_mod
from diamond.audit import coverage as coverage_mod
from diamond.audit import decode as decode_mod
from diamond.audit import decode_codes as decode_codes_mod
from diamond.audit import reconcile as reconcile_mod
from diamond.config import BUILDING_THE_GREEN_MONSTER
from diamond import awards as awards_mod
from diamond import draft as draft_mod
from diamond import hof as hof_mod
from diamond import records as records_mod
from diamond.schema import build_warehouse, open_warehouse_db, rebuild_l1_l2
from rich.console import Console

app = typer.Typer(help="OOTP 27 monthly-dump warehouse and analysis app", no_args_is_help=True)
_console = Console()


@app.callback()
def _root() -> None:
    """Diamond CLI."""


@app.command()
def decode(
    year: int | None = typer.Option(
        None,
        help="Season year to audit. Defaults to MAX(year) from the dump's career_bat.",
    ),
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/decoder_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Discover OOTP integer-code meanings (game_type, split_id, at-bat result)."""
    decode_mod.run(year=year, dump=dump, output_path=output)


@app.command()
def reconcile(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/reconciliation_report.md"),
        help="Markdown report output path",
    ),
    source: str = typer.Option(
        "csv",
        help=(
            "'csv' reads dump CSVs directly (audit-phase mode). 'warehouse' "
            "reads from <save>/diamond/diamond.duckdb — the post-ingest "
            "regression check per Decision D8."
        ),
    ),
) -> None:
    """Reconcile import_export files against derivations from monthly dump CSVs."""
    reconcile_mod.run(dump=dump, output_path=output, source=source)


@app.command()
def coverage(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    year: int | None = typer.Option(
        None,
        help="Season year for year-scoped probes. Defaults to MAX(year) from career_bat.",
    ),
    output: Path = typer.Option(
        Path("audit_output/coverage_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Profile dump CSVs that support feature views (standings, leaders, awards, etc.)."""
    coverage_mod.run(dump=dump, year=year, output_path=output)


@app.command("decode-codes")
def decode_codes(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/codes_decoder_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Decode the four pending codebooks (award_id, leader.category, streak_id, body_part)."""
    decode_codes_mod.run(dump=dump, output_path=output)


@app.command()
def ingest(
    dump: str | None = typer.Argument(
        None,
        help="Dump folder name (e.g., 'dump_2029_11'). Omit with --all or --rebuild-only.",
    ),
    all_dumps: bool = typer.Option(
        False, "--all", help="Ingest every dump in <save>/dump/ in chronological order."
    ),
    rebuild_only: bool = typer.Option(
        False,
        "--rebuild-only",
        help="Skip L0 ingest entirely; only rebuild L1+L2 from existing L0 data.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-ingest dumps already marked 'success' in _diamond_ingests.",
    ),
    no_rebuild: bool = typer.Option(
        False,
        "--no-rebuild",
        help="Stop after L0 ingest; skip the L1+L2 rebuild.",
    ),
) -> None:
    """Ingest OOTP dumps into the warehouse and rebuild L1+L2.

    Writes to <save>/diamond/diamond.duckdb (per Decision D2). The warehouse
    is layered:
      L0   raw landing — one dump's CSVs become 69 l0_* tables
      L1   conformed   — 12 reference + 35 event + 21 snapshot + 6 _current views
      L2   facts       — 8 analytical-grain tables (see docs/SCHEMA.md)

    Examples:
        diamond ingest dump_2029_11        # ingest one dump + rebuild L1+L2
        diamond ingest --all               # walk every dump folder in order
        diamond ingest --rebuild-only      # rebuild L1+L2 from current L0
        diamond ingest dump_2029_11 --force --no-rebuild   # L0 only, force re-ingest
    """
    save = BUILDING_THE_GREEN_MONSTER

    # Argument validation: exactly one of {dump, --all, --rebuild-only}
    modes = sum([dump is not None, all_dumps, rebuild_only])
    if modes != 1:
        _console.print(
            "[red]Specify exactly one of:[/red] a dump name, --all, or --rebuild-only."
        )
        raise typer.Exit(1)

    con = open_warehouse_db(save)
    db_path = save.save_dir / "diamond" / "diamond.duckdb"
    _console.print(f"[bold]Warehouse:[/bold] {db_path}\n")

    try:
        if rebuild_only:
            rebuild_l1_l2(con, save, verbose=True)
        else:
            dumps_arg = None if all_dumps else [dump]
            result = build_warehouse(
                con,
                save,
                dumps=dumps_arg,
                force=force,
                rebuild=not no_rebuild,
                verbose=True,
                quiet_per_dump=all_dumps,  # cleaner output for --all
            )
            _console.print(
                f"\n[bold]Summary:[/bold] {len(result['ingested'])} ingested, "
                f"{len(result['skipped'])} skipped."
            )
    finally:
        con.close()


@app.command()
def draft(
    year: int = typer.Argument(..., help="Draft year to analyze (e.g., 2026)."),
    team: int | None = typer.Option(
        None,
        help="Optional team_id to scope the report to a single org's class (e.g., 4 for Boston).",
    ),
    output: Path = typer.Option(
        None,
        help="Markdown report output path. Defaults to audit_output/draft_<year>.md.",
    ),
) -> None:
    """Show a draft class — pick by pick, with current status + MLB WAR.

    Reads from the L3 `f_draft_class` table (built by `diamond ingest`).
    Each player is bucketed into one of: mlb_star / mlb_regular /
    mlb_callup / in_draft_org / traded_away / released / retired.

    Examples:
        diamond draft 2026                # full class
        diamond draft 2026 --team 4       # Sox 2026 class only
    """
    draft_mod.run(year=year, team_id=team, output_path=output)


@app.command()
def records(
    scope: str = typer.Option(
        "career",
        help="'career' or 'season'.",
    ),
    discipline: str = typer.Option(
        "batting",
        help="'batting' or 'pitching'.",
    ),
    category: str | None = typer.Option(
        None,
        help="A single category to render (e.g., 'HR', 'WAR', 'IP'). "
        "Default: render every category for the scope+discipline.",
    ),
    limit: int = typer.Option(10, help="Top-N per category (max 25)."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/records_<scope>_<discipline>.md",
    ),
) -> None:
    """All-time MLB leaderboards (single-season + career) — counting stats.

    Reads from the L3 `f_record_player` table.

    Examples:
        diamond records                                  # career batting, all cats
        diamond records --scope season --category HR     # single-season HR top 10
        diamond records --discipline pitching --scope career --limit 25
    """
    records_mod.run(
        scope=scope, discipline=discipline,
        category=category, limit=limit, output_path=output,
    )


@app.command()
def awards(
    award: int | None = typer.Option(
        None,
        help="Award id to render (see diamond.constants.AwardId). "
        "5=MVP, 4=CY, 6=ROY, 7=GG, 11=SS, 9=ASG, 14=WS roster.",
    ),
    player: int | None = typer.Option(
        None,
        help="Player id to render — shows their full career awards.",
    ),
    team: int | None = typer.Option(
        None,
        help="Team id to render franchise totals (org-rolled-up via parent_team_id).",
    ),
    league: int = typer.Option(203, help="League id (default MLB=203)."),
    limit: int = typer.Option(15, help="Top-N players per award."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/awards.md",
    ),
) -> None:
    """Awards leaderboards — career totals per player, per franchise.

    Three modes (priority order):
      diamond awards --player <id>          # one player's full résumé
      diamond awards --team <id>            # franchise totals (org-rolled-up)
      diamond awards --award <id>           # top-N players for that award
      diamond awards                        # catalog: top-N for every award
    """
    awards_mod.run(
        award_id=award,
        player_id=player,
        team_id=team,
        league_id=league,
        limit=limit,
        output_path=output,
    )


@app.command()
def hof(
    candidates: bool = typer.Option(
        False, "--candidates",
        help="Show top-N career-WAR players who haven't been inducted yet.",
    ),
    limit: int = typer.Option(25, help="Top-N for --candidates mode."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/hof.md (or hof_candidates.md).",
    ),
) -> None:
    """Hall of Fame tracker — current inductees + future candidates.

    By default lists every HoF/inducted player with stats + hardware.
    With --candidates, ranks the top career-MLB-WAR players who haven't
    yet been inducted (rough HoF shortlist).
    """
    hof_mod.run(candidates=candidates, limit=limit, output_path=output)


@app.command()
def advanced(
    year: int | None = typer.Option(
        None,
        help="Season year. Defaults to MAX(year) from the dump's career_bat.",
    ),
    league_id: int = typer.Option(203, help="League id (default MLB=203)"),
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/advanced_stats_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Compute modern advanced stats (Tiers 1-5) from at-bat + dump data."""
    advanced_mod.run(year=year, league_id=league_id, dump=dump, output_path=output)


if __name__ == "__main__":
    app()
