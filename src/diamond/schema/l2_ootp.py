"""L2 facts mirroring OOTP-authoritative cached aggregates.

Phase 4a deliverable #2 (D40 — Audit Closure → Maximize Warehouse).

These tables don't derive anything — they surface OOTP's own pre-computed
season / career / league / player-value caches alongside our derivations
in ``l2.py`` and ``l3_advanced.py``. The Phase 4a #1 inventory
(``audit_output/l0_column_coverage.md``) flagged each of the constituent
L0 source columns as orphan (no consumer in ``src/`` or ``web/``); this
module is the consumer.

**Why a parallel L2 layer**

1. **Invariants watchdog inputs (D40 Phase 4b)** — our `wOBA` / `FIP` /
   `ERA+` / ... derivations should match OOTP's cached aggregates within
   rounding. Surfacing the cached values as named L2 columns lets the
   forthcoming `_diamond_invariants` watchdog run drift checks per
   (team, year), (player, year), (league, year, level) — no further
   warehouse work needed.

2. **API exposure of unused-but-paid-for cache** — orphan columns like
   `l0_team_history_pitching_stats.gbfbp` (GB/FB ratio %), `kbb` (K/BB
   ratio), `ws` (winning percentage), `r9`/`h9` (rate-per-9), `cgp`
   (complete-game %), `qsp` (quality-start %), the `*p` rate stats
   (`winp` / `svp` / `bsvp` / `gfp`), and the `*a` allowed-hit-type
   counts (`sa` / `da` / `ta` / `ra`) become queryable warehouse fields
   with names that match what the OOTP UI displays.

3. **Reachability for future per-team / per-player dashboards** —
   `f_player_value_current` exposes 39 orphan columns from
   `l0_players_value`: per-position OOTP-internal valuations
   (`overall_sp/rp/c/1b/2b/3b/ss/lf/cf/rf`), per-side valuations
   (`*_value_vsl/vsr`), award-trigger flags, and master rolls
   (`oa` / `oa_rating` / `pot` / `pot_rating`).

**Naming convention**

Suffix `_ootp` distinguishes these from our derivations:

  - ``f_team_season_batting`` (derived, summed across PA event)
  - ``f_team_season_batting_ootp`` (OOTP-authoritative, this module)

The orphan list per table is captured as a tuple constant
(`_*_ORPHAN_COLS`). `_assert_columns_present` runs after each build and
fails the warehouse build if a column has disappeared from the L0
upstream — that's an OOTP version-bump signal worth catching loudly.

**Grain (PK) summary**

  f_team_season_batting_ootp     PK = (team_id, year)
  f_team_season_pitching_ootp    PK = (team_id, year)
  f_team_season_fielding_ootp    PK = (team_id, year, position)

  f_player_stint_batting_ootp    PK = (player_id, year, league_id,
                                       level_id, split_id, team_id, stint)
  f_player_stint_pitching_ootp   same shape (no position dim)
  f_player_stint_fielding_ootp   PK adds position, drops stint

  f_league_season_pitching_ootp  PK = (league_id, year, level_id,
                                       team_id, game_id)
  f_league_season_fielding_ootp  PK adds position

  f_player_value_current         PK = (player_id)
                                 (passthrough of player_value_snapshot
                                 filtered to MAX(dump_date) per player)

All builders are idempotent — `CREATE OR REPLACE`. Build order is
independent of the existing `l2.py` facts; this module is wired in
after them in ``build.py``'s orchestration.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Orphan column inventories (mirror audit_output/l0_column_coverage.md)
# ─────────────────────────────────────────────────────────────────────────────
#
# Each tuple lists the columns Phase 4a #1's inventory flagged as orphan
# for the named L0 source. _assert_columns_present validates each is still
# present in the materialized fact — if OOTP drops one in a future version,
# the warehouse build fails loudly instead of silently dropping the column.

_TEAM_HISTORY_BATTING_ORPHANS = (
    "sbp",  # stolen-base %
)

_TEAM_HISTORY_PITCHING_ORPHANS = (
    # allowed-hit counts:
    "sa", "da", "ta", "ra",
    # rate stats per 9 IP:
    "r9", "h9",
    # percentage stats:
    "cgp",   # complete-game %
    "qsp",   # quality-start %
    "winp",  # win %
    "svp",   # save %
    "bsvp",  # blown-save %
    "gfp",   # games-finished %
    "pig",   # pitches-per-inning-game (?)
    "ws",    # winning %?  (OOTP "WS" header — distinct from Win Shares; per
             # DATA_NOTES TBD on exact semantic; surfaced for the watchdog)
    "gbfbp", # GB/FB ratio (as %)
    "kbb",   # K/BB ratio
)

_TEAM_HISTORY_FIELDING_ORPHANS = (
    "rtop",   # runner-thrown-out % (catcher caught-stealing %)
    "cera",   # catcher ERA (when this player caught)
)

_PLAYERS_CAREER_BATTING_ORPHANS = (
    "ubr",   # ultimate base running (OOTP-supplied)
)

_PLAYERS_CAREER_PITCHING_ORPHANS = (
    # allowed-hit counts (per-pitcher this time):
    "sa", "da", "ta", "ra",
)

_PLAYERS_CAREER_FIELDING_ORPHANS = (
    "plays_base", "roe",
    # opportunity-bucket counters (OOTP zone-rating inputs):
    "opps_0", "opps_made_0",
    "opps_1", "opps_made_1",
    "opps_2", "opps_made_2",
    "opps_3", "opps_made_3",
    "opps_4", "opps_made_4",
    "opps_5", "opps_made_5",
)

_LEAGUE_HISTORY_PITCHING_ORPHANS = (
    "sa", "da", "ta", "ra", "r9", "h9",
    "kp", "bbp", "kbbp",     # K%, BB%, K-BB%
    "cgp", "qsp", "winp",
    "svp", "bsvp", "irsp",   # inherited-runners-scored %
    "gfp", "pig", "ws",
    "gbfbp", "kbb",
)

_LEAGUE_HISTORY_FIELDING_ORPHANS = (
    "rtop", "cera",
    "plays_base", "roe", "eff",
    "opps_0", "opps_made_0",
    "opps_1", "opps_made_1",
    "opps_2", "opps_made_2",
    "opps_3", "opps_made_3",
    "opps_4", "opps_made_4",
    "opps_5", "opps_made_5",
)

_PLAYERS_SCOUTED_RATINGS_ORPHANS = (
    # bookkeeping:
    "scouting_coach_id",
    # batting overall + talent (orphan sub-cols):
    "batting_ratings_overall_hp",
    "batting_ratings_talent_hp",
    # batting vs-LHP per-tool split:
    "batting_ratings_vsl_gap",
    "batting_ratings_vsl_strikeouts",
    "batting_ratings_vsl_hp",
    "batting_ratings_vsl_babip",
    # batting vs-RHP per-tool split:
    "batting_ratings_vsr_gap",
    "batting_ratings_vsr_strikeouts",
    "batting_ratings_vsr_hp",
    "batting_ratings_vsr_babip",
    # batting hitter-type misc:
    "batting_ratings_misc_gb_hitter_type",
    "batting_ratings_misc_fb_hitter_type",
    # pitching overall (orphan sub-cols):
    "pitching_ratings_overall_balk",
    "pitching_ratings_overall_hp",
    "pitching_ratings_overall_wild_pitch",
    # pitching vs-LHB per-tool split:
    "pitching_ratings_vsl_movement",
    "pitching_ratings_vsl_hra",
    "pitching_ratings_vsl_control",
    "pitching_ratings_vsl_pbabip",
    "pitching_ratings_vsl_balk",
    "pitching_ratings_vsl_hp",
    "pitching_ratings_vsl_wild_pitch",
    # pitching vs-RHB per-tool split:
    "pitching_ratings_vsr_movement",
    "pitching_ratings_vsr_hra",
    "pitching_ratings_vsr_control",
    "pitching_ratings_vsr_pbabip",
    "pitching_ratings_vsr_balk",
    "pitching_ratings_vsr_hp",
    "pitching_ratings_vsr_wild_pitch",
    # pitching talent split orphans:
    "pitching_ratings_talent_balk",
    "pitching_ratings_talent_hp",
    "pitching_ratings_talent_wild_pitch",
    # pitching misc:
    "pitching_ratings_misc_velocity_target",
    "pitching_ratings_babip",
    # fielding ratings — catcher framing (single-stat) + per-position potential:
    "fielding_ratings_catcher_framing",
    "fielding_rating_pos1_pot", "fielding_rating_pos2_pot",
    "fielding_rating_pos3_pot", "fielding_rating_pos4_pot",
    "fielding_rating_pos5_pot", "fielding_rating_pos6_pot",
    "fielding_rating_pos7_pot", "fielding_rating_pos8_pot",
    "fielding_rating_pos9_pot",
)

_PLAYERS_VALUE_ORPHANS = (
    # offensive valuations (current + talent, per side):
    "offensive_value", "offensive_value_talent",
    "offensive_value_vsl", "offensive_value_vsr",
    # pitching valuations (current + talent, per side):
    "pitching_value", "pitching_value_talent",
    "pitching_value_vsl", "pitching_value_vsr",
    # master rolls:
    "overall_value", "talent_value", "career_value",
    # leadoff/run-game valuations:
    "leadoff_value_vsl", "leadoff_value_vsr",
    "running_value", "stealing_value",
    # season performance + 3-stage stats trajectory:
    "season_performance",
    "stats_value_0", "stats_value_1", "stats_value_2",
    "stats_mod_0", "stats_mod_1", "stats_mod_2",
    "ratings_value",
    # per-position valuations (OOTP overall by position):
    "overall_sp", "overall_rp",
    "overall_c", "overall_1b", "overall_2b", "overall_3b", "overall_ss",
    "overall_lf", "overall_cf", "overall_rf",
    # award triggers:
    "award_bat", "award_pit", "award_field",
    # OOTP "OA" (overall) + potential rolls (raw + display-scaled):
    "oa", "oa_rating", "pot_rating",
)


# ─────────────────────────────────────────────────────────────────────────────
# Schema-validation helper (run after every build to catch upstream drift)
# ─────────────────────────────────────────────────────────────────────────────


def _assert_columns_present(
    con: duckdb.DuckDBPyConnection,
    table: str,
    expected: tuple[str, ...],
) -> None:
    """Loud failure if any expected column is missing from `table`.

    Catches the case where an OOTP version-bump drops or renames an
    orphan column — surfaces as a build-time failure rather than a
    silent loss of the watchdog input.
    """
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    actual = {r[1] for r in rows}
    missing = [c for c in expected if c not in actual]
    if missing:
        raise RuntimeError(
            f"{table} is missing expected OOTP-cache columns: {missing!r}. "
            "OOTP version-bump likely changed the source CSV — update the "
            "_*_ORPHAN_COLS tuple in src/diamond/schema/l2_ootp.py."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Team-season facts (one row per team-year)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_team_season_batting_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(team_id, year) OOTP-cached batting aggregates.

    Passthrough of ``team_history_batting_event``. Carries every OOTP
    rate stat (avg/obp/slg/ops/iso/rc/rc27/woba/sbp) — most are already
    referenced from the API layer; this fact gives them a single
    addressable join key for invariants checks.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_team_season_batting_ootp AS
        SELECT * FROM team_history_batting_event
    """)
    con.execute(
        "ALTER TABLE f_team_season_batting_ootp ADD PRIMARY KEY (team_id, year)"
    )
    _assert_columns_present(
        con, "f_team_season_batting_ootp", _TEAM_HISTORY_BATTING_ORPHANS
    )
    return con.execute("SELECT COUNT(*) FROM f_team_season_batting_ootp").fetchone()[0]


