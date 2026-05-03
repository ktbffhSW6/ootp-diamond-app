"""Smoke test for L0 ingest.

Builds L0 from the latest dump in `BUILDING_THE_GREEN_MONSTER` into an
in-memory DuckDB, then prints sanity stats:
  - total rows ingested
  - row counts for the 5 largest L0 tables
  - the `_diamond_ingests` row for this dump
  - a sanity check on `file_seq` for `l0_players_at_bat_batting_stats`
    (must be 1..N within the dump, with no gaps)

Run: python scripts/smoke_l0.py
"""

from __future__ import annotations

import sys

# Force UTF-8 stdout/stderr on Windows so Rich box characters render — same
# pattern as src/diamond/cli.py.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import duckdb
from rich.console import Console
from rich.table import Table

from diamond.config import BUILDING_THE_GREEN_MONSTER
from diamond.schema import L0_CATALOG, build_l0


def main() -> int:
    console = Console()
    save = BUILDING_THE_GREEN_MONSTER
    dump = save.latest_dump_name()

    console.rule(f"L0 smoke test — {save.save_name} / {dump}")

    con = duckdb.connect()
    rows_per_table = build_l0(con, save, dump, verbose=True)

    total_rows = sum(rows_per_table.values())
    tables_built = len(rows_per_table)
    console.print(
        f"\n[bold green]Done.[/bold green] {tables_built} L0 tables, "
        f"{total_rows:,} rows total."
    )

    # Top 5 tables by row count
    top5 = sorted(rows_per_table.items(), key=lambda kv: -kv[1])[:5]
    t = Table(title="Largest L0 tables")
    t.add_column("table")
    t.add_column("rows", justify="right")
    for name, n in top5:
        t.add_row(name, f"{n:,}")
    console.print(t)

    # Admin-table check
    row = con.execute(
        """
        SELECT dump_date, dump_name, status,
               LENGTH(rows_per_table_json) AS json_len
        FROM _diamond_ingests
        """
    ).fetchall()
    console.print(f"\n_diamond_ingests rows: {row}")

    # file_seq sanity check on the at-bat log (load-bearing per OPEN-4)
    ab_check = con.execute(
        """
        SELECT MIN(file_seq)        AS min_seq,
               MAX(file_seq)        AS max_seq,
               COUNT(DISTINCT file_seq) AS distinct_seqs,
               COUNT(*)             AS rows
        FROM l0_players_at_bat_batting_stats
        """
    ).fetchone()
    console.print(
        f"\nl0_players_at_bat_batting_stats file_seq: "
        f"min={ab_check[0]}, max={ab_check[1]}, distinct={ab_check[2]:,}, "
        f"rows={ab_check[3]:,}"
    )
    if ab_check[0] != 1 or ab_check[1] != ab_check[3] or ab_check[2] != ab_check[3]:
        console.print(
            "[red]FAIL:[/red] file_seq is not 1..N with no gaps."
        )
        return 1
    console.print("[green]✓[/green] file_seq is 1..N, no gaps")

    # Idempotency check: rebuild and confirm row counts unchanged
    console.rule("Idempotency check — rebuilding the same dump")
    rows_per_table_2 = build_l0(con, save, dump, verbose=False)
    if rows_per_table == rows_per_table_2:
        console.print("[green]✓[/green] re-ingest produced identical row counts")
    else:
        deltas = {
            k: (rows_per_table.get(k, 0), rows_per_table_2.get(k, 0))
            for k in set(rows_per_table) | set(rows_per_table_2)
            if rows_per_table.get(k) != rows_per_table_2.get(k)
        }
        console.print(f"[red]FAIL:[/red] row counts changed across re-ingest: {deltas}")
        return 1

    # Catalog completeness sanity
    if tables_built < len(L0_CATALOG):
        console.print(
            f"\n[yellow]Note:[/yellow] only {tables_built}/{len(L0_CATALOG)} "
            f"catalog tables were ingested for this dump (others had missing CSVs)."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
