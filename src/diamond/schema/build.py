"""Warehouse build orchestrator.

Public entry points:

  Per-layer (called individually by the smoke test):
    init_admin_tables(con)             — create _diamond_ingests if missing
    record_ingest_start / _done        — admin-table bookkeeping
    dump_name_to_date(name)            — 'dump_2029_11' → date(2029, 11, 1)
    build_l0(con, save, dump_name)     — ingest one dump's CSVs into l0_*

  High-level (called by the `diamond ingest` CLI):
    open_warehouse_db(save)            — open <save>/diamond/diamond.duckdb (D2)
    ingest_dump(con, save, name, ...)  — single-dump L0 ingest with skip-if-success
    rebuild_l1_l2(con, save, ...)      — full L1+L2 rebuild (cheap; ~30s)
    build_warehouse(con, save, ...)    — full pipeline orchestrator

The L0 build is dynamic CTAS / INSERT — DuckDB infers types from the CSVs
via `read_csv_auto(sample_size=-1)`, which has been the working pattern
throughout the audit phase. We don't hand-write per-table L0 schemas:

  - First load: `CREATE TABLE l0_<x> AS SELECT *, dump_date, ingest_ts,
                 ROW_NUMBER() OVER () AS file_seq FROM read_csv_auto(...)`.
  - Subsequent loads: `DELETE FROM l0_<x> WHERE dump_date = ?` then
                       `INSERT INTO l0_<x> SELECT *, ...` from the new dump.

This means re-running `build_l0` for a previously-loaded dump is idempotent
(per OPEN-7 — the official idempotency contract is the `_diamond_ingests`
admin row + per-CSV checksum, but at the L0 mechanics level the
DELETE-then-INSERT pattern is already safe).

Assumption: CSV column shape is stable across dumps within a single save.
A new dump introducing a new column would fail the INSERT (column-count
mismatch). OOTP's CSV exports are stable across a save, so this is safe in
practice, but if it ever fires the fix is to DROP and rebuild L0 from
scratch — L0 is just provenance, all of which lives on disk in `dump/`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
from rich.console import Console

from diamond.config import SaveConfig
from diamond.schema.l0 import L0_CATALOG, L0Spec

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Admin table — _diamond_ingests
# ─────────────────────────────────────────────────────────────────────────────


# Per OPEN-7 (resolved 2026-05-05): one row per ingested dump, with timestamps,
# success/fail status, and a JSON blob recording row counts per L0 table for
# debugging. The `csv_checksum_blob` column is reserved for the per-CSV
# checksum work landing in item 4 (the `diamond ingest` CLI).
DIAMOND_INGESTS_DDL = """
CREATE TABLE IF NOT EXISTS _diamond_ingests (
    dump_date            DATE PRIMARY KEY,
    dump_name            VARCHAR NOT NULL,
    ingest_ts            TIMESTAMP NOT NULL,
    status               VARCHAR NOT NULL,        -- 'in_progress' | 'success' | 'failed'
    rows_per_table_json  VARCHAR,                 -- JSON {table_name: row_count}
    csv_checksum_blob    VARCHAR                  -- reserved for item 4
);
"""


def init_admin_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create the warehouse-machinery tables if they don't exist."""
    con.execute(DIAMOND_INGESTS_DDL)


def record_ingest_start(
    con: duckdb.DuckDBPyConnection,
    dump_name: str,
    dump_date: date,
) -> None:
    """Mark an ingest as in-progress. Idempotent on dump_date."""
    con.execute(
        """
        INSERT INTO _diamond_ingests (dump_date, dump_name, ingest_ts, status)
        VALUES (?, ?, NOW(), 'in_progress')
        ON CONFLICT (dump_date) DO UPDATE SET
            dump_name  = excluded.dump_name,
            ingest_ts  = NOW(),
            status     = 'in_progress'
        """,
        [dump_date, dump_name],
    )


def record_ingest_done(
    con: duckdb.DuckDBPyConnection,
    dump_date: date,
    rows_per_table: dict[str, int],
    *,
    success: bool = True,
) -> None:
    """Finalize an ingest with status + per-table row counts."""
    con.execute(
        """
        UPDATE _diamond_ingests
        SET status = ?,
            rows_per_table_json = ?,
            ingest_ts = NOW()
        WHERE dump_date = ?
        """,
        ["success" if success else "failed", json.dumps(rows_per_table), dump_date],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dump-name parsing
# ─────────────────────────────────────────────────────────────────────────────


def dump_name_to_date(dump_name: str) -> date:
    """Convert ``dump_2029_11`` → ``date(2029, 11, 1)``.

    Dump folders are named `dump_YYYY_MM`. We use the 1st of the month as
    the canonical dump_date so it sorts naturally and uniquely identifies
    the dump.
    """
    parts = dump_name.split("_")
    if len(parts) != 3 or parts[0] != "dump":
        raise ValueError(
            f"Unexpected dump folder name: {dump_name!r} "
            f"(expected 'dump_YYYY_MM')"
        )
    try:
        year, month = int(parts[1]), int(parts[2])
    except ValueError as e:
        raise ValueError(f"Could not parse year/month from {dump_name!r}") from e
    if not (1 <= month <= 12):
        raise ValueError(f"Invalid month in {dump_name!r}: {month}")
    return date(year, month, 1)


# ─────────────────────────────────────────────────────────────────────────────
# L0 build
# ─────────────────────────────────────────────────────────────────────────────


def _csv_path(csv_dir: Path, spec: L0Spec) -> Path:
    return csv_dir / f"{spec.csv_name}.csv"


def _q(path: Path) -> str:
    """Quote a path for embedding inside a DuckDB SQL literal."""
    # DuckDB accepts forward slashes on Windows, and posix form avoids
    # backslash-escaping issues inside single-quoted SQL strings.
    return f"'{path.as_posix()}'"


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1",
        [table],
    ).fetchone()
    return row is not None


