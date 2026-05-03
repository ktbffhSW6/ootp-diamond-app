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
from diamond.schema import build_warehouse, open_warehouse_db, rebuild_l1_l2
from rich.console import Console

app = typer.Typer(help="OOTP 27 monthly-dump warehouse and analysis app", no_args_is_help=True)
_console = Console()


@app.callback()
def _root() -> None:
    """Diamond CLI."""


@app.command()
def decode(
    year: int = typer.Option(2029, help="Season year to audit"),
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
    output: Path = typer.Option(
        Path("audit_output/coverage_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Profile dump CSVs that support feature views (standings, leaders, awards, etc.)."""
    coverage_mod.run(dump=dump, output_path=output)


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
def advanced(
    year: int = typer.Option(2029, help="Season year"),
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
