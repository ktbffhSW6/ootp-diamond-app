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
    GENERIC_SNAPSHOTS,
    L0_CATALOG,
    L1_REFERENCE_TABLES,
    build_l0,
    build_l1_event,
    build_l1_machinery,
    build_l1_reference,
    build_l1_snapshot,
    build_l2,
    build_l3,
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


def smoke_l1_snapshot(con: duckdb.DuckDBPyConnection, save, console: Console) -> bool:
    """Phase D invariants. Returns True on pass."""
    console.rule("Phase D — L1 state-snapshot tables")
    rows = build_l1_snapshot(con, save, verbose=True)

    expected = len(GENERIC_SNAPSHOTS) + 2  # + players_snapshot + players_ratings_snapshot
    if len(rows) != expected:
        console.print(
            f"[red]FAIL:[/red] built {len(rows)} snapshots, expected {expected}"
        )
        return False
    console.print(f"\n[green]✓[/green] all {expected} snapshot tables built")

    # D12: players_ratings_snapshot must NOT contain scouting_team_id=0 rows.
    # (The col was dropped at build, but verify by checking against l0 source
    # we'd see the scouting_team_id=0 player count is non-zero in L0 but the
    # filter was applied.)
    l0_team0 = con.execute("""
        SELECT COUNT(*) FROM l0_players_scouted_ratings
        WHERE scouting_team_id = 0
          AND dump_date = (SELECT MAX(dump_date) FROM l0_players_scouted_ratings)
    """).fetchone()[0]
    l1_total = con.execute(
        "SELECT COUNT(*) FROM players_ratings_snapshot WHERE dump_date = "
        "(SELECT MAX(dump_date) FROM players_ratings_snapshot)"
    ).fetchone()[0]
    if l0_team0 == 0:
        console.print(
            "[yellow]Note:[/yellow] no scouting_team_id=0 rows in L0 (unexpected)"
        )
    else:
        # If l1 latest count <= l0 scouting_team_id=4 count, we filtered correctly
        l0_team4 = con.execute(f"""
            SELECT COUNT(*) FROM l0_players_scouted_ratings
            WHERE scouting_team_id = {save.audit_team_id}
              AND dump_date = (SELECT MAX(dump_date) FROM l0_players_scouted_ratings)
              AND player_id IN (SELECT player_id FROM _scoped_players)
        """).fetchone()[0]
        if l1_total != l0_team4:
            console.print(
                f"[red]FAIL:[/red] players_ratings_snapshot latest = {l1_total} "
                f"≠ expected scouted+scoped {l0_team4}"
            )
            return False
        console.print(
            f"[green]✓[/green] D12 filter applied: only scouting_team_id={save.audit_team_id} "
            f"rows in players_ratings_snapshot ({l1_total} latest-dump rows)"
        )

    # Spot-check: players_snapshot should have running_ratings_speed populated
    cols = {r[0] for r in con.execute("DESCRIBE players_snapshot").fetchall()}
    for needed in ("running_ratings_speed", "running_ratings_baserunning"):
        if needed not in cols:
            console.print(f"[red]FAIL:[/red] players_snapshot missing {needed}")
            return False
    console.print("[green]✓[/green] players_snapshot has folded-in running_ratings_* cols")

    # _current views should expose just one row per player (latest dump)
    n = con.execute("SELECT COUNT(*) FROM players_current").fetchone()[0]
    n_distinct = con.execute(
        "SELECT COUNT(DISTINCT player_id) FROM players_current"
    ).fetchone()[0]
    if n != n_distinct:
        console.print(
            f"[red]FAIL:[/red] players_current has {n} rows but {n_distinct} "
            f"distinct player_ids"
        )
        return False
    console.print(f"[green]✓[/green] players_current is 1-row-per-player ({n:,})")

    # Idempotency
    rows_2 = build_l1_snapshot(con, save, verbose=False)
    if rows != rows_2:
        console.print("[red]FAIL:[/red] snapshot rebuild changed row counts")
        return False
    console.print("[green]✓[/green] snapshot rebuild is idempotent")

    return True


