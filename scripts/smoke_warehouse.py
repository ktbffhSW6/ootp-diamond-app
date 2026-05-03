"""End-to-end warehouse smoke test.

Builds the warehouse layer-by-layer in an in-memory DuckDB and asserts
the core invariants of each phase. As phases land, this script grows
incrementally rather than spawning new files.

Phases covered today:
  - Phase A (L0):           dynamic CTAS / DELETE-INSERT, idempotent re-ingest
  - Phase B (L1 reference): replace-latest with PK enforcement

Run: python scripts/smoke_warehouse.py
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
from diamond.schema import (
    ALL_EVENT_SPECS,
    L0_CATALOG,
    L1_REFERENCE_TABLES,
    build_l0,
    build_l1_event,
    build_l1_machinery,
    build_l1_reference,
)


def smoke_l0(con: duckdb.DuckDBPyConnection, save, dump: str, console: Console) -> bool:
    """Phase A invariants. Returns True on pass."""
    console.rule(f"Phase A — L0 ingest from {dump}")
    rows_per_table = build_l0(con, save, dump, verbose=True)

    total_rows = sum(rows_per_table.values())
    tables_built = len(rows_per_table)
    console.print(
        f"\n[bold green]L0 done.[/bold green] {tables_built} tables, "
        f"{total_rows:,} rows."
    )

    # Top 5 by size
    top5 = sorted(rows_per_table.items(), key=lambda kv: -kv[1])[:5]
    t = Table(title="Largest L0 tables")
    t.add_column("table")
    t.add_column("rows", justify="right")
    for name, n in top5:
        t.add_row(name, f"{n:,}")
    console.print(t)

    # _diamond_ingests check
    admin_rows = con.execute(
        "SELECT dump_date, dump_name, status FROM _diamond_ingests"
    ).fetchall()
    console.print(f"_diamond_ingests: {admin_rows}")

    # file_seq sanity on the at-bat log (load-bearing per OPEN-4)
    ab = con.execute("""
        SELECT MIN(file_seq), MAX(file_seq),
               COUNT(DISTINCT file_seq), COUNT(*)
        FROM l0_players_at_bat_batting_stats
    """).fetchone()
    if ab[0] != 1 or ab[1] != ab[3] or ab[2] != ab[3]:
        console.print("[red]FAIL:[/red] file_seq has gaps or wrong range")
        return False
    console.print(
        f"[green]✓[/green] l0_players_at_bat_batting_stats.file_seq = 1..{ab[1]:,}, no gaps"
    )

    # Idempotency
    rows_per_table_2 = build_l0(con, save, dump, verbose=False)
    if rows_per_table != rows_per_table_2:
        console.print("[red]FAIL:[/red] row counts changed across re-ingest")
        return False
    console.print("[green]✓[/green] re-ingest is idempotent")

    if tables_built < len(L0_CATALOG):
        console.print(
            f"[yellow]Note:[/yellow] only {tables_built}/{len(L0_CATALOG)} "
            f"L0 tables ingested (others had missing CSVs)."
        )
    return True


def smoke_l1_reference(con: duckdb.DuckDBPyConnection, console: Console) -> bool:
    """Phase B invariants. Returns True on pass."""
    console.rule("Phase B — L1 reference tables")
    rows_per_table = build_l1_reference(con, verbose=True)

    # Each L1 row count must equal the latest dump's L0 row count for that source
    console.print()
    for spec in L1_REFERENCE_TABLES:
        l1_n = rows_per_table[spec.l1_table]
        l0_n = con.execute(
            f"SELECT COUNT(*) FROM {spec.source_l0} "
            f"WHERE dump_date = (SELECT MAX(dump_date) FROM {spec.source_l0})"
        ).fetchone()[0]
        if l1_n != l0_n:
            console.print(
                f"[red]FAIL:[/red] {spec.l1_table} {l1_n} ≠ "
                f"{spec.source_l0} latest-dump {l0_n}"
            )
            return False
    console.print("[green]✓[/green] L1 row counts match latest L0 dump for all 12 tables")

    # Admin columns must NOT have leaked into L1
    leak = []
    for spec in L1_REFERENCE_TABLES:
        cols = {r[0] for r in con.execute(f"DESCRIBE {spec.l1_table}").fetchall()}
        for forbidden in ("dump_date", "ingest_ts", "file_seq"):
            if forbidden in cols:
                leak.append((spec.l1_table, forbidden))
    if leak:
        console.print(f"[red]FAIL:[/red] admin columns leaked into L1: {leak}")
        return False
    console.print("[green]✓[/green] no admin columns leaked into L1 (EXCLUDE clause works)")

    # PK enforcement spot-check: try to insert a duplicate continent and expect rejection
    sample_id = con.execute(
        "SELECT continent_id FROM continents LIMIT 1"
    ).fetchone()[0]
    pk_rejected = False
    try:
        con.execute(
            f"INSERT INTO continents (continent_id, name) VALUES ({sample_id}, 'DUP_TEST')"
        )
    except duckdb.ConstraintException:
        pk_rejected = True
    if not pk_rejected:
        console.print("[red]FAIL:[/red] PK constraint did not reject duplicate insert")
        return False
    console.print("[green]✓[/green] PK constraint enforces uniqueness (smoke-tested on `continents`)")

    # Idempotency: rebuild and confirm
    rows_per_table_2 = build_l1_reference(con, verbose=False)
    if rows_per_table != rows_per_table_2:
        console.print("[red]FAIL:[/red] L1 reference rebuild changed row counts")
        return False
    console.print("[green]✓[/green] L1 reference rebuild is idempotent")

    return True


def smoke_l1_machinery(con: duckdb.DuckDBPyConnection, save, console: Console) -> bool:
    """Phase C prereq: _scoped_teams and _scoped_players."""
    console.rule("Phase C prereq — L1 machinery (scope sets)")
    rows = build_l1_machinery(con, save, verbose=True)

    # Scoped teams should equal the count of teams whose league_id is in scope
    expected_teams = con.execute(
        f"SELECT COUNT(DISTINCT team_id) FROM l0_teams "
        f"WHERE league_id IN ({', '.join(str(i) for i in save.league_ids)})"
    ).fetchone()[0]
    if rows["_scoped_teams"] != expected_teams:
        console.print(
            f"[red]FAIL:[/red] _scoped_teams = {rows['_scoped_teams']} "
            f"≠ expected {expected_teams}"
        )
        return False
    console.print(
        f"[green]✓[/green] _scoped_teams matches expected count from l0_teams"
    )
    return True


def smoke_l1_event(con: duckdb.DuckDBPyConnection, console: Console) -> bool:
    """Phase C invariants. Returns True on pass."""
    console.rule("Phase C — L1 event tables")
    rows = build_l1_event(con, verbose=True)

    expected_total = len(ALL_EVENT_SPECS) + 2  # + at_bats_event + streak_event
    if len(rows) != expected_total:
        console.print(
            f"[red]FAIL:[/red] built {len(rows)} event tables, "
            f"expected {expected_total}"
        )
        return False
    console.print(
        f"\n[green]✓[/green] all {expected_total} event tables built"
    )

    # Every event table should have at least one row (sanity — none should be empty)
    empty = [(name, n) for name, n in rows.items() if n == 0]
    if empty:
        console.print(f"[yellow]Warning:[/yellow] empty L1 event tables: {empty}")

    # Spot-check D3/D4 scope filter on at_bats_event:
    # every player_id in at_bats_event must be in _scoped_players.
    leak = con.execute("""
        SELECT COUNT(*) FROM at_bats_event
        WHERE player_id NOT IN (SELECT player_id FROM _scoped_players)
    """).fetchone()[0]
    if leak > 0:
        console.print(
            f"[red]FAIL:[/red] at_bats_event has {leak} rows with "
            f"player_id NOT in _scoped_players"
        )
        return False
    console.print("[green]✓[/green] at_bats_event obeys _scoped_players filter")

    # Spot-check pa_in_game_seq sanity on at_bats_event
    bad_seq = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT game_id, player_id, MIN(pa_in_game_seq) AS lo,
                   MAX(pa_in_game_seq) AS hi, COUNT(*) AS n
            FROM at_bats_event
            GROUP BY game_id, player_id
        ) WHERE lo != 1 OR hi != n
    """).fetchone()[0]
    if bad_seq > 0:
        console.print(
            f"[red]FAIL:[/red] at_bats_event has {bad_seq} (game, batter) "
            f"groups where pa_in_game_seq is not 1..N"
        )
        return False
    console.print(
        "[green]✓[/green] at_bats_event.pa_in_game_seq is 1..N within every (game, batter)"
    )

    # PK enforcement spot-check on streak_event (the COALESCE PK)
    pk_rejected = False
    sample = con.execute(
        "SELECT player_id, league_id, streak_id, started, ended_or_max "
        "FROM streak_event LIMIT 1"
    ).fetchone()
    if sample is not None:
        try:
            con.execute(
                "INSERT INTO streak_event (player_id, league_id, streak_id, "
                "started, ended_or_max, value, has_ended, ended) "
                "VALUES (?, ?, ?, ?, ?, 99, 1, ?)",
                [sample[0], sample[1], sample[2], sample[3], sample[4], sample[3]],
            )
        except duckdb.ConstraintException:
            pk_rejected = True
        if not pk_rejected:
            console.print(
                "[red]FAIL:[/red] streak_event PK did not reject duplicate"
            )
            return False
        console.print(
            "[green]✓[/green] streak_event PK with COALESCE column rejects duplicates"
        )

    # Idempotency
    rows_2 = build_l1_event(con, verbose=False)
    if rows != rows_2:
        console.print(
            f"[red]FAIL:[/red] event rebuild changed row counts"
        )
        return False
    console.print("[green]✓[/green] event-table rebuild is idempotent")

    return True


def main() -> int:
    console = Console()
    save = BUILDING_THE_GREEN_MONSTER
    dump = save.latest_dump_name()
    con = duckdb.connect()

    if not smoke_l0(con, save, dump, console):
        return 1
    if not smoke_l1_reference(con, console):
        return 1
    if not smoke_l1_machinery(con, save, console):
        return 1
    if not smoke_l1_event(con, console):
        return 1

    console.rule("[bold green]All smoke tests passed[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
