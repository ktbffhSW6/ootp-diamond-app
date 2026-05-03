"""L1 event tables — append-only events scoped to D3/D4.

Event tables hold rows that accumulate but never change retroactively
(games, awards, career-stat snapshots, league/team history, trade events).
Each event table is built from the **latest dump's** rows in its source
L0 table — OOTP's monthly dumps are strict supersets across the season,
so the latest one is canonical.

PKs come in three flavors:

  1. **Natural PK** — 21 tables where one or more L0 columns uniquely
     identify a row. Verified empirically by the PK probe.
  2. **Synthetic PK = (dump_date, file_seq)** — 12 tables where natural
     columns have OOTP-source dups (e.g., `players_career_batting_stats`
     has multiple rows per (player, year, team, level, split, stint) due
     to historical-import quirks). The synthetic PK is unambiguous; the
     "natural" identifier set is documented as informational. L2 facts
     are responsible for aggregating across the dups.
  3. **Synthesized column in PK** — 2 tables (at-bats, streaks) where
     the L0 row needs an extra computed column to be uniquely keyed.

Build pattern (applied per spec):

    CREATE OR REPLACE TABLE <event> AS
        SELECT * EXCLUDE (dump_date, ingest_ts, file_seq)   -- or keep, for synthetic PKs
        FROM <l0_source>
        WHERE dump_date = (SELECT MAX(dump_date) FROM <l0_source>)
          AND <scope_filter>;
    ALTER TABLE <event> ADD PRIMARY KEY (<pk_cols>);

Scope filter is per-table (D3/D4) — see `_scoped_teams` / `_scoped_players`
in `l1_machinery.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Specs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class L1EventSpec:
    """One L1 event table.

    Attributes:
        l1_table:        Final L1 table name (with `_event` suffix).
        source_l0:       The L0 table to pull from.
        primary_key:     Tuple of columns enforced as PK.
        natural_key:     Conceptual identifier set, even if not enforceable.
                         Equal to `primary_key` for natural-PK tables;
                         documents the conceptual key for synthetic ones.
        scope_where:     SQL fragment applied as additional WHERE. Use
                         `"TRUE"` for tables with no scope filter.
        keep_admin:      If True, preserve `dump_date` / `file_seq` columns
                         in L1 (required when the synthetic PK uses them).
        notes:           Free-form per-spec comment.
    """

    l1_table: str
    source_l0: str
    primary_key: tuple[str, ...]
    natural_key: tuple[str, ...]
    scope_where: str = "TRUE"
    keep_admin: bool = False
    notes: str = ""


# Scope filter fragments. The `IN (SELECT ...)` form is what DuckDB optimizes
# into a hash join — fast. Each is a stable WHERE-clause snippet referencing
# the relevant l0 source columns by name.
_SCOPE_PLAYER       = "player_id IN (SELECT player_id FROM _scoped_players)"
_SCOPE_TEAM         = "team_id IN (SELECT team_id FROM _scoped_teams)"
_SCOPE_LEAGUE_HARDCODED_15 = (
    # The 15 scoped league_ids per SaveConfig.league_ids. Inlined here so
    # this module doesn't import SaveConfig (the league_id list is also a
    # decision per D11 — once a league is in scope it stays in scope).
    "league_id IN (203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, "
    "252, 217, 218, 234, 70)"
)
_SCOPE_NONE         = "TRUE"   # human_manager_history et al — single user, no filter


# Trade scope: a trade is in-scope if ANY participating team is scoped.
# trade_history.csv has team_id_0 and team_id_1 (each side of the trade).
_SCOPE_TRADE = (
    "(team_id_0 IN (SELECT team_id FROM _scoped_teams) "
    "OR team_id_1 IN (SELECT team_id FROM _scoped_teams))"
)


# ── Natural-PK event tables (21) ──────────────────────────────────────────────

NATURAL_PK_EVENTS: list[L1EventSpec] = [
    # — Games —
    L1EventSpec(
        "games_event", "l0_games",
        primary_key=("game_id",), natural_key=("game_id",),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15,
    ),
    L1EventSpec(
        "games_score_event", "l0_games_score",
        primary_key=("game_id", "team", "inning"),
        natural_key=("game_id", "team", "inning"),
        scope_where="game_id IN (SELECT game_id FROM games_event)",
        notes="Filtered transitively through games_event so it stays scope-consistent.",
    ),

    # — Per-player events with natural keys —
    L1EventSpec(
        "players_individual_batting_event", "l0_players_individual_batting_stats",
        primary_key=("player_id", "opponent_id"),
        natural_key=("player_id", "opponent_id"),
        scope_where=_SCOPE_PLAYER,
        notes="Career head-to-head per (batter, opponent_pitcher).",
    ),
    L1EventSpec(
        "players_league_leader_event", "l0_players_league_leader",
        primary_key=("player_id", "year", "league_id", "category"),
        natural_key=("player_id", "year", "league_id", "category"),
        scope_where=_SCOPE_PLAYER,
    ),
    L1EventSpec(
        "players_game_pitching_event", "l0_players_game_pitching_stats",
        primary_key=("player_id", "game_id"),
        natural_key=("player_id", "game_id"),
        scope_where=_SCOPE_PLAYER,
    ),

    # — Trade —
    L1EventSpec(
        "trade_event", "l0_trade_history",
        primary_key=("message_id",), natural_key=("message_id",),
        scope_where=_SCOPE_TRADE,
        notes="Each row is one trade; multi-team trades involving any scoped team kept.",
    ),

    # — League history (parent + all-star + playoffs) —
    L1EventSpec(
        "league_history_all_star_event", "l0_league_history_all_star",
        primary_key=("league_id", "sub_league_id", "year", "all_star_pos", "all_star"),
        natural_key=("league_id", "sub_league_id", "year", "all_star_pos", "all_star"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15,
    ),
    L1EventSpec(
        "league_playoffs_event", "l0_league_playoffs",
        primary_key=("league_id",), natural_key=("league_id",),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15,
        notes="One row per league describing the playoff structure.",
    ),
    L1EventSpec(
        "league_playoff_fixtures_event", "l0_league_playoff_fixtures",
        primary_key=("league_id", "round", "team_id0", "team_id1"),
        natural_key=("league_id", "round", "team_id0", "team_id1"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15,
    ),

    # — Team history —
    L1EventSpec(
        "team_history_event", "l0_team_history",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
    ),
    L1EventSpec(
        "team_history_batting_event", "l0_team_history_batting_stats",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
    ),
    L1EventSpec(
        "team_history_pitching_event", "l0_team_history_pitching_stats",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
    ),
    L1EventSpec(
        "team_history_fielding_event", "l0_team_history_fielding_stats_stats",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
        notes="Source CSV is curiously named `team_history_fielding_stats_stats.csv`.",
    ),
    L1EventSpec(
        "team_history_financials_event", "l0_team_history_financials",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
    ),
    L1EventSpec(
        "team_history_record_event", "l0_team_history_record",
        primary_key=("team_id", "year"), natural_key=("team_id", "year"),
        scope_where=_SCOPE_TEAM,
    ),

    # — Human manager (the user) —
    L1EventSpec(
        "human_manager_history_event", "l0_human_manager_history",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
    L1EventSpec(
        "human_manager_history_batting_event", "l0_human_manager_history_batting_stats",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
    L1EventSpec(
        "human_manager_history_pitching_event", "l0_human_manager_history_pitching_stats",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
    L1EventSpec(
        "human_manager_history_fielding_event", "l0_human_manager_history_fielding_stats_stats",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
    L1EventSpec(
        "human_manager_history_financials_event", "l0_human_manager_history_financials",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
    L1EventSpec(
        "human_manager_history_record_event", "l0_human_manager_history_record",
        primary_key=("human_manager_id", "year"),
        natural_key=("human_manager_id", "year"),
        scope_where=_SCOPE_NONE,
    ),
]


# ── Synthetic-PK event tables (12) ────────────────────────────────────────────
# The natural identifier set has OOTP-source dups (verified by probe).
# We use `(dump_date, file_seq)` from L0 as the enforced PK; the natural
# key is documented for L2 aggregation logic.

SYNTHETIC_PK_EVENTS: list[L1EventSpec] = [
    L1EventSpec(
        "players_career_batting_event", "l0_players_career_batting_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "year", "team_id", "league_id", "level_id",
                     "split_id", "stint"),
        scope_where=_SCOPE_PLAYER,
        keep_admin=True,
        notes=(
            "Natural key has dups in OOTP data (e.g. player 118234 in 1948 "
            "shows two rows with same (player,year,team,...) but different AB). "
            "L2 f_player_season_batting aggregates across these by the "
            "natural key."
        ),
    ),
    L1EventSpec(
        "players_career_pitching_event", "l0_players_career_pitching_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "year", "team_id", "league_id", "level_id",
                     "split_id", "stint"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes="Same OOTP-source dup pattern as career_batting.",
    ),
    L1EventSpec(
        "players_career_fielding_event", "l0_players_career_fielding_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "year", "team_id", "league_id", "level_id",
                     "split_id", "position"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes="Same OOTP-source dup pattern.",
    ),
    L1EventSpec(
        "players_awards_event", "l0_players_awards",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "year", "award_id", "league_id",
                     "season", "month", "day"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes=(
            "Natural key approximation — multi-occurrence awards (Player of "
            "the Week) collide on (player, year, award_id) without month/day."
        ),
    ),
    L1EventSpec(
        "players_injury_event", "l0_players_injury_history",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "date", "body_part"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes="(player, date, body_part) has 5 dups; setbacks may help further.",
    ),
    L1EventSpec(
        "players_salary_history_event", "l0_players_salary_history",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "year"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes=(
            "Multiple salary entries per (player, year) when contracts "
            "restructure mid-season. ~1.1% of rows are dups."
        ),
    ),
    L1EventSpec(
        "players_game_batting_event", "l0_players_game_batting",
        primary_key=("dump_date", "file_seq"),
        natural_key=("player_id", "game_id"),
        scope_where=_SCOPE_PLAYER, keep_admin=True,
        notes="14 dups in 430K rows — likely doubleheader edge case.",
    ),
    L1EventSpec(
        "league_events_event", "l0_league_events",
        primary_key=("dump_date", "file_seq"),
        natural_key=("league_id", "start_date", "type", "name"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15, keep_admin=True,
        notes="(league_id, start_date, type, name) has ~30% dups.",
    ),
    L1EventSpec(
        "league_history_main_event", "l0_league_history",
        primary_key=("dump_date", "file_seq"),
        natural_key=("league_id", "year"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15, keep_admin=True,
        notes=(
            "Parent league_history table — separate from league_history_*_stats. "
            "(league_id, year) has dups, possibly due to sub_league rows or "
            "season-state rows."
        ),
    ),
    L1EventSpec(
        "league_history_batting_event", "l0_league_history_batting_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("league_id", "year", "level_id", "team_id", "game_id"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15, keep_admin=True,
        notes=(
            "team_id discriminates AL (12) vs NL (25) sub-leagues per D11. "
            "Even (league_id, year, level_id, team_id, game_id) doesn't fully "
            "uniquely identify rows — likely additional season-state dim. "
            "league_constants module aggregates via GROUP BY (league_id, year, "
            "level_id) which is correct."
        ),
    ),
    L1EventSpec(
        "league_history_pitching_event", "l0_league_history_pitching_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("league_id", "year", "level_id", "team_id", "game_id"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15, keep_admin=True,
        notes="Same shape as league_history_batting; aggregate at L2.",
    ),
    L1EventSpec(
        "league_history_fielding_event", "l0_league_history_fielding_stats",
        primary_key=("dump_date", "file_seq"),
        natural_key=("league_id", "year", "level_id", "team_id", "position"),
        scope_where=_SCOPE_LEAGUE_HARDCODED_15, keep_admin=True,
        notes="Same shape; aggregate at L2.",
    ),
]


ALL_EVENT_SPECS: list[L1EventSpec] = NATURAL_PK_EVENTS + SYNTHETIC_PK_EVENTS


def _validate_specs() -> None:
    names = [s.l1_table for s in ALL_EVENT_SPECS]
    assert len(names) == len(set(names)), (
        f"L1 event spec duplicates: {[n for n in names if names.count(n) > 1]}"
    )
    for s in ALL_EVENT_SPECS:
        assert s.primary_key, f"{s.l1_table} has empty PK"
        assert s.natural_key, f"{s.l1_table} has empty natural key"


_validate_specs()


# ─────────────────────────────────────────────────────────────────────────────
# Build — generic event tables
# ─────────────────────────────────────────────────────────────────────────────


def _build_one_event(con: duckdb.DuckDBPyConnection, spec: L1EventSpec) -> int:
    """Materialize one L1 event table from its spec."""
    if spec.keep_admin:
        # Synthetic PK uses (dump_date, file_seq) so we keep them, drop only ingest_ts.
        select_clause = "SELECT * EXCLUDE (ingest_ts)"
    else:
        # Natural PK; drop all three admin cols.
        select_clause = "SELECT * EXCLUDE (dump_date, ingest_ts, file_seq)"

    pk_list = ", ".join(spec.primary_key)
    con.execute(f"""
        CREATE OR REPLACE TABLE {spec.l1_table} AS
        {select_clause}
        FROM {spec.source_l0}
        WHERE dump_date = (SELECT MAX(dump_date) FROM {spec.source_l0})
          AND ({spec.scope_where})
    """)
    con.execute(f"ALTER TABLE {spec.l1_table} ADD PRIMARY KEY ({pk_list})")
    return con.execute(f"SELECT COUNT(*) FROM {spec.l1_table}").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Build — special: at_bats_event (synthesized pa_in_game_seq per OPEN-4)
# ─────────────────────────────────────────────────────────────────────────────


def _build_at_bats_event(con: duckdb.DuckDBPyConnection) -> int:
    """Build at_bats_event with synthesized `pa_in_game_seq`.

    The CSV is grouped by batter; within (game_id, player_id) file_seq is
    chronological (per OPEN-4). pa_in_game_seq = ROW_NUMBER OVER
    (PARTITION BY game_id, player_id ORDER BY file_seq) — "this batter's
    Nth PA of this game".
    """
    con.execute("""
        CREATE OR REPLACE TABLE at_bats_event AS
        SELECT * EXCLUDE (dump_date, ingest_ts, file_seq),
            ROW_NUMBER() OVER (
                PARTITION BY game_id, player_id
                ORDER BY file_seq
            ) AS pa_in_game_seq
        FROM l0_players_at_bat_batting_stats
        WHERE dump_date = (SELECT MAX(dump_date) FROM l0_players_at_bat_batting_stats)
          AND player_id IN (SELECT player_id FROM _scoped_players)
    """)
    con.execute(
        "ALTER TABLE at_bats_event ADD PRIMARY KEY (game_id, player_id, pa_in_game_seq)"
    )
    return con.execute("SELECT COUNT(*) FROM at_bats_event").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Build — special: streak_event (synthesized ended_or_max for COALESCE PK)
# ─────────────────────────────────────────────────────────────────────────────


def _build_streak_event(con: duckdb.DuckDBPyConnection) -> int:
    """Build streak_event with `ended_or_max` derived col per OPEN-5.

    ~0.15% of rows have NULL `ended` (active streaks); OOTP also emits
    boundary dups where a new active streak starts on the same day a
    prior streak ended. Including a derived `ended_or_max = COALESCE
    (ended, '9999-12-31')` in the PK resolves both cases.
    """
    # `ended` arrives from L0 as VARCHAR (OOTP date format "2026-5-13" with
    # un-padded month/day); TRY_CAST coerces it to DATE, NULL on parse fail
    # (which COALESCE then replaces with the sentinel).
    con.execute("""
        CREATE OR REPLACE TABLE streak_event AS
        SELECT * EXCLUDE (dump_date, ingest_ts, file_seq),
            COALESCE(TRY_CAST(ended AS DATE), CAST('9999-12-31' AS DATE)) AS ended_or_max
        FROM l0_players_streak
        WHERE dump_date = (SELECT MAX(dump_date) FROM l0_players_streak)
          AND player_id IN (SELECT player_id FROM _scoped_players)
    """)
    con.execute(
        "ALTER TABLE streak_event ADD PRIMARY KEY "
        "(player_id, league_id, streak_id, started, ended_or_max)"
    )
    return con.execute("SELECT COUNT(*) FROM streak_event").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l1_event(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build all L1 event tables. Requires _scoped_teams / _scoped_players.

    Returns: dict of `{l1_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    # 1. Natural-PK first (some have transitive scope dependencies, e.g.
    #    games_score_event references games_event)
    if verbose:
        console.print("[bold]Natural-PK events[/bold]")
    for spec in NATURAL_PK_EVENTS:
        n = _build_one_event(con, spec)
        rows[spec.l1_table] = n
        if verbose:
            pk = ", ".join(spec.primary_key)
            console.print(
                f"  [green]✓[/green] {spec.l1_table:<42} "
                f"[dim]{n:>10,} rows  PK=({pk})[/dim]"
            )

    # 2. Synthetic-PK
    if verbose:
        console.print("[bold]Synthetic-PK events[/bold]  [dim](dump_date, file_seq)[/dim]")
    for spec in SYNTHETIC_PK_EVENTS:
        n = _build_one_event(con, spec)
        rows[spec.l1_table] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {spec.l1_table:<42} "
                f"[dim]{n:>10,} rows[/dim]"
            )

    # 3. Specials
    if verbose:
        console.print("[bold]Specials[/bold]  [dim](synthesized PK columns)[/dim]")
    n = _build_at_bats_event(con)
    rows["at_bats_event"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] at_bats_event                              "
            f"[dim]{n:>10,} rows  PK=(game_id, player_id, pa_in_game_seq)[/dim]"
        )
    n = _build_streak_event(con)
    rows["streak_event"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] streak_event                               "
            f"[dim]{n:>10,} rows  PK includes COALESCE(ended, '9999-12-31')[/dim]"
        )

    return rows