def smoke_l2(con: duckdb.DuckDBPyConnection, console: Console) -> bool:
    """Phase E invariants. Returns True on pass."""
    console.rule("Phase E — L2 facts")
    rows = build_l2(con, verbose=True)

    if len(rows) != 8:
        console.print(f"[red]FAIL:[/red] built {len(rows)} L2 facts, expected 8")
        return False
    console.print(f"\n[green]✓[/green] all 8 L2 fact tables built")

    # f_player_season_batting must collapse the L1 OOTP-source dups —
    # row count should be ≤ L1 row count.
    l1_n = con.execute("SELECT COUNT(*) FROM players_career_batting_event").fetchone()[0]
    l2_n = rows["f_player_season_batting"]
    if l2_n > l1_n:
        console.print(
            f"[red]FAIL:[/red] f_player_season_batting={l2_n} > "
            f"L1 source={l1_n}"
        )
        return False
    if l2_n == l1_n:
        console.print(
            f"[yellow]Note:[/yellow] f_player_season_batting == L1 row count "
            f"({l2_n}) — no dup collapse occurred"
        )
    else:
        console.print(
            f"[green]✓[/green] f_player_season_batting collapsed L1 dups: "
            f"{l1_n:,} → {l2_n:,} ({l1_n - l2_n} rows removed)"
        )

    # f_pa_event must have year/league_id/level_id populated for every row
    # (the dim flatten contract)
    null_dim = con.execute("""
        SELECT COUNT(*) FROM f_pa_event
        WHERE year IS NULL OR league_id IS NULL OR level_id IS NULL
    """).fetchone()[0]
    if null_dim > 0:
        console.print(
            f"[red]FAIL:[/red] f_pa_event has {null_dim} rows with NULL dims"
        )
        return False
    console.print(
        f"[green]✓[/green] f_pa_event dim flatten complete (year, league_id, level_id all populated)"
    )

    # Sanity: f_player_career row count should match scoped player count
    n_career = rows["f_player_career"]
    n_scoped = con.execute("SELECT COUNT(*) FROM _scoped_players").fetchone()[0]
    if n_career > n_scoped:
        console.print(
            f"[red]FAIL:[/red] f_player_career={n_career} > _scoped_players={n_scoped}"
        )
        return False
    console.print(
        f"[green]✓[/green] f_player_career has {n_career:,} rows "
        f"(of {n_scoped:,} scoped players — others have no career stats yet)"
    )

    # Idempotency
    rows_2 = build_l2(con, verbose=False)
    if rows != rows_2:
        console.print("[red]FAIL:[/red] L2 rebuild changed row counts")
        return False
    console.print("[green]✓[/green] L2 rebuild is idempotent")

    return True


