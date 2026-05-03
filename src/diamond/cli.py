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

from diamond.audit import coverage as coverage_mod
from diamond.audit import decode as decode_mod
from diamond.audit import reconcile as reconcile_mod

app = typer.Typer(help="OOTP 27 monthly-dump warehouse and analysis app", no_args_is_help=True)


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
) -> None:
    """Reconcile import_export files against derivations from monthly dump CSVs."""
    reconcile_mod.run(dump=dump, output_path=output)


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


if __name__ == "__main__":
    app()
