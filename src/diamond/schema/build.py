"""Warehouse build orchestrator.

Currently exposes:
  - init_admin_tables(con)             — create _diamond_ingests if missing
  - record_ingest_start / _done        — admin-table bookkeeping
  - dump_name_to_date(name)            — 'dump_2029_11' → date(2029, 11, 1)
  - build_l0(con, save, dump_name)     — ingest one dump's CSVs into l0_*

Future phases will add build_l1 / build_l2 here.

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
