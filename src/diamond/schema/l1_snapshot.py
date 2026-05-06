"""L1 state-snapshot tables — per-dump entity state.

Snapshot tables capture "what was true at this dump's date." Unlike event
tables (which UPSERT on natural key, taking the latest dump's row), every
dump's state matters here — diffing successive snapshots is what powers
`player_movements` and any "evolution over time" feature.

Build pattern, applied to every spec:

    CREATE OR REPLACE TABLE <entity>_snapshot AS
        SELECT * EXCLUDE (ingest_ts, file_seq)
                                       -- KEEP dump_date, it's part of the PK
        FROM <l0_source>
        WHERE <scope_filter>;
    ALTER TABLE <entity>_snapshot ADD PRIMARY KEY (<entity_key>..., dump_date);

Special builds:

  - **players_snapshot** folds the four populated `running_ratings_*` cols
    from `l0_players_batting` into the players row (per OPEN-1 — the rest
    of `players_batting` is empty stub data).
  - **players_ratings_snapshot** filters `scouting_team_id = 4` per D12
    (user's-org-scouted only, never the objective `scouting_team_id = 0`).

`_current` views expose the latest dump's snapshot for the most-queried
entities — they're cheap (filter on `dump_date = MAX(dump_date)`) and
shield consumers from having to remember the dump_date filter.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
from rich.console import Console

from diamond.config import SaveConfig

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Spec
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class L1SnapshotSpec:
    """One L1 state-snapshot table."""

    l1_table: str
    source_l0: str
    entity_key: tuple[str, ...]    # PK is entity_key + ("dump_date",)
    scope_where: str = "TRUE"
    notes: str = ""


# Scope-filter fragments (re-used across specs)
_SCOPE_PLAYER = "player_id IN (SELECT player_id FROM _scoped_players)"
_SCOPE_TEAM   = "team_id IN (SELECT team_id FROM _scoped_teams)"
_SCOPE_NONE   = "TRUE"


# ── Generic-build snapshot tables (19) ───────────────────────────────────────
# (players_snapshot and players_ratings_snapshot have special builds below.)

GENERIC_SNAPSHOTS: list[L1SnapshotSpec] = [
    # — Per-player —
    L1SnapshotSpec(
        "players_fielding_snapshot", "l0_players_fielding",
        entity_key=("player_id",), scope_where=_SCOPE_PLAYER,
        notes="OPEN-1: per-position experience + per-position rating + potential.",
    ),
    L1SnapshotSpec(
        "roster_status_snapshot", "l0_players_roster_status",
        entity_key=("player_id",), scope_where=_SCOPE_PLAYER,
    ),
    L1SnapshotSpec(
        "contract_snapshot", "l0_players_contract",
        entity_key=("player_id",), scope_where=_SCOPE_PLAYER,
    ),
    L1SnapshotSpec(
        "contract_extension_snapshot", "l0_players_contract_extension",
        entity_key=("player_id",), scope_where=_SCOPE_PLAYER,
    ),
    L1SnapshotSpec(
        "player_value_snapshot", "l0_players_value",
        entity_key=("player_id",), scope_where=_SCOPE_PLAYER,
        notes="WAR + per-position value buckets.",
    ),

    # — Per-team —
    L1SnapshotSpec(
        "team_record_snapshot", "l0_team_record",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
    ),
    L1SnapshotSpec(
        "team_relations_snapshot", "l0_team_relations",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
        notes="Team's place in (league, sub_league, division). Could shift on realignment.",
    ),
    L1SnapshotSpec(
        "team_roster_snapshot", "l0_team_roster",
        entity_key=("team_id", "player_id", "list_id"),
        scope_where=_SCOPE_TEAM,
        notes="list_id distinguishes 25-man, 40-man, minors etc.",
    ),
    L1SnapshotSpec(
        "team_roster_staff_snapshot", "l0_team_roster_staff",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
        notes="One wide row per team with named staff slots (manager, hitting_coach, etc.).",
    ),
    L1SnapshotSpec(
        "team_affiliations_snapshot", "l0_team_affiliations",
        entity_key=("team_id", "affiliated_team_id"),
        scope_where=_SCOPE_TEAM,
        notes="Org-tree affiliations; can shift between minor-league reorganizations.",
    ),
    L1SnapshotSpec(
        "team_financials_snapshot", "l0_team_financials",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
    ),
    L1SnapshotSpec(
        "team_last_financials_snapshot", "l0_team_last_financials",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
        notes="Prior-season financial close — separate from team_financials (current season).",
    ),
    L1SnapshotSpec(
        "team_batting_stats_snapshot", "l0_team_batting_stats",
        entity_key=("team_id", "split_id"),
        scope_where=_SCOPE_TEAM,
        notes="Current-season running totals; rolls over Feb-Mar each year.",
    ),
    L1SnapshotSpec(
        "team_pitching_stats_snapshot", "l0_team_pitching_stats",
        entity_key=("team_id", "split_id"),
        scope_where=_SCOPE_TEAM,
    ),
    L1SnapshotSpec(
        "team_bullpen_pitching_stats_snapshot", "l0_team_bullpen_pitching_stats",
        entity_key=("team_id", "split_id"),
        scope_where=_SCOPE_TEAM,
    ),
    L1SnapshotSpec(
        "team_starting_pitching_stats_snapshot", "l0_team_starting_pitching_stats",
        entity_key=("team_id", "split_id"),
        scope_where=_SCOPE_TEAM,
    ),
    L1SnapshotSpec(
        "team_fielding_stats_snapshot", "l0_team_fielding_stats_stats",
        entity_key=("team_id", "split_id", "position"),
        scope_where=_SCOPE_TEAM,
        notes="Source CSV named team_fielding_stats_stats.csv (typo in OOTP).",
    ),
    L1SnapshotSpec(
        "projected_rotation_snapshot", "l0_projected_starting_pitchers",
        entity_key=("team_id",), scope_where=_SCOPE_TEAM,
        notes="One wide row per team with starter_0..starter_7 slot fields.",
    ),

    # — Coaches (no scope filter — keep all coaches; the team_id col will
    #            link them to scoped vs unscoped teams) —
    L1SnapshotSpec(
        "coaches_snapshot", "l0_coaches",
        entity_key=("coach_id",), scope_where=_SCOPE_NONE,
    ),
]


def _validate_specs() -> None:
    names = [s.l1_table for s in GENERIC_SNAPSHOTS]
    assert len(names) == len(set(names)), (
        f"L1 snapshot spec duplicates: {[n for n in names if names.count(n) > 1]}"
    )
    for s in GENERIC_SNAPSHOTS:
        assert s.entity_key, f"{s.l1_table} has empty entity_key"


_validate_specs()


# ─────────────────────────────────────────────────────────────────────────────
# Build — generic snapshot tables
# ─────────────────────────────────────────────────────────────────────────────


def _build_one_snapshot(con: duckdb.DuckDBPyConnection, spec: L1SnapshotSpec) -> int:
    pk_cols = spec.entity_key + ("dump_date",)
    pk_list = ", ".join(pk_cols)
    con.execute(f"""
        CREATE OR REPLACE TABLE {spec.l1_table} AS
        SELECT * EXCLUDE (ingest_ts, file_seq)
        FROM {spec.source_l0}
        WHERE ({spec.scope_where})
    """)
    con.execute(f"ALTER TABLE {spec.l1_table} ADD PRIMARY KEY ({pk_list})")
    return con.execute(f"SELECT COUNT(*) FROM {spec.l1_table}").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Special: players_snapshot (fold in batting running cols per OPEN-1)
# ─────────────────────────────────────────────────────────────────────────────


def _build_players_snapshot(con: duckdb.DuckDBPyConnection) -> int:
    """Players state + the 4 useful cols from players_batting per OPEN-1."""
    con.execute("""
        CREATE OR REPLACE TABLE players_snapshot AS
        SELECT
            p.* EXCLUDE (ingest_ts, file_seq),
            pb.running_ratings_speed,
            pb.running_ratings_stealing_rate,
            pb.running_ratings_stealing,
            pb.running_ratings_baserunning
        FROM l0_players p
        LEFT JOIN l0_players_batting pb
               ON p.player_id = pb.player_id
              AND p.dump_date = pb.dump_date
        WHERE p.player_id IN (SELECT player_id FROM _scoped_players)
    """)
    con.execute(
        "ALTER TABLE players_snapshot ADD PRIMARY KEY (player_id, dump_date)"
    )
    return con.execute("SELECT COUNT(*) FROM players_snapshot").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Special: players_ratings_snapshot (D12 filter)
# ─────────────────────────────────────────────────────────────────────────────


def _build_players_ratings_snapshot(
    con: duckdb.DuckDBPyConnection, save: SaveConfig
) -> int:
    """Per-player ratings, FILTERED to user-org-scouted view per D12.

    Drops `scouting_team_id = 0` (objective rating) — never reachable from
    L1+ tables. Other team_ids are also dropped; we keep only the user's
    organization's view (`save.audit_team_id`, currently 4 for the Red Sox).
    """
    con.execute(f"""
        CREATE OR REPLACE TABLE players_ratings_snapshot AS
        SELECT * EXCLUDE (ingest_ts, file_seq, scouting_team_id)
        FROM l0_players_scouted_ratings
        WHERE scouting_team_id = {save.audit_team_id}   -- D12: user-org only
          AND player_id IN (SELECT player_id FROM _scoped_players)
    """)
    con.execute(
        "ALTER TABLE players_ratings_snapshot ADD PRIMARY KEY (player_id, dump_date)"
    )
    return con.execute(
        "SELECT COUNT(*) FROM players_ratings_snapshot"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# `_current` views (latest snapshot's rows only)
# ─────────────────────────────────────────────────────────────────────────────


# Most-queried entities get a `_current` view that filters to the latest
# dump_date. Cheap — just a WHERE clause. No materialization.
_CURRENT_VIEWS: list[tuple[str, str]] = [
    ("players_current",          "players_snapshot"),
    ("players_ratings_current",  "players_ratings_snapshot"),
    ("players_fielding_current", "players_fielding_snapshot"),
    ("roster_status_current",    "roster_status_snapshot"),
    ("contract_current",         "contract_snapshot"),
    ("team_record_current",      "team_record_snapshot"),
    ("team_roster_current",      "team_roster_snapshot"),
]


def _build_current_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Create the `_current` convenience views over `_snapshot` tables."""
    created = []
    for view, source in _CURRENT_VIEWS:
        con.execute(f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT * FROM {source}
            WHERE dump_date = (SELECT MAX(dump_date) FROM {source})
        """)
        created.append(view)
    return created


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l1_snapshot(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build every L1 state-snapshot table + `_current` views.

    Requires `_scoped_teams` / `_scoped_players` from build_l1_machinery.
    Returns dict of `{l1_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    # 1. Specials
    if verbose:
        console.print("[bold]Specials[/bold]  [dim](custom builds)[/dim]")
    n = _build_players_snapshot(con)
    rows["players_snapshot"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] players_snapshot                   "
            f"[dim]{n:>10,} rows  PK=(player_id, dump_date)  +running_ratings[/dim]"
        )
    n = _build_players_ratings_snapshot(con, save)
    rows["players_ratings_snapshot"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] players_ratings_snapshot           "
            f"[dim]{n:>10,} rows  PK=(player_id, dump_date)  D12 filter[/dim]"
        )

    # 2. Generic
    if verbose:
        console.print("[bold]Generic snapshots[/bold]")
    for spec in GENERIC_SNAPSHOTS:
        n = _build_one_snapshot(con, spec)
        rows[spec.l1_table] = n
        if verbose:
            pk = ", ".join(spec.entity_key + ("dump_date",))
            console.print(
                f"  [green]✓[/green] {spec.l1_table:<42} "
                f"[dim]{n:>10,} rows  PK=({pk})[/dim]"
            )

    # 3. _current views
    views = _build_current_views(con)
    if verbose:
        console.print(
            f"[bold]_current views[/bold]  [dim]{len(views)} views over latest dump_date[/dim]"
        )
        for v in views:
            console.print(f"  [green]✓[/green] {v}")

    return rows