def _build_f_team_season_pitching_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(team_id, year) OOTP-cached pitching aggregates.

    Passthrough of ``team_history_pitching_event``. Includes 16 orphan
    columns flagged by Phase 4a #1's inventory — see
    `_TEAM_HISTORY_PITCHING_ORPHANS`.

    Of the 16, the high-value invariants are:
    - ``fip`` (we compute our own; OOTP cache as drift check)
    - ``babip`` (same)
    - ``era`` (vs our SUM(er)*9 / SUM(ip))
    - ``whip`` (vs our SUM(bb+ha) / SUM(ip))
    - ``kbb`` (vs our SUM(k) / SUM(bb))
    - ``gbfbp`` (vs our SUM(gb) / SUM(fb))

    The percentage stats (``cgp`` / ``qsp`` / ``winp`` / ``svp`` /
    ``bsvp`` / ``gfp``) and the allowed-hit-type counts
    (``sa`` / ``da`` / ``ta`` / ``ra``) are pure OOTP — we have no
    independent derivation, so they're additive data.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_team_season_pitching_ootp AS
        SELECT * FROM team_history_pitching_event
    """)
    con.execute(
        "ALTER TABLE f_team_season_pitching_ootp ADD PRIMARY KEY (team_id, year)"
    )
    _assert_columns_present(
        con, "f_team_season_pitching_ootp", _TEAM_HISTORY_PITCHING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_team_season_pitching_ootp"
    ).fetchone()[0]


def _build_f_team_season_fielding_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(team_id, year, position) OOTP-cached fielding aggregates.

    Passthrough of ``team_history_fielding_event``. Orphan columns
    ``rtop`` (runners-thrown-out %, catchers) and ``cera`` (catcher
    ERA) are catcher-specific defensive metrics; surfacing them here
    makes them queryable for per-catcher defense leaderboards.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_team_season_fielding_ootp AS
        SELECT * FROM team_history_fielding_event
    """)
    # team_history_fielding_event PK is (team_id, year) per the L1 spec,
    # but the natural grain is (team_id, year, position). We keep the
    # passthrough PK to avoid divergence; consumers filter by `position`
    # for per-slot analysis. The L0 source has rows per position
    # already.
    con.execute(
        "ALTER TABLE f_team_season_fielding_ootp ADD PRIMARY KEY (team_id, year)"
    )
    _assert_columns_present(
        con, "f_team_season_fielding_ootp", _TEAM_HISTORY_FIELDING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_team_season_fielding_ootp"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Player-stint facts (per L1 event passthroughs)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_player_stint_batting_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-stint OOTP-cached batting rates (passthrough of L1 event).

    The natural key (player_id, year, league_id, level_id, split_id,
    team_id, stint) has OOTP-source dups in some historical rows, so
    the L1 event uses synthetic PK (dump_date, file_seq); we preserve
    that here. Captures the orphan ``ubr`` (ultimate baserunning)
    column plus the OOTP-cached ``wpa`` / ``war`` per stint.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_player_stint_batting_ootp AS
        SELECT * FROM players_career_batting_event
    """)
    con.execute(
        "ALTER TABLE f_player_stint_batting_ootp ADD PRIMARY KEY (dump_date, file_seq)"
    )
    _assert_columns_present(
        con, "f_player_stint_batting_ootp", _PLAYERS_CAREER_BATTING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_stint_batting_ootp"
    ).fetchone()[0]


def _build_f_player_stint_pitching_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-stint OOTP-cached pitching rates (passthrough of L1 event).

    Captures allowed-hit-type orphans (``sa`` / ``da`` / ``ta`` /
    ``ra``) plus the OOTP-cached ``war`` / ``ra9war`` per stint —
    these are the IE-A-tier reconciled per-stint WAR values D11
    relies on for the bWAR/pWAR aggregation in
    ``f_player_season_advanced_*``.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_player_stint_pitching_ootp AS
        SELECT * FROM players_career_pitching_event
    """)
    con.execute(
        "ALTER TABLE f_player_stint_pitching_ootp ADD PRIMARY KEY (dump_date, file_seq)"
    )
    _assert_columns_present(
        con, "f_player_stint_pitching_ootp", _PLAYERS_CAREER_PITCHING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_stint_pitching_ootp"
    ).fetchone()[0]


