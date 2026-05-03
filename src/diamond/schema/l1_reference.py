"""L1 reference tables — replace-latest from L0, with PK enforcement.

Reference tables hold mostly-static dimensions: geography, leagues, teams,
parks, languages, the user's manager record. They follow a simple
"replace-latest" rule — `build_l1_reference` rebuilds each table from the
most recent dump's L0 rows.

Build pattern, applied to every spec:

    CREATE OR REPLACE TABLE <l1_table> AS
        SELECT * EXCLUDE (dump_date, ingest_ts, file_seq)
        FROM <source_l0>
        WHERE dump_date = (SELECT MAX(dump_date) FROM <source_l0>);

    ALTER TABLE <l1_table> ADD PRIMARY KEY (<pk_cols>);

The `* EXCLUDE` hides L0's three admin columns from L1 — they belong to
provenance, not the analytics surface. Column types and the rest of the
schema are inherited from L0 (which inherited them from `read_csv_auto`'s
type inference, which has been reliable across the audit phase).

PKs are added post-CTAS via `ALTER TABLE` because DuckDB does not support
inline PRIMARY KEY in `CREATE TABLE AS SELECT`. The constraint is real:
inserting a duplicate raises `duckdb.ConstraintException`, verified in
the smoke test.

Per OPEN-2 resolution, `language_data.csv` lands at L0 as `l0_language_data`
but is renamed at L1 to `geo_languages` for clarity (it's a geo→language
demographic mapping, not language metadata).

Per the SCHEMA.md naming convention (OPEN-8 resolution), L1 reference
tables are **unprefixed** (`leagues`, `teams`, `parks`) — the layer is
inferred from build order, not from a name prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Spec
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class L1RefSpec:
    """One L1 reference table.

    Attributes:
        l1_table:    Final L1 table name (no prefix).
        source_l0:   The L0 table to pull from (with `l0_` prefix).
        primary_key: Tuple of column names that uniquely identify a row.
        notes:       Free-form comment on the spec.
    """

    l1_table: str
    source_l0: str
    primary_key: tuple[str, ...]
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Catalog — 12 reference tables
# ─────────────────────────────────────────────────────────────────────────────


L1_REFERENCE_TABLES: list[L1RefSpec] = [
    # ── Geography ──
    L1RefSpec("continents",     "l0_continents",     ("continent_id",)),
    L1RefSpec("nations",        "l0_nations",        ("nation_id",)),
    L1RefSpec("states",         "l0_states",         ("state_id",)),
    L1RefSpec("cities",         "l0_cities",         ("city_id",)),

    # ── Languages (i18n) ──
    L1RefSpec("languages",      "l0_languages",      ("language_id",)),
    L1RefSpec(
        "geo_languages", "l0_language_data",
        ("parent_table", "parent_id", "language_id"),
        notes="Renamed from language_data per OPEN-2 — geo→language demographic mix.",
    ),

    # ── League org tree ──
    L1RefSpec("leagues",        "l0_leagues",        ("league_id",)),
    L1RefSpec(
        "sub_leagues", "l0_sub_leagues",
        ("league_id", "sub_league_id"),
        notes="sub_league_id is unique only within a league_id.",
    ),
    L1RefSpec(
        "divisions", "l0_divisions",
        ("league_id", "sub_league_id", "division_id"),
        notes="division_id is unique only within (league_id, sub_league_id).",
    ),

    # ── Teams & parks ──
    L1RefSpec("teams",          "l0_teams",          ("team_id",)),
    L1RefSpec("parks",          "l0_parks",          ("park_id",)),

    # ── User (the human GM) ──
    L1RefSpec(
        "human_managers", "l0_human_managers",
        ("human_manager_id",),
        notes="Single row in this save (the user). Plural matches the CSV name.",
    ),
]


def _validate_catalog() -> None:
    """Assert no duplicate L1 names and no empty PKs."""
    names = [s.l1_table for s in L1_REFERENCE_TABLES]
    assert len(names) == len(set(names)), (
        f"L1_REFERENCE_TABLES has duplicates: "
        f"{[n for n in names if names.count(n) > 1]}"
    )
    for spec in L1_REFERENCE_TABLES:
        assert spec.primary_key, f"{spec.l1_table} has empty PK"


_validate_catalog()


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────


def build_l1_reference(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build (or rebuild) every L1 reference table from the latest L0 rows.

    Idempotent — uses CREATE OR REPLACE so re-running is safe.

    Returns: dict of `{l1_table_name: row_count}`.

    Raises:
        duckdb.CatalogException if any source L0 table is missing.
        duckdb.ConstraintException if an L0 source contains duplicate keys.
    """
    rows_per_table: dict[str, int] = {}
    for spec in L1_REFERENCE_TABLES:
        pk_list = ", ".join(spec.primary_key)
        # Replace-latest: take rows from the most recent dump_date in L0.
        # Drop L0's admin columns; PK gets added next.
        con.execute(f"""
            CREATE OR REPLACE TABLE {spec.l1_table} AS
            SELECT * EXCLUDE (dump_date, ingest_ts, file_seq)
            FROM {spec.source_l0}
            WHERE dump_date = (SELECT MAX(dump_date) FROM {spec.source_l0})
        """)
        con.execute(
            f"ALTER TABLE {spec.l1_table} ADD PRIMARY KEY ({pk_list})"
        )
        n = con.execute(
            f"SELECT COUNT(*) FROM {spec.l1_table}"
        ).fetchone()[0]
        rows_per_table[spec.l1_table] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {spec.l1_table:<25} "
                f"[dim]{n:>6,} rows  PK=({pk_list})[/dim]"
            )
    return rows_per_table
