"""L0 catalog — which CSV maps to which `l0_*` table.

L0 is a per-dump provenance archive. Each table is a typed copy of one CSV
plus three admin columns:

    dump_date   DATE        -- 1st of the month derived from `dump_YYYY_MM/`
    ingest_ts   TIMESTAMP   -- when the row was loaded
    file_seq    BIGINT      -- the row's position in the source CSV (1-indexed)

`file_seq` matters operationally because `players_at_bat_batting_stats.csv`
is grouped by batter and within `(game_id, player_id)` the file order is
chronological. L1 uses `ROW_NUMBER() OVER (PARTITION BY game_id, player_id
ORDER BY file_seq)` to derive `pa_in_game_seq` (per OPEN-4 resolution).

Per Decision D12, `players_scouted_ratings.csv` lands at L0 unfiltered
(provenance — every team's view of every player), then the L0→L1 builder
drops `scouting_team_id = 0` rows so the objective rating never reaches
the product.

Per OPEN-1 resolution, `players_pitching.csv` is **skipped entirely** —
0 of 67 rating columns are populated; it's a stub.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class L0Spec:
    """One CSV → one L0 table."""

    csv_name: str           # without .csv extension; e.g., "players"
    notes: str = ""

    @property
    def l0_table(self) -> str:
        return f"l0_{self.csv_name}"


# Source CSVs that we deliberately do NOT ingest — see SCHEMA.md OPEN-1.
L0_SKIP: list[str] = [
    "players_pitching",
    # players_pitching.csv has 0 of 67 rating columns populated for any of the
    # 148K rows; it's a schema-only stub. The canonical pitching ratings live
    # in players_scouted_ratings.
]


# The 69 CSVs we ingest. Order is alphabetical for predictability — DuckDB
# doesn't care about creation order at L0 (no FKs).
L0_CATALOG: list[L0Spec] = [
    # — Reference geography & i18n (small, mostly-static) —
    L0Spec("cities"),
    L0Spec("continents"),
    L0Spec("languages",
           notes="40 rows. Reference: language_id → name."),
    L0Spec("language_data",
           notes="374 rows. Geo→language demographic mix; "
                 "renamed to `geo_languages` at L1."),
    L0Spec("nations"),
    L0Spec("states"),

    # — League/team org tree —
    L0Spec("divisions"),
    L0Spec("leagues"),
    L0Spec("parks"),
    L0Spec("sub_leagues"),
    L0Spec("team_affiliations"),
    L0Spec("team_relations"),
    L0Spec("teams"),

    # — Coaches & user (manager) —
    L0Spec("coaches"),
    L0Spec("human_managers"),
    L0Spec("human_manager_history"),
    L0Spec("human_manager_history_batting_stats"),
    L0Spec("human_manager_history_fielding_stats_stats"),
    L0Spec("human_manager_history_financials"),
    L0Spec("human_manager_history_pitching_stats"),
    L0Spec("human_manager_history_record"),

    # — Games & at-bats (event) —
    L0Spec("games"),
    L0Spec("games_score"),
    L0Spec("players_at_bat_batting_stats",
           notes="1.3M PA log. CSV is grouped by batter; `file_seq` is "
                 "load-bearing for L1's pa_in_game_seq derivation per OPEN-4."),
    L0Spec("players_game_batting"),
    L0Spec("players_game_pitching_stats"),

    # — Per-player season stats (event) —
    L0Spec("players_career_batting_stats"),
    L0Spec("players_career_fielding_stats"),
    L0Spec("players_career_pitching_stats"),
    L0Spec("players_individual_batting_stats"),

    # — Per-player events —
    L0Spec("players_awards"),
    L0Spec("players_injury_history"),
    L0Spec("players_league_leader"),
    L0Spec("players_salary_history"),
    L0Spec("players_streak",
           notes="L1 PK is (player_id, league_id, streak_id, started, "
                 "COALESCE(ended, '9999-12-31')) — see OPEN-5."),
    L0Spec("trade_history"),

    # — Per-player state snapshots —
    L0Spec("players",
           notes="Bio + current team + ratings rollup. The state-snapshot "
                 "diff across dumps is what drives `player_movements`."),
    L0Spec("players_batting",
           notes="OPEN-1: only `running_ratings_*` (4 of 42 cols) populated; "
                 "the 30+ batting-rating cols are zero. L1 folds the 4 useful "
                 "cols into the players snapshot rather than keeping a "
                 "separate rating snapshot."),
    L0Spec("players_contract"),
    L0Spec("players_contract_extension"),
    L0Spec("players_fielding",
           notes="OPEN-1: 27 useful cols (per-position experience + per-position "
                 "rating + potential). The experience cols are unique to this "
                 "file. L1 keeps as `players_fielding_snapshot`."),
    L0Spec("players_roster_status"),
    L0Spec("players_scouted_ratings",
           notes="D12: scouting_team_id=0 (objective rating) is dropped at "
                 "L0→L1, never exposed downstream. L0 retains it for provenance."),
    L0Spec("players_value"),
    L0Spec("projected_starting_pitchers"),

    # — League history (event) —
    L0Spec("league_events"),
    L0Spec("league_history"),
    L0Spec("league_history_all_star"),
    L0Spec("league_history_batting_stats",
           notes="Source for `league_constants` (D11). Already consumed by "
                 "the `lg_constants_bat` view in src/diamond/league_constants.py."),
    L0Spec("league_history_fielding_stats"),
    L0Spec("league_history_pitching_stats",
           notes="Source for `league_constants`."),
    L0Spec("league_playoffs"),
    L0Spec("league_playoff_fixtures"),

    # — Team history (event) —
    L0Spec("team_history"),
    L0Spec("team_history_batting_stats"),
    L0Spec("team_history_fielding_stats_stats"),
    L0Spec("team_history_financials"),
    L0Spec("team_history_pitching_stats"),
    L0Spec("team_history_record"),

    # — Team current-state snapshots —
    L0Spec("team_batting_stats"),
    L0Spec("team_bullpen_pitching_stats"),
    L0Spec("team_fielding_stats_stats"),
    L0Spec("team_financials"),
    L0Spec("team_last_financials"),
    L0Spec("team_pitching_stats"),
    L0Spec("team_record"),
    L0Spec("team_roster"),
    L0Spec("team_roster_staff"),
    L0Spec("team_starting_pitching_stats"),
]


def _validate_catalog() -> None:
    """Assert no duplicates and no overlap with the skip list."""
    names = [s.csv_name for s in L0_CATALOG]
    assert len(names) == len(set(names)), (
        f"L0_CATALOG has duplicates: {[n for n in names if names.count(n) > 1]}"
    )
    overlap = set(names) & set(L0_SKIP)
    assert not overlap, f"L0_CATALOG and L0_SKIP overlap on {overlap}"


_validate_catalog()
