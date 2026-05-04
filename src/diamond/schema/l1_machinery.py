"""Warehouse machinery — scope sets used by L1 event/snapshot builders.

`_scoped_teams` and `_scoped_players` are bookkeeping tables that downstream
L1 builders consult to enforce Decisions D3 (strict league scope for v1)
and D4 (once-in-scope, always-in-scope for players), with optional D13
reference-scope expansion.

  - `_scoped_teams`:   team_id PK. Every team whose `league_id` is in
                       `SaveConfig.league_ids` (15 league_ids for "Building
                       the Green Monster"). One-shot read from `l0_teams`.
  - `_scoped_players`: player_id PK. Two-tier per D13:
                       1. **Org tier** (always on): every player who, at
                          any dump, was on a scoped team. Union across
                          ALL `l0_players` snapshots — D4's "stays in
                          scope through retirement" rule.
                       2. **Reference tier** (D13, opt-in): every player
                          with ≥1 career MLB appearance (PA at level_id=1
                          OR pitching outs at level_id=1). Sourced from
                          `l0_players_career_batting_stats` and
                          `l0_players_career_pitching_stats`. Adds the
                          HoFers, current-era stars on other orgs, and
                          historical legends OOTP imports.

Both tables are full-rebuild on every ingest (`CREATE OR REPLACE`). They
must be rebuilt before any L1 event/snapshot table that filters by them.

The leading underscore in the name marks these as warehouse machinery,
distinguishing them from the analytics surface (`leagues`, `players_event`,
`f_player_season_batting`, etc.). Per the SCHEMA.md naming convention.

Note on the reference-scope cohort definition: D13 originally specified
"≥1 MLB PA" (batting only). In universal-DH eras pitchers may never bat,
so a strict PA gate would exclude relief-only pitchers from the reference
scope (~3K pitchers in this save). The implementation extends to
`PA ≥ 1 OR pitching outs ≥ 1` — i.e., "ever played MLB". Documented
back in D13 as a clarification.
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

    When `save.reference_scope_enabled` is True, expands `_scoped_players`
    to include any player with ≥1 MLB appearance per D13 (see module
    docstring for cohort definition).

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

    # Scoped players — org-tier base set: union across all l0_players
    # snapshots of any player who was on a scoped team in any dump (D4).
    org_clause = """
        SELECT DISTINCT player_id
        FROM l0_players
        WHERE team_id IN (SELECT team_id FROM _scoped_teams)
    """

    if save.reference_scope_enabled:
        # D13 reference-tier expansion: players with ≥1 MLB appearance.
        # MLB = level_id = 1, split_id = 1 (overall, no platoon split).
        # Includes both batting (PA) and pitching (IP outs) so universal-
        # DH-era relief pitchers aren't dropped.
        scoped_players_sql = f"""
            CREATE OR REPLACE TABLE _scoped_players AS
            ({org_clause})
            UNION
            SELECT DISTINCT player_id
            FROM l0_players_career_batting_stats
            WHERE level_id = 1 AND split_id = 1 AND pa >= 1
            UNION
            SELECT DISTINCT player_id
            FROM l0_players_career_pitching_stats
            WHERE level_id = 1 AND split_id = 1 AND outs >= 1
        """
    else:
        scoped_players_sql = f"""
            CREATE OR REPLACE TABLE _scoped_players AS
            ({org_clause})
        """

    con.execute(scoped_players_sql)
    con.execute("ALTER TABLE _scoped_players ADD PRIMARY KEY (player_id)")
    n_players = con.execute(
        "SELECT COUNT(*) FROM _scoped_players"
    ).fetchone()[0]

    if verbose:
        console.print(
            f"  [green]✓[/green] _scoped_teams    "
            f"[dim]{n_teams:>6,} teams[/dim]"
        )
        ref_tag = " + reference (D13)" if save.reference_scope_enabled else ""
        console.print(
            f"  [green]✓[/green] _scoped_players  "
            f"[dim]{n_players:>6,} players (org-tier{ref_tag})[/dim]"
        )

    return {"_scoped_teams": n_teams, "_scoped_players": n_players}