def _build_f_player_stint_fielding_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-stint OOTP-cached fielding (passthrough of L1 event).

    Captures the orphan ``plays_base`` + ``roe`` (reached-on-error) +
    full opportunity-bucket grid (``opps_0..5`` / ``opps_made_0..5``).
    The opps_* fields are OOTP's zone-rating inputs — six difficulty
    buckets per fielder per (year, level, league, position). Pulling
    them through to L2 unlocks zone-rating breakdowns in any future
    defense viz without re-joining L0.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_player_stint_fielding_ootp AS
        SELECT * FROM players_career_fielding_event
    """)
    con.execute(
        "ALTER TABLE f_player_stint_fielding_ootp ADD PRIMARY KEY (dump_date, file_seq)"
    )
    _assert_columns_present(
        con, "f_player_stint_fielding_ootp", _PLAYERS_CAREER_FIELDING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_player_stint_fielding_ootp"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# League-season facts (the watchdog's level/year-baseline reference)
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_league_season_pitching_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(league_id, year, level_id, team_id, game_id) OOTP-cached pitching
    league-history rows.

    Passthrough of ``league_history_pitching_event``. Captures 20
    orphan columns including ``kp`` (K%), ``bbp`` (BB%), ``kbbp``
    (K-BB%), ``irsp`` (inherited-runners-scored %), and the full
    rate-stat set already exposed at team-level.

    Aggregation to (league_id, year, level_id) is intentionally
    deferred — the L1 event preserves all dimension columns, so
    consumers can roll up to whatever grain they need. Our existing
    ``f_league_season`` already produces the (league, year, level)
    aggregates from the same source; this fact is for invariants
    checks at the lower grain.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_league_season_pitching_ootp AS
        SELECT * FROM league_history_pitching_event
    """)
    # L1 event uses synthetic (dump_date, file_seq) PK due to natural-key
    # dups; preserve that.
    con.execute(
        "ALTER TABLE f_league_season_pitching_ootp "
        "ADD PRIMARY KEY (dump_date, file_seq)"
    )
    _assert_columns_present(
        con, "f_league_season_pitching_ootp", _LEAGUE_HISTORY_PITCHING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_league_season_pitching_ootp"
    ).fetchone()[0]