def _ingest_one_l0_table(
    con: duckdb.DuckDBPyConnection,
    spec: L0Spec,
    csv_path: Path,
    dump_date: date,
) -> int:
    """Idempotently load one CSV into its L0 table. Returns rows inserted."""
    table = spec.l0_table
    csv_lit = _q(csv_path)
    select_clause = f"""
        SELECT *,
            CAST('{dump_date.isoformat()}' AS DATE) AS dump_date,
            NOW()                                   AS ingest_ts,
            ROW_NUMBER() OVER ()                    AS file_seq
        FROM read_csv_auto({csv_lit}, sample_size=-1, ignore_errors=true)
    """
    if not _table_exists(con, table):
        con.execute(f"CREATE TABLE {table} AS {select_clause}")
    else:
        # DELETE-then-INSERT is the idempotency primitive for L0:
        # re-running the same dump replaces its rows cleanly.
        con.execute(f"DELETE FROM {table} WHERE dump_date = ?", [dump_date])
        con.execute(f"INSERT INTO {table} {select_clause}")
    n = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE dump_date = ?", [dump_date]
    ).fetchone()[0]
    return n


def already_ingested(
    con: duckdb.DuckDBPyConnection,
    dump_name: str,
) -> bool:
    """Return True if `_diamond_ingests` shows this dump as 'success'."""
    init_admin_tables(con)
    row = con.execute(
        "SELECT 1 FROM _diamond_ingests WHERE dump_name = ? AND status = 'success' LIMIT 1",
        [dump_name],
    ).fetchone()
    return row is not None


