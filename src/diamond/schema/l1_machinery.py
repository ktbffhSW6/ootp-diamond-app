"""Warehouse machinery — scope sets used by L1 event/snapshot builders.

`_scoped_teams` and `_scoped_players` are bookkeeping tables that downstream
L1 builders consult to enforce Decisions D3 (strict league scope for v1)
and D4 (once-in-scope, always-in-scope for players).

  - `_scoped_teams`:   team_id PK. Every team whose `league_id` is in
                       `SaveConfig.league_ids` (15 league_ids for "Building
                       the Green Monster"). One-shot read from `l0_teams`.
  - `_scoped_players`: player_id PK. Every player who, at any dump, was
                       on a scoped team. Union across ALL `l0_players`
                       snapshots — that's how D4's "stays in scope through
                       retirement" rule materializes.

Both tables are full-rebuild on every ingest (`CREATE OR REPLACE`). They
must be rebuilt before any L1 event/snapshot table that filters by them.

The leading underscore in the name marks these as warehouse machinery,
distinguishing them from the analytics surface (`leagues`, `players_event`,
`f_player_season_batting`, etc.). Per the SCHEMA.md naming convention.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

from diamond.config import SaveConfig

console = Console()


def build_l1_machinery(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build `_scoped_teams` and `_scoped_players` from L0.

    Returns: dict of `{table_name: row_count}`.
    """
    league_id_list = ", ".join(str(i) for i in save.league_ids)

    # Scoped teams: any team whose league_id is in SaveConfig.league_ids.
    # `l0_teams` is replace-latest in shape (one row per team_id per dump),
    # but team→league assignment is stable across dumps in OOTP, so taking
    # ANY dump's view works. We dedupe with DISTINCT.
    con.execute(f"""
        CREATE OR REPLACE TABLE _scoped_teams AS
        SELECT DISTINCT team_id
        FROM l0_teams
        WHERE league_id IN ({league_id_list})
    """)
    con.execute("ALTER TABLE _scoped_teams ADD PRIMARY KEY (team_id)")
    n_teams = con.execute("SELECT COUNT(*) FROM _scoped_teams").fetchone()[0]

    # Scoped players: union across ALL l0_players snapshots of any player
    # who was on a scoped team in any dump. Captures D4 — once a player is
    # in scope they stay there even if they leave for KBO later.
    con.execute("""
        CREATE OR REPLACE TABLE _scoped_players AS
        SELECT DISTINCT player_id
        FROM l0_players
        WHERE team_id IN (SELECT team_id FROM _scoped_teams)
    """)
    con.execute("ALTER TABLE _scoped_players ADD PRIMARY KEY (player_id)")
    n_players = con.execute(
        "SELECT COUNT(*) FROM _scoped_players"
    ).fetchone()[0]

    if verbose:
        console.print(
            f"  [green]✓[/green] _scoped_teams    "
            f"[dim]{n_teams:>6,} teams[/dim]"
        )
        console.print(
            f"  [green]✓[/green] _scoped_players  "
            f"[dim]{n_players:>6,} players (across all dumps' snapshots)[/dim]"
        )

    return {"_scoped_teams": n_teams, "_scoped_players": n_players}