def _build_f_league_season_fielding_ootp(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(league, year, level, team, position) OOTP-cached fielding rows.

    Passthrough of ``league_history_fielding_event``. Captures 17
    orphan columns including the zone-rating inputs (``opps_*`` /
    ``opps_made_*``), efficiency (``eff``), reach-on-error (``roe``),
    catcher metrics (``rtop`` / ``cera``).
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_league_season_fielding_ootp AS
        SELECT * FROM league_history_fielding_event
    """)
    con.execute(
        "ALTER TABLE f_league_season_fielding_ootp "
        "ADD PRIMARY KEY (dump_date, file_seq)"
    )
    _assert_columns_present(
        con, "f_league_season_fielding_ootp", _LEAGUE_HISTORY_FIELDING_ORPHANS
    )
    return con.execute(
        "SELECT COUNT(*) FROM f_league_season_fielding_ootp"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Player valuation (current-state snapshot at latest dump)
# ─────────────────────────────────────────────────────────────────────────────


def _build_v_player_ratings_by_side(con: duckdb.DuckDBPyConnection) -> int:
    """View enumerating per-side (vs-L/vs-R) scouted ratings + talent splits.

    Phase 4a #1 inventory flagged 45 orphan columns in
    ``l0_players_scouted_ratings`` — all per-side / per-tool rating
    splits the L1 snapshot exposes via ``SELECT *`` but no consumer
    names. This view enumerates them explicitly so:

    1. The names appear in source for grep-ability.
    2. Future API consumers (per-side splits on player page, AI prompt
       context for side-vulnerability analysis) have one named query
       target with the OOTP semantic columns surfaced.

    Sourced from ``players_ratings_current`` (latest dump, audit-team
    scouted only per D12).
    """
    con.execute("""
        CREATE OR REPLACE VIEW v_player_ratings_by_side AS
        SELECT
            player_id,
            team_id,
            position,
            role,
            dump_date,

            -- ── Batting: overall + talent ─────────────────────────────
            batting_ratings_overall_contact,
            batting_ratings_overall_gap,
            batting_ratings_overall_power,
            batting_ratings_overall_eye,
            batting_ratings_overall_strikeouts,
            batting_ratings_overall_hp,         -- HBP rating (orphan)
            batting_ratings_overall_babip,
            batting_ratings_talent_contact,
            batting_ratings_talent_gap,
            batting_ratings_talent_power,
            batting_ratings_talent_eye,
            batting_ratings_talent_strikeouts,
            batting_ratings_talent_hp,          -- HBP talent (orphan)
            batting_ratings_talent_babip,

            -- ── Batting vs LHP ────────────────────────────────────────
            batting_ratings_vsl_contact,
            batting_ratings_vsl_gap,            -- (orphan)
            batting_ratings_vsl_power,
            batting_ratings_vsl_eye,
            batting_ratings_vsl_strikeouts,     -- (orphan)
            batting_ratings_vsl_hp,             -- (orphan)
            batting_ratings_vsl_babip,          -- (orphan)

            -- ── Batting vs RHP ────────────────────────────────────────
            batting_ratings_vsr_contact,
            batting_ratings_vsr_gap,            -- (orphan)
            batting_ratings_vsr_power,
            batting_ratings_vsr_eye,
            batting_ratings_vsr_strikeouts,     -- (orphan)
            batting_ratings_vsr_hp,             -- (orphan)
            batting_ratings_vsr_babip,          -- (orphan)

            -- ── Batting hitter-type misc ──────────────────────────────
            batting_ratings_misc_bunt,
            batting_ratings_misc_bunt_for_hit,
            batting_ratings_misc_gb_hitter_type,  -- (orphan)
            batting_ratings_misc_fb_hitter_type,  -- (orphan)

            -- ── Pitching: overall + talent ────────────────────────────
            pitching_ratings_overall_stuff,
            pitching_ratings_overall_movement,
            pitching_ratings_overall_control,
            pitching_ratings_overall_hra,
            pitching_ratings_overall_pbabip,
            pitching_ratings_overall_balk,        -- (orphan)
            pitching_ratings_overall_hp,          -- (orphan)
            pitching_ratings_overall_wild_pitch,  -- (orphan)
            pitching_ratings_talent_stuff,
            pitching_ratings_talent_movement,
            pitching_ratings_talent_control,
            pitching_ratings_talent_hra,
            pitching_ratings_talent_pbabip,
            pitching_ratings_talent_balk,         -- (orphan)
            pitching_ratings_talent_hp,           -- (orphan)
            pitching_ratings_talent_wild_pitch,   -- (orphan)

            -- ── Pitching vs LHB ───────────────────────────────────────
            pitching_ratings_vsl_stuff,
            pitching_ratings_vsl_movement,        -- (orphan)
            pitching_ratings_vsl_control,         -- (orphan)
            pitching_ratings_vsl_hra,             -- (orphan)
            pitching_ratings_vsl_pbabip,          -- (orphan)
            pitching_ratings_vsl_balk,            -- (orphan)
            pitching_ratings_vsl_hp,              -- (orphan)
            pitching_ratings_vsl_wild_pitch,      -- (orphan)

            -- ── Pitching vs RHB ───────────────────────────────────────
            pitching_ratings_vsr_stuff,
            pitching_ratings_vsr_movement,        -- (orphan)
            pitching_ratings_vsr_control,         -- (orphan)
            pitching_ratings_vsr_hra,             -- (orphan)
            pitching_ratings_vsr_pbabip,          -- (orphan)
            pitching_ratings_vsr_balk,            -- (orphan)
            pitching_ratings_vsr_hp,              -- (orphan)
            pitching_ratings_vsr_wild_pitch,      -- (orphan)

            -- ── Pitching misc ─────────────────────────────────────────
            pitching_ratings_misc_velocity,
            pitching_ratings_misc_velocity_target,  -- (orphan)
            pitching_ratings_misc_arm_slot,
            pitching_ratings_misc_stamina,
            pitching_ratings_misc_ground_fly,
            pitching_ratings_misc_hold,
            pitching_ratings_babip,                 -- (orphan)

            -- ── Fielding overall + per-position rating + potential ────
            fielding_ratings_catcher_framing,       -- (orphan)
            fielding_rating_pos1_pot,               -- (orphan)
            fielding_rating_pos2_pot,               -- (orphan)
            fielding_rating_pos3_pot,               -- (orphan)
            fielding_rating_pos4_pot,               -- (orphan)
            fielding_rating_pos5_pot,               -- (orphan)
            fielding_rating_pos6_pot,               -- (orphan)
            fielding_rating_pos7_pot,               -- (orphan)
            fielding_rating_pos8_pot,               -- (orphan)
            fielding_rating_pos9_pot,               -- (orphan)

            -- ── Bookkeeping ───────────────────────────────────────────
            scouting_coach_id,                      -- (orphan)
            scouting_accuracy
        FROM players_ratings_current
    """)
    return con.execute(
        "SELECT COUNT(*) FROM v_player_ratings_by_side"
    ).fetchone()[0]


def _build_f_player_value_current(con: duckdb.DuckDBPyConnection) -> int:
    """Latest-dump OOTP-cached player valuations (one row per scoped player).

    Passthrough of ``player_value_snapshot`` filtered to the latest
    ``dump_date`` per player. Surfaces 39 orphan columns:

    - **per-side current/talent valuations**: ``offensive_value{,_talent,_vsl,_vsr}``,
      ``pitching_value{,_talent,_vsl,_vsr}``,
      ``leadoff_value_vsl/vsr``, ``running_value``, ``stealing_value``
    - **master rolls**: ``overall_value``, ``talent_value``, ``career_value``
    - **season trajectory**: ``season_performance``,
      ``stats_value_{0,1,2}`` (3-segment trajectory),
      ``stats_mod_{0,1,2}`` (modifiers per segment)
    - **per-position OOTP-internal overall**: ``overall_{sp,rp,c,1b,2b,3b,ss,lf,cf,rf}``
    - **award-trigger flags**: ``award_bat``, ``award_pit``, ``award_field``
    - **OA / potential rolls**: ``oa``, ``oa_rating``, ``pot``, ``pot_rating``

    These feed forthcoming Phase 4b/5 surfaces:
    - "best ROIC / overpay" leaderboards (career_value vs contract)
    - "position fit" cards on the player page
    - per-side talent splits on roster tables
    - AI prompt context: spotlight cards can cite OOTP's own master
      rolls instead of re-deriving them.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_player_value_current AS
        SELECT pv.*
        FROM player_value_snapshot pv
        WHERE pv.dump_date = (
            SELECT MAX(dump_date) FROM player_value_snapshot
        )
    """)
    con.execute(
        "ALTER TABLE f_player_value_current ADD PRIMARY KEY (player_id)"
    )
    _assert_columns_present(
        con, "f_player_value_current", _PLAYERS_VALUE_ORPHANS
    )
    return con.execute("SELECT COUNT(*) FROM f_player_value_current").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l2_ootp(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build every OOTP-cache passthrough fact.

    Called after ``build_l2()`` — depends on L1 event + snapshot tables
    only, no L2 dependencies.

    Returns dict of ``{fact_name: row_count}``.
    """
    rows: dict[str, int] = {}

    builders = [
        ("f_team_season_batting_ootp",     _build_f_team_season_batting_ootp),
        ("f_team_season_pitching_ootp",    _build_f_team_season_pitching_ootp),
        ("f_team_season_fielding_ootp",    _build_f_team_season_fielding_ootp),
        ("f_player_stint_batting_ootp",    _build_f_player_stint_batting_ootp),
        ("f_player_stint_pitching_ootp",   _build_f_player_stint_pitching_ootp),
        ("f_player_stint_fielding_ootp",   _build_f_player_stint_fielding_ootp),
        ("f_league_season_pitching_ootp",  _build_f_league_season_pitching_ootp),
        ("f_league_season_fielding_ootp",  _build_f_league_season_fielding_ootp),
        ("f_player_value_current",         _build_f_player_value_current),
        ("v_player_ratings_by_side",       _build_v_player_ratings_by_side),
    ]

    for name, fn in builders:
        n = fn(con)
        rows[name] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {name:<36} [dim]{n:>10,} rows[/dim]"
            )

    return rows