def build_l0(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    dump_name: str,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Ingest every CSV from one dump into the corresponding `l0_*` table.

    Returns: dict of `{l0_table_name: rows_inserted_for_this_dump}`.

    Idempotent: re-running for the same dump replaces its rows.
    Records status into `_diamond_ingests`.

    Missing CSVs are warned and skipped — earlier dumps may legitimately
    lack files that started appearing in later OOTP versions, and partial
    saves don't have every CSV.
    """
    init_admin_tables(con)
    dump_date = dump_name_to_date(dump_name)
    csv_dir = save.csv_dir(dump_name)
    if not csv_dir.exists():
        raise FileNotFoundError(f"CSV directory not found: {csv_dir}")

    record_ingest_start(con, dump_name, dump_date)
    rows_per_table: dict[str, int] = {}
    missing: list[str] = []
    try:
        for spec in L0_CATALOG:
            path = _csv_path(csv_dir, spec)
            if not path.exists():
                missing.append(spec.csv_name)
                if verbose:
                    console.print(
                        f"  [yellow]missing CSV (skipping):[/yellow] {spec.csv_name}.csv"
                    )
                continue
            n = _ingest_one_l0_table(con, spec, path, dump_date)
            rows_per_table[spec.l0_table] = n
            if verbose:
                console.print(
                    f"  [green]✓[/green] {spec.l0_table:<55} "
                    f"[dim]{n:>10,} rows[/dim]"
                )
    except Exception:
        record_ingest_done(con, dump_date, rows_per_table, success=False)
        raise
    else:
        record_ingest_done(con, dump_date, rows_per_table, success=True)
        if verbose and missing:
            console.print(
                f"\n[yellow]Note:[/yellow] {len(missing)} CSV(s) missing "
                f"from this dump (see above)."
            )
    return rows_per_table


# ─────────────────────────────────────────────────────────────────────────────
# High-level orchestration
# ─────────────────────────────────────────────────────────────────────────────


def open_warehouse_db(save: SaveConfig) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the per-save DuckDB at <save>/diamond/diamond.duckdb.

    Per Decision D2, each save gets its own warehouse DB alongside its
    `dump/` and `import_export/` folders. The `diamond/` subdirectory is
    created if missing.
    """
    db_dir = save.save_dir / "diamond"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "diamond.duckdb"
    return duckdb.connect(str(db_path))


def ingest_dump(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    dump_name: str,
    *,
    force: bool = False,
    verbose: bool = True,
) -> tuple[bool, dict[str, int]]:
    """Ingest a single dump's CSVs into L0.

    Returns (was_ingested, rows_per_table). If the dump is already 'success'
    in `_diamond_ingests` and `force=False`, returns (False, {}).

    Idempotent regardless: build_l0 itself uses DELETE-then-INSERT keyed on
    dump_date, so re-ingesting (even with --force) is safe.
    """
    if not force and already_ingested(con, dump_name):
        if verbose:
            console.print(
                f"[dim]Already ingested:[/dim] {dump_name} "
                f"[dim](use --force to override)[/dim]"
            )
        return False, {}
    rows = build_l0(con, save, dump_name, verbose=verbose)
    return True, rows


def rebuild_l1_l2(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    *,
    verbose: bool = True,
) -> dict[str, dict[str, int]]:
    """Drop-and-rebuild L1 (machinery + reference + event + snapshot) and L2.

    All builders are idempotent (CREATE OR REPLACE). Cheap enough to run
    after every L0 ingest — measured at ~30s for the full warehouse on
    "Building the Green Monster".

    Returns nested dict of `{layer: {table_name: row_count}}`.
    """
    # Late imports avoid pulling these into module-import time when the
    # schema package's other modules import build.py.
    from diamond.schema.l1_event import build_l1_event
    from diamond.schema.l1_machinery import build_l1_machinery
    from diamond.schema.l1_reference import build_l1_reference
    from diamond.schema.l1_snapshot import build_l1_snapshot
    from diamond.schema.l2 import build_l2

    out: dict[str, dict[str, int]] = {}
    if verbose:
        console.rule("L1 machinery")
    out["l1_machinery"] = build_l1_machinery(con, save, verbose=verbose)
    if verbose:
        console.rule("L1 reference")
    out["l1_reference"] = build_l1_reference(con, verbose=verbose)
    if verbose:
        console.rule("L1 events")
    out["l1_event"] = build_l1_event(con, verbose=verbose)
    if verbose:
        console.rule("L1 snapshots")
    out["l1_snapshot"] = build_l1_snapshot(con, save, verbose=verbose)
    if verbose:
        console.rule("L2 facts")
    out["l2"] = build_l2(con, verbose=verbose)
    return out


def build_warehouse(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    *,
    dumps: list[str] | None = None,
    force: bool = False,
    rebuild: bool = True,
    verbose: bool = True,
    quiet_per_dump: bool = False,
) -> dict:
    """Full ingest + rebuild orchestrator.

    Args:
        dumps: list of dump names to ingest. None means "all dumps in
               `<save>/dump/` in chronological order".
        force: re-ingest dumps already marked 'success'.
        rebuild: after L0 ingest(s), rebuild L1+L2. Set False to defer
                 the rebuild (e.g., during a multi-step pipeline).
        verbose: master verbose flag.
        quiet_per_dump: when ingesting many dumps, suppress the per-table
                       row-count rows; show one summary line per dump
                       instead. The L1+L2 rebuild remains verbose.

    Returns: dict with keys
        "ingested":   list of dump names actually ingested
        "skipped":    list of dump names skipped (already 'success')
        "l0_rows":    {dump_name: total_rows_inserted}
        "l1_l2":      output of rebuild_l1_l2 (or None if rebuild=False)
    """
    init_admin_tables(con)
    targets = dumps if dumps is not None else save.all_dump_names()

    ingested: list[str] = []
    skipped: list[str] = []
    l0_totals: dict[str, int] = {}

    for d in targets:
        per_dump_verbose = verbose and not quiet_per_dump
        if verbose and quiet_per_dump:
            console.print(f"[dim]→[/dim] {d}", end=" ")
        elif verbose:
            console.rule(f"L0 ingest: {d}")
        was_ingested, rows = ingest_dump(
            con, save, d, force=force, verbose=per_dump_verbose
        )
        if was_ingested:
            ingested.append(d)
            total = sum(rows.values())
            l0_totals[d] = total
            if verbose and quiet_per_dump:
                console.print(f"[green]✓[/green] {total:,} rows")
        else:
            skipped.append(d)
            if verbose and quiet_per_dump:
                console.print("[dim]skipped[/dim]")

    if verbose:
        console.print(
            f"\n[bold]L0 done.[/bold] Ingested {len(ingested)}, skipped "
            f"{len(skipped)} (already 'success')."
        )

    l1_l2 = None
    if rebuild and (ingested or force):
        l1_l2 = rebuild_l1_l2(con, save, verbose=verbose)
    elif rebuild and not ingested:
        if verbose:
            console.print(
                "[dim]No new dumps; skipping L1+L2 rebuild "
                "(use --force or --rebuild-only to force).[/dim]"
            )

    return {
        "ingested": ingested,
        "skipped": skipped,
        "l0_rows": l0_totals,
        "l1_l2": l1_l2,
    }