def smoke_l3(con: duckdb.DuckDBPyConnection, console: Console) -> bool:
    """Phase F invariants (L3 derived).

    With a single dump the full snapshot-diff of `player_movements` only
    yields `first_appearance` rows (no LAG predecessor exists), so the
    invariant set is light:

      - f_trade_participant builds with PK enforced
      - player_movements builds and contains the trade_id column
      - All team_change rows with trade_id resolve to a real f_trade_participant
        entry (referential consistency)
      - L3 rebuild is idempotent
    """
    console.rule("Phase F — L3 derived")
    rows = build_l3(con, verbose=True)

    # f_trade_participant: every row should map to a real trade_event
    n_orphans = con.execute("""
        SELECT COUNT(*) FROM f_trade_participant tp
        WHERE NOT EXISTS (
            SELECT 1 FROM trade_event te WHERE te.message_id = tp.trade_id
        )
    """).fetchone()[0]
    if n_orphans:
        console.print(
            f"[red]FAIL:[/red] {n_orphans} f_trade_participant rows lack "
            f"a matching trade_event"
        )
        return False
    console.print(
        "[green]✓[/green] f_trade_participant rows all resolve to trade_event"
    )

    # player_movements has the trade_id column
    # PRAGMA table_info row shape: (cid, name, type, notnull, dflt_value, pk)
    cols = {r[1] for r in con.execute("PRAGMA table_info(player_movements)").fetchall()}
    if "trade_id" not in cols:
        console.print("[red]FAIL:[/red] player_movements missing trade_id column")
        return False
    console.print("[green]✓[/green] player_movements has trade_id column")

    # Every non-null trade_id in player_movements must reference a real trade
    n_orphan_attrib = con.execute("""
        SELECT COUNT(*) FROM player_movements pm
        WHERE pm.trade_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM f_trade_participant tp
              WHERE tp.trade_id = pm.trade_id AND tp.player_id = pm.player_id
          )
    """).fetchone()[0]
    if n_orphan_attrib:
        console.print(
            f"[red]FAIL:[/red] {n_orphan_attrib} player_movements rows have "
            f"trade_id without matching f_trade_participant entry"
        )
        return False
    console.print(
        "[green]✓[/green] all player_movements.trade_id values resolve to "
        "f_trade_participant"
    )

    # f_draft_class: every row maps to a real player and to a real draft team
    n_orphan_player = con.execute("""
        SELECT COUNT(*) FROM f_draft_class fdc
        WHERE NOT EXISTS (
            SELECT 1 FROM players_current pc WHERE pc.player_id = fdc.player_id
        )
    """).fetchone()[0]
    if n_orphan_player:
        console.print(
            f"[red]FAIL:[/red] {n_orphan_player} f_draft_class rows lack a "
            f"matching players_current entry"
        )
        return False
    console.print(
        "[green]✓[/green] f_draft_class rows all resolve to players_current"
    )

    # f_draft_class: outcome bucket invariants
    # 1) ever_made_mlb=true  ⇒ outcome must be one of {mlb_star, mlb_regular, mlb_callup, retired}
    # 2) ever_made_mlb=false ⇒ outcome must be one of {in_draft_org, traded_away, released, retired}
    n_outcome_violation = con.execute("""
        SELECT COUNT(*) FROM f_draft_class
        WHERE
          (ever_made_mlb = TRUE  AND outcome NOT IN ('mlb_star','mlb_regular','mlb_callup','retired'))
       OR (ever_made_mlb = FALSE AND outcome NOT IN ('in_draft_org','traded_away','released','retired'))
    """).fetchone()[0]
    if n_outcome_violation:
        console.print(
            f"[red]FAIL:[/red] {n_outcome_violation} f_draft_class rows have "
            f"outcome inconsistent with ever_made_mlb"
        )
        return False
    console.print(
        "[green]✓[/green] f_draft_class outcomes consistent with ever_made_mlb"
    )

    # f_record_player: ranks are contiguous 1..N per (category × source);
    # values must be monotonically non-increasing as rank_in_source goes up.
    n_rank_violation = con.execute("""
        WITH grouped AS (
            SELECT scope, discipline, category, source,
                   COUNT(*) AS n,
                   MAX(rank_in_source) AS max_rank,
                   MIN(rank_in_source) AS min_rank
            FROM f_record_player
            GROUP BY scope, discipline, category, source
        )
        SELECT COUNT(*) FROM grouped
        WHERE max_rank != n OR min_rank != 1
    """).fetchone()[0]
    if n_rank_violation:
        console.print(
            f"[red]FAIL:[/red] {n_rank_violation} f_record_player (category, source) "
            f"groups have non-contiguous rank_in_source sequences"
        )
        return False
    console.print(
        "[green]✓[/green] f_record_player rank_in_source contiguous per (category, source)"
    )

    n_value_violation = con.execute("""
        WITH ordered AS (
            SELECT scope, discipline, category, source, rank_in_source, value,
                   LAG(value) OVER (
                       PARTITION BY scope, discipline, category, source
                       ORDER BY rank_in_source
                   ) AS prev_value
            FROM f_record_player
        )
        SELECT COUNT(*) FROM ordered
        WHERE prev_value IS NOT NULL AND value > prev_value
    """).fetchone()[0]
    if n_value_violation:
        console.print(
            f"[red]FAIL:[/red] f_record_player has {n_value_violation} rows where "
            f"value increases as rank_in_source goes up"
        )
        return False
    console.print(
        "[green]✓[/green] f_record_player values monotonically descend by rank_in_source"
    )

    # source must be one of {'save', 'lahman', 'bref', 'statcast'}
    n_bad_source = con.execute("""
        SELECT COUNT(*) FROM f_record_player
        WHERE source NOT IN ('save', 'lahman', 'bref', 'statcast')
    """).fetchone()[0]
    if n_bad_source:
        console.print(
            f"[red]FAIL:[/red] f_record_player has {n_bad_source} rows with unknown source"
        )
        return False
    console.print("[green]✓[/green] f_record_player source values valid")

    # f_award_career_player: every row must have n_won > 0 (no empty rows)
    n_zero_awards = con.execute("""
        SELECT COUNT(*) FROM f_award_career_player WHERE n_won <= 0
    """).fetchone()[0]
    if n_zero_awards:
        console.print(
            f"[red]FAIL:[/red] {n_zero_awards} f_award_career_player rows have n_won <= 0"
        )
        return False
    console.print("[green]✓[/green] all f_award_career_player rows have n_won > 0")

    # f_award_franchise: same n_won > 0 invariant
    n_zero_franchise = con.execute("""
        SELECT COUNT(*) FROM f_award_franchise WHERE n_won <= 0
    """).fetchone()[0]
    if n_zero_franchise:
        console.print(
            f"[red]FAIL:[/red] {n_zero_franchise} f_award_franchise rows have n_won <= 0"
        )
        return False
    console.print("[green]✓[/green] all f_award_franchise rows have n_won > 0")

    # Idempotency
    rows_2 = build_l3(con, verbose=False)
    if rows != rows_2:
        console.print("[red]FAIL:[/red] L3 rebuild changed row counts")
        return False
    console.print("[green]✓[/green] L3 rebuild is idempotent")

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
    if not smoke_l1_snapshot(con, save, console):
        return 1
    if not smoke_l2(con, console):
        return 1
    if not smoke_l3(con, console):
        return 1

    console.rule("[bold green]All smoke tests passed[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
