"""L3 derived tables — model-driven analytical surfaces built on L1 + L2.

Currently exposes:

  - f_trade_participant       long-format trade roster, 1 row per (trade × player)
  - player_movements          timeline of every team change, attributed to trades
                              where applicable
  - f_draft_class             one row per drafted player, joining current status
                              + made-MLB outcome + cumulative MLB career stats
  - f_record_player           top-25 leaderboard rows per (scope × discipline ×
                              category) across all-time MLB single-season + career
                              counting stats
  - f_award_career_player     career award totals per player (1 row per player×award)
  - f_award_franchise         franchise award totals per (team × award)
                              (team_id captured at the time of winning)

Future L3 builders that will live here:

  - park_factors                    — halved-park-factor materialization
  - f_player_season_advanced_*      — wOBA / wRC+ / FIP / SIERA per season
  - streak_history                  — decoded streak rows with names

Build pattern: L3 tables are full DROP/CREATE on every ingest (cheap; the
warehouse fits in memory). They depend on L1 / L2 already being current.

Build order matters:
  - `f_trade_participant` builds before `player_movements` (the latter
    LEFT JOINs to it for trade attribution)
  - `f_draft_class` builds AFTER `player_movements` (it consumes the
    `to_level_id=1` movements to derive `first_mlb_date`)

Records / awards / HoF: pure derivations off L2 facts + L1 reference tables.
Records and awards live as L3 tables; HoF surfaces directly from
`players_current` and joins to `f_award_event` at query time.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# f_trade_participant
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_trade_participant(con: duckdb.DuckDBPyConnection) -> int:
    """Long-format roster of every player who changed hands in a trade.

    `trade_event` stores each trade as one wide row with up to 10 player
    slots per side (`player_id_0_0..9`, `player_id_1_0..9`). This pivots
    that into one row per (trade × player), making downstream joins
    straightforward — particularly the `trade_id` attribution back into
    `player_movements`.

    Schema:
        trade_id     BIGINT  — `trade_event.message_id` (one per trade)
        trade_date   DATE
        player_id    BIGINT
        from_org_id  BIGINT  — MLB-level team the player was traded FROM
        to_org_id    BIGINT  — MLB-level team the player was traded TO
        side         INTEGER — 0 (was on team_id_0) or 1 (was on team_id_1)

    PK = (trade_id, player_id). Each player appears on at most one side
    of a given trade.

    Cash, draft picks, and IAFA cap are intentionally excluded — this is
    the *player*-participant surface. Add `f_trade_pick` etc. later if
    we ever want pick-flow analysis.
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_trade_participant AS
        WITH side_0 AS (
            SELECT
                message_id  AS trade_id,
                date        AS trade_date,
                team_id_0   AS from_org_id,
                team_id_1   AS to_org_id,
                CAST(0 AS INTEGER) AS side,
                player_id
            FROM trade_event,
                 UNNEST([
                     player_id_0_0, player_id_0_1, player_id_0_2, player_id_0_3,
                     player_id_0_4, player_id_0_5, player_id_0_6, player_id_0_7,
                     player_id_0_8, player_id_0_9
                 ]) AS t(player_id)
            WHERE player_id > 0
        ),
        side_1 AS (
            SELECT
                message_id, date,
                team_id_1, team_id_0,
                CAST(1 AS INTEGER),
                player_id
            FROM trade_event,
                 UNNEST([
                     player_id_1_0, player_id_1_1, player_id_1_2, player_id_1_3,
                     player_id_1_4, player_id_1_5, player_id_1_6, player_id_1_7,
                     player_id_1_8, player_id_1_9
                 ]) AS t(player_id)
            WHERE player_id > 0
        )
        SELECT * FROM side_0
        UNION ALL
        SELECT * FROM side_1
    """)
    con.execute(
        "ALTER TABLE f_trade_participant ADD PRIMARY KEY (trade_id, player_id)"
    )
    return con.execute("SELECT COUNT(*) FROM f_trade_participant").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# player_movements
# ─────────────────────────────────────────────────────────────────────────────


def _build_player_movements(con: duckdb.DuckDBPyConnection) -> int:
    """Derive `player_movements` from snapshot diffs + draft data.

    Two sources are emitted:

      1. **snapshot_diff**: compare consecutive (player_id, dump_date) rows
         of `players_snapshot`; emit a row each time `team_id` or `retired`
         changes.
      2. **draft**: one row per player whose `draft_team_id > 0`, recorded
         at the first dump_date we saw them. Captures both pre-save
         imported draftees (HoF members, historical legends) and in-save
         draft classes.

    Movement types (11 total):
      - `first_appearance`   first dump in which we observed this player
      - `drafted`            from the draft source (one per drafted player)
      - `signed`             from no team (0) to a team
      - `released`           from a team to no team (0)
      - `retired`            retired flag turned on
      - `unretired`          retired flag turned off
      - `trade`              team change matched to a `trade_event` (carries `trade_id`)
      - `promotion`          team change within same MLB org, level moved CLOSER to MLB
                             (e.g., AAA level=2 → MLB level=1)
      - `demotion`           team change within same org, level moved FARTHER from MLB
      - `intra_org_lateral`  team change within same org at the same level
      - `waiver_or_other`    team change between orgs with no trade attribution
                             (waiver claim / non-trade transfer)

    Trade attribution: rows initially flagged as a generic team change are
    LEFT JOINed to `f_trade_participant`. A match requires player_id +
    org-rolled-up from/to teams + a ±60-day date window. ~2.5% of all team
    changes resolve to a trade; ~99.8% of trade participants get matched.
    Three structural caveats:

      - Org match uses `parent_team_id` to roll AAA/AA/A/etc. teams up to
        their MLB parent, since trades are recorded at MLB-org level but
        the actual player snapshot may show a farm-team `team_id`.
      - Window is ±60 days around `dump_date_observed`. Dumps are labeled
        with the 1st of the month but capture end-of-month state, so a
        trade on the 30th typically shows up in the dump labeled the 1st
        of that same month.
      - `trade_id` is `NULL` for non-trade rows (promotion/demotion/etc.).

    Level lookup: joins `teams` on `team_id` to read the `level` column,
    yielding `from_level_id` and `to_level_id`. These also drive the
    promotion/demotion classification (lower level_id = closer to MLB).
    """
    con.execute("""
        CREATE OR REPLACE TABLE player_movements AS
        WITH ordered AS (
            -- One row per (player, dump) with prev-state cols for diffing
            SELECT
                player_id,
                dump_date,
                team_id,
                retired,
                LAG(team_id) OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS prev_team_id,
                LAG(retired) OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS prev_retired,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id ORDER BY dump_date
                ) AS row_num
            FROM players_snapshot
        ),
        diffs AS (
            -- Emit one row per actual transition. row_num=1 is "first time
            -- we ever saw this player" → first_appearance. Subsequent rows
            -- only emit if team_id or retired changed.
            SELECT
                player_id,
                dump_date AS dump_date_observed,
                prev_team_id AS from_team_id,
                team_id AS to_team_id,
                CASE
                    WHEN row_num = 1 THEN 'first_appearance'
                    WHEN prev_retired = 0 AND retired = 1 THEN 'retired'
                    WHEN prev_retired = 1 AND retired = 0 THEN 'unretired'
                    WHEN COALESCE(prev_team_id, 0) = 0 AND team_id > 0 THEN 'signed'
                    WHEN prev_team_id > 0 AND team_id = 0 THEN 'released'
                    WHEN prev_team_id != team_id THEN 'team_change'
                    ELSE NULL
                END AS movement_type
            FROM ordered
            WHERE row_num = 1
               OR COALESCE(prev_team_id, -1) != COALESCE(team_id, -1)
               OR COALESCE(prev_retired, -1) != COALESCE(retired, -1)
        ),
        snapshot_movements AS (
            SELECT
                d.player_id,
                d.dump_date_observed,
                d.movement_type,
                d.from_team_id,
                d.to_team_id,
                tf.level AS from_level_id,
                tt.level AS to_level_id,
                'snapshot_diff' AS source,
                CAST(NULL AS INTEGER) AS draft_year,
                CAST(NULL AS INTEGER) AS draft_round,
                CAST(NULL AS INTEGER) AS draft_overall_pick
            FROM diffs d
            LEFT JOIN teams tf ON tf.team_id = d.from_team_id
            LEFT JOIN teams tt ON tt.team_id = d.to_team_id
            WHERE d.movement_type IS NOT NULL
        ),
        draft_first_seen AS (
            -- For draft events, take each scoped player's earliest snapshot
            -- where draft_team_id is populated.  draft_year + draft_team_id
            -- are stamped per player and stable across dumps (drafts don't
            -- get rescinded in OOTP), so MIN(dump_date) is fine.
            SELECT
                player_id,
                MIN(dump_date) AS dump_date_observed,
                ANY_VALUE(draft_year)         AS draft_year,
                ANY_VALUE(draft_team_id)      AS draft_team_id,
                ANY_VALUE(draft_round)        AS draft_round,
                ANY_VALUE(draft_overall_pick) AS draft_overall_pick
            FROM players_snapshot
            WHERE draft_year > 0 AND draft_team_id > 0
            GROUP BY player_id
        ),
        draft_movements AS (
            SELECT
                d.player_id,
                d.dump_date_observed,
                'drafted' AS movement_type,
                CAST(NULL AS INTEGER) AS from_team_id,
                d.draft_team_id AS to_team_id,
                CAST(NULL AS INTEGER) AS from_level_id,
                tt.level AS to_level_id,
                'draft' AS source,
                d.draft_year,
                d.draft_round,
                d.draft_overall_pick
            FROM draft_first_seen d
            LEFT JOIN teams tt ON tt.team_id = d.draft_team_id
        ),
        all_movements AS (
            SELECT * FROM snapshot_movements
            UNION ALL
            SELECT * FROM draft_movements
        ),
        -- Roll farm-team team_ids up to their MLB-org team_id for trade matching.
        -- A trade between Boston (4) and Cleveland (10) moves players whose
        -- snapshot may show them on Worcester (35, parent=4) or Akron etc.
        team_orgs AS (
            SELECT team_id,
                   COALESCE(NULLIF(parent_team_id, 0), team_id) AS org_id
            FROM teams
        ),
        -- LEFT JOIN team_change rows to f_trade_participant; pick the
        -- single best-matching trade (closest by date) when there's any
        -- ambiguity. Org-rolled from-team and to-team must both line up
        -- with the trade sides; observation must be within 60 days of
        -- the trade date (dumps label as 1st-of-month but capture
        -- end-of-month state, so a trade on the 30th of a month shows
        -- up in the dump labeled the 1st of that same month).
        attributed AS (
            SELECT
                m.*,
                fo.org_id AS from_org_id,
                t_.org_id AS to_org_id,
                tp.trade_id,
                ROW_NUMBER() OVER (
                    PARTITION BY m.player_id, m.dump_date_observed,
                                 m.from_team_id, m.to_team_id
                    ORDER BY ABS(tp.trade_date - m.dump_date_observed) NULLS LAST
                ) AS _rn
            FROM all_movements m
            LEFT JOIN team_orgs fo ON fo.team_id = m.from_team_id
            LEFT JOIN team_orgs t_ ON t_.team_id = m.to_team_id
            LEFT JOIN f_trade_participant tp
                   ON m.movement_type = 'team_change'
                  AND tp.player_id    = m.player_id
                  AND tp.from_org_id  = fo.org_id
                  AND tp.to_org_id    = t_.org_id
                  AND tp.trade_date BETWEEN m.dump_date_observed - INTERVAL '60' DAY
                                        AND m.dump_date_observed + INTERVAL '60' DAY
        )
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY player_id, dump_date_observed, source
            ) AS movement_id,
            player_id,
            dump_date_observed,
            -- Refine the generic 'team_change' label into trade /
            -- promotion / demotion / intra_org_lateral / waiver_or_other
            -- using the org-rollup + level + trade_id we now have.
            CASE
                WHEN movement_type != 'team_change' THEN movement_type
                WHEN trade_id IS NOT NULL                                       THEN 'trade'
                WHEN from_org_id = to_org_id AND to_level_id < from_level_id    THEN 'promotion'
                WHEN from_org_id = to_org_id AND to_level_id > from_level_id    THEN 'demotion'
                WHEN from_org_id = to_org_id                                    THEN 'intra_org_lateral'
                ELSE 'waiver_or_other'
            END AS movement_type,
            from_team_id,
            to_team_id,
            from_level_id,
            to_level_id,
            source,
            draft_year,
            draft_round,
            draft_overall_pick,
            trade_id
        FROM attributed
        WHERE _rn = 1
    """)
    con.execute(
        "ALTER TABLE player_movements ADD PRIMARY KEY (movement_id)"
    )
    return con.execute("SELECT COUNT(*) FROM player_movements").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# f_draft_class
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_draft_class(con: duckdb.DuckDBPyConnection) -> int:
    """One row per drafted player. Joins current status, made-MLB outcome,
    and cumulative MLB career stats (combined batter + pitcher WAR).

    Sources:
      - `players_current`               draft metadata + current state
      - `player_movements`              first promotion to level=1 (MLB)
      - `players_career_batting_event`  career MLB PA / WAR (level_id=1)
      - `players_career_pitching_event` career MLB IP / WAR (level_id=1)
      - `teams` × 2                     draft-team and current-team names

    Sanity-checked 2026-05-06: all 4 draft classes (2026–2029) retain
    100% of their drafted players in `players_current`. Released and
    retired draftees stick around in the snapshot, so this table
    captures the entire class without survivorship loss. See
    DATA_NOTES.md "f_draft_class — player retention" for the probe.

    Schema:
        player_id           BIGINT
        first_name, last_name VARCHAR
        position            BIGINT     1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS,
                                       7=LF, 8=CF, 9=RF, 10=DH
        bats, throws        BIGINT     1=R, 2=L, 3=S
        date_of_birth       DATE
        draft_age           INTEGER    draft_year - YEAR(date_of_birth)
        college             BIGINT     1=college, 0=HS/intl
        draft_year          INTEGER
        draft_round         INTEGER
        draft_overall_pick  INTEGER
        draft_supplemental  BIGINT     0/1
        draft_team_id       BIGINT
        draft_team_name     VARCHAR
        current_team_id     BIGINT     0 = unsigned/released
        current_team_name   VARCHAR
        current_level_id    BIGINT     1=MLB, 2=AAA, ..., NULL if FA
        current_org_id      BIGINT     parent-team rollup of current team
        retired             BIGINT     0/1
        free_agent          BIGINT     0/1
        ever_made_mlb       BOOLEAN
        first_mlb_date      DATE       NULL if never reached MLB
        years_since_draft   INTEGER    based on latest dump_date
        mlb_g, mlb_pa       BIGINT     batter career counting (level=1)
        mlb_h, mlb_hr       BIGINT
        mlb_war_bat         DOUBLE
        mlb_g_pit, mlb_outs BIGINT     pitcher career counting (level=1)
        mlb_w, mlb_l, mlb_s BIGINT
        mlb_war_pit         DOUBLE
        career_mlb_war      DOUBLE     mlb_war_bat + mlb_war_pit (sum)
        outcome             VARCHAR    derived bucket — see below

    The `outcome` bucket is a quick at-a-glance status:
      - `mlb_star`        ever made MLB AND career_mlb_war >= 5.0
      - `mlb_regular`     ever made MLB AND career_mlb_war >= 1.0
      - `mlb_callup`      ever made MLB AND career_mlb_war < 1.0
      - `in_draft_org`    never made MLB, still in original org
      - `traded_away`     never made MLB, now in different org
      - `released`        never made MLB, no team
      - `retired`         retired flag set
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_draft_class AS
        WITH first_mlb AS (
            -- First time the player actually arrived on an MLB roster.
            -- Excludes `drafted` movements: those synthesize to_team_id =
            -- draft_team (always MLB-level), which would falsely flag
            -- every drafted player as "ever made MLB" on draft day. The
            -- player's genuine MLB debut shows up as a later promotion /
            -- first_appearance / signed / trade / waiver_or_other row.
            SELECT player_id, MIN(dump_date_observed) AS first_mlb_date
            FROM player_movements
            WHERE to_level_id = 1
              AND movement_type != 'drafted'
            GROUP BY player_id
        ),
        career_mlb_bat AS (
            SELECT
                player_id,
                SUM(g)   AS mlb_g,
                SUM(pa)  AS mlb_pa,
                SUM(h)   AS mlb_h,
                SUM(hr)  AS mlb_hr,
                SUM(war) AS mlb_war_bat
            FROM players_career_batting_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        career_mlb_pit AS (
            SELECT
                player_id,
                SUM(g)    AS mlb_g_pit,
                SUM(outs) AS mlb_outs,
                SUM(w)    AS mlb_w,
                SUM(l)    AS mlb_l,
                SUM(s)    AS mlb_s,
                SUM(war)  AS mlb_war_pit
            FROM players_career_pitching_event
            WHERE level_id = 1 AND split_id = 1
            GROUP BY player_id
        ),
        team_orgs AS (
            SELECT team_id,
                   COALESCE(NULLIF(parent_team_id, 0), team_id) AS org_id
            FROM teams
        ),
        latest_dump AS (
            SELECT MAX(dump_date) AS dd FROM players_snapshot
        )
        SELECT
            pc.player_id,
            pc.first_name,
            pc.last_name,
            pc.position,
            pc.bats,
            pc.throws,
            pc.date_of_birth,
            CAST(pc.draft_year - EXTRACT(YEAR FROM pc.date_of_birth) AS INTEGER) AS draft_age,
            pc.college,
            CAST(pc.draft_year AS INTEGER)         AS draft_year,
            CAST(pc.draft_round AS INTEGER)        AS draft_round,
            CAST(pc.draft_overall_pick AS INTEGER) AS draft_overall_pick,
            pc.draft_supplemental,
            pc.draft_team_id,
            dt.name AS draft_team_name,
            pc.team_id AS current_team_id,
            ct.name AS current_team_name,
            ct.level AS current_level_id,
            curr_org.org_id AS current_org_id,
            pc.retired,
            pc.free_agent,
            (fm.first_mlb_date IS NOT NULL) AS ever_made_mlb,
            fm.first_mlb_date,
            CAST(EXTRACT(YEAR FROM (SELECT dd FROM latest_dump)) - pc.draft_year AS INTEGER)
                AS years_since_draft,
            COALESCE(cb.mlb_g,    0) AS mlb_g,
            COALESCE(cb.mlb_pa,   0) AS mlb_pa,
            COALESCE(cb.mlb_h,    0) AS mlb_h,
            COALESCE(cb.mlb_hr,   0) AS mlb_hr,
            COALESCE(cb.mlb_war_bat, 0.0) AS mlb_war_bat,
            COALESCE(cp.mlb_g_pit, 0) AS mlb_g_pit,
            COALESCE(cp.mlb_outs, 0)  AS mlb_outs,
            COALESCE(cp.mlb_w,    0)  AS mlb_w,
            COALESCE(cp.mlb_l,    0)  AS mlb_l,
            COALESCE(cp.mlb_s,    0)  AS mlb_s,
            COALESCE(cp.mlb_war_pit, 0.0) AS mlb_war_pit,
            COALESCE(cb.mlb_war_bat, 0.0) + COALESCE(cp.mlb_war_pit, 0.0) AS career_mlb_war,
            CASE
                WHEN pc.retired = 1                                   THEN 'retired'
                WHEN fm.first_mlb_date IS NOT NULL
                     AND COALESCE(cb.mlb_war_bat, 0) + COALESCE(cp.mlb_war_pit, 0) >= 5.0
                                                                      THEN 'mlb_star'
                WHEN fm.first_mlb_date IS NOT NULL
                     AND COALESCE(cb.mlb_war_bat, 0) + COALESCE(cp.mlb_war_pit, 0) >= 1.0
                                                                      THEN 'mlb_regular'
                WHEN fm.first_mlb_date IS NOT NULL                    THEN 'mlb_callup'
                WHEN pc.team_id = 0                                   THEN 'released'
                WHEN curr_org.org_id = draft_org.org_id                THEN 'in_draft_org'
                ELSE 'traded_away'
            END AS outcome
        FROM players_current pc
        LEFT JOIN teams dt        ON dt.team_id      = pc.draft_team_id
        LEFT JOIN teams ct        ON ct.team_id      = pc.team_id
        LEFT JOIN team_orgs draft_org ON draft_org.team_id = pc.draft_team_id
        LEFT JOIN team_orgs curr_org  ON curr_org.team_id  = pc.team_id
        LEFT JOIN first_mlb fm    ON fm.player_id    = pc.player_id
        LEFT JOIN career_mlb_bat cb ON cb.player_id  = pc.player_id
        LEFT JOIN career_mlb_pit cp ON cp.player_id  = pc.player_id
        WHERE pc.draft_year > 0 AND pc.draft_team_id > 0
    """)
    con.execute(
        "ALTER TABLE f_draft_class ADD PRIMARY KEY (player_id)"
    )
    return con.execute("SELECT COUNT(*) FROM f_draft_class").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# f_record_player — top-25 leaderboards per category
# ─────────────────────────────────────────────────────────────────────────────


# (scope, discipline, category, save_value_col, save_cte, lahman_value_col)
# Lahman col missing → only save data contributes (e.g. WAR — not in Lahman).
# Statcast categories live in STATCAST_CATEGORIES below — no save-side
# equivalent for those (OOTP per-PA EV is on a different scale).
# Sort direction is always DESC for v1 (counting stats only, "more is better").
# Scope to MLB (league_id=203, level_id=1, split_id=1) for save data, and
# Lahman lgID IN ('AL', 'NL') for the historical side.
RECORD_CATEGORIES: list[tuple[str, str, str, str, str, str | None]] = [
    # ──────────────── single-season batting ─────────────────
    ("season", "batting", "HR",  "hr",  "season_bat", "hr"),
    ("season", "batting", "RBI", "rbi", "season_bat", "rbi"),
    ("season", "batting", "R",   "r",   "season_bat", "r"),
    ("season", "batting", "H",   "h",   "season_bat", "h"),
    ("season", "batting", "BB",  "bb",  "season_bat", "bb"),
    ("season", "batting", "SB",  "sb",  "season_bat", "sb"),
    ("season", "batting", "2B",  "d",   "season_bat", "d"),
    ("season", "batting", "3B",  "t",   "season_bat", "t"),
    ("season", "batting", "PA",  "pa",  "season_bat", "pa"),
    ("season", "batting", "WAR", "war", "season_bat", None),     # Lahman has no WAR
    # ──────────────── career batting ────────────────────────
    ("career", "batting", "HR",  "hr",  "career_bat", "hr"),
    ("career", "batting", "RBI", "rbi", "career_bat", "rbi"),
    ("career", "batting", "R",   "r",   "career_bat", "r"),
    ("career", "batting", "H",   "h",   "career_bat", "h"),
    ("career", "batting", "BB",  "bb",  "career_bat", "bb"),
    ("career", "batting", "SB",  "sb",  "career_bat", "sb"),
    ("career", "batting", "PA",  "pa",  "career_bat", "pa"),
    ("career", "batting", "WAR", "war", "career_bat", None),
    # ──────────────── single-season pitching ────────────────
    ("season", "pitching", "W",   "w",    "season_pit", "w"),
    ("season", "pitching", "S",   "s",    "season_pit", "sv"),
    ("season", "pitching", "K",   "k",    "season_pit", "so"),
    ("season", "pitching", "IP",  "outs", "season_pit", "ipouts"),
    ("season", "pitching", "SHO", "sho",  "season_pit", "sho"),
    ("season", "pitching", "CG",  "cg",   "season_pit", "cg"),
    ("season", "pitching", "QS",  "qs",   "season_pit", None),    # Lahman has no QS
    ("season", "pitching", "WAR", "war",  "season_pit", None),
    # ──────────────── career pitching ───────────────────────
    ("career", "pitching", "W",   "w",    "career_pit", "w"),
    ("career", "pitching", "S",   "s",    "career_pit", "sv"),
    ("career", "pitching", "K",   "k",    "career_pit", "so"),
    ("career", "pitching", "IP",  "outs", "career_pit", "ipouts"),
    ("career", "pitching", "SHO", "sho",  "career_pit", "sho"),
    ("career", "pitching", "CG",  "cg",   "career_pit", "cg"),
    ("career", "pitching", "WAR", "war",  "career_pit", None),
]


# Statcast batting record categories — source = 'statcast'. Single-season
# values come straight from `history_statcast_batting_season`. Career
# values are per-player MAX (peak power / distance) over all seasons in
# the historical window — not weighted-averaged rate stats, since rate
# stats need PA gates that are awkward across multi-year careers.
#
# tuple shape: (scope, category, statcast_col, transform_sql)
# transform_sql can be None for direct passthrough.
STATCAST_BATTING_CATEGORIES: list[tuple[str, str, str, str]] = [
    # ──────────── single-season batting (Statcast) ────────────
    ("season", "MAX_EV",          "max_hit_speed",          "MAX(max_hit_speed)"),
    ("season", "AVG_EV",          "avg_hit_speed",          "MAX(avg_hit_speed)"),
    ("season", "HARD_HIT_PCT",    "ev95percent",            "MAX(ev95percent)"),
    ("season", "BARREL_PCT",      "brl_percent",            "MAX(brl_percent)"),
    ("season", "SWEET_SPOT_PCT",  "anglesweetspotpercent",  "MAX(anglesweetspotpercent)"),
    ("season", "MAX_DIST",        "max_distance",           "MAX(max_distance)"),
    # ──────────── career batting (Statcast — peak only) ───────
    # Career rate-stat records (avg EV, hard-hit%, etc.) need PA-weighted
    # aggregation; skipped for v1. Career MAX-aggregable stats are clean.
    ("career", "MAX_EV",          "max_hit_speed",          "MAX(max_hit_speed)"),
    ("career", "MAX_DIST",        "max_distance",           "MAX(max_distance)"),
]

# Top-N per (scope, discipline, category, source). UI never wants more than
# this; Lahman alone has thousands of qualifying career-rows per category.
RECORD_TOP_N = 50

# Save scope — MLB (league_id=203, level_id=1, split_id=1).
RECORD_LEAGUE_ID = 203
RECORD_LEVEL_ID = 1


def _build_f_record_player(con: duckdb.DuckDBPyConnection) -> int:
    """Top-50 per (category, source) leaderboard table — single-season +
    career, batting + pitching. Sources: 'save' (the user's OOTP save,
    MLB-only) and 'lahman' (real-life MLB 1871–present).

    A `--era` flag on the CLI filters by source; the default unifies
    all three into a combined leaderboard. Each row carries `display_name`
    (UI-ready) plus identity: `player_id` for save rows, `external_id`
    for non-save rows (Lahman bbrefID for source='lahman', MLBAM player_id
    for source='statcast'). Source disambiguates which id namespace
    `external_id` is in.

    Stored ranks are within-source — i.e. the row with the most career
    HR in Lahman gets rank_in_source=1 among lahman rows, and the same
    for save. The CLI computes a unified rank when rendering all-era.
    Storing within-source ranks keeps the table cheap and lets the
    user pick "save only" / "lahman only" / "all eras" without
    re-querying source data.

    Schema:
        scope            VARCHAR  'season' or 'career'
        discipline       VARCHAR  'batting' or 'pitching'
        category         VARCHAR  e.g. 'HR', 'IP', 'MAX_EV'
        source           VARCHAR  'save' | 'lahman' | 'statcast'
        rank_in_source   INTEGER  1 = best within source (1..50)
        value            DOUBLE   stat value (outs for IP — CLI converts)
        display_name     VARCHAR  UI-ready full name
        player_id        BIGINT   OOTP player_id (save rows only; NULL for non-save)
        external_id      VARCHAR  Lahman bbrefID (source='lahman') OR MLBAM
                                  player_id-as-string (source='statcast')
        year             INTEGER  NULL for career rows
        team_id          BIGINT   OOTP team_id (save only)
        team_abbr        VARCHAR  3-letter team abbr; populated for save+lahman

    PK = (scope, discipline, category, source, rank_in_source).

    Notes:
      - WAR and QS are save-only (Lahman doesn't carry them). `--era
        lahman --category WAR` returns empty.
      - Statcast categories (MAX_EV, AVG_EV, BARREL_PCT, HARD_HIT_PCT,
        SWEET_SPOT_PCT, MAX_DIST) are batting-only and statcast-only.
        Save's at-bat-level EV data exists but isn't yet joined here
        (different calibration scale; future work). `--era statcast
        --category HR` returns empty.
    """
    save_parts: list[str] = []
    lahman_parts: list[str] = []
    for scope, disc, cat, save_col, save_cte, lahman_col in RECORD_CATEGORIES:
        # ─ save side ─────────────────────────────────────────
        if scope == "season":
            save_parts.append(f"""
                SELECT
                    '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                    'save' AS source,
                    CAST({save_col} AS DOUBLE) AS value,
                    player_id,
                    CAST(NULL AS VARCHAR) AS external_id,
                    CAST(year AS INTEGER) AS year,
                    team_id,
                    CAST(NULL AS VARCHAR) AS team_abbr,
                    CAST(NULL AS VARCHAR) AS display_name
                FROM {save_cte}
            """)
        else:
            save_parts.append(f"""
                SELECT
                    '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                    'save' AS source,
                    CAST({save_col} AS DOUBLE) AS value,
                    player_id,
                    CAST(NULL AS VARCHAR) AS external_id,
                    CAST(NULL AS INTEGER) AS year,
                    CAST(NULL AS BIGINT)  AS team_id,
                    CAST(NULL AS VARCHAR) AS team_abbr,
                    CAST(NULL AS VARCHAR) AS display_name
                FROM {save_cte}
            """)
        # ─ lahman side ───────────────────────────────────────
        if lahman_col is None:
            continue  # category not derivable from Lahman
        lahman_cte = "lahman_season_bat" if (scope == "season" and disc == "batting") else \
                     "lahman_season_pit" if (scope == "season" and disc == "pitching") else \
                     "lahman_career_bat" if (scope == "career" and disc == "batting") else \
                     "lahman_career_pit"
        if scope == "season":
            lahman_parts.append(f"""
                SELECT
                    '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                    'lahman' AS source,
                    CAST({lahman_col} AS DOUBLE) AS value,
                    CAST(NULL AS BIGINT) AS player_id,
                    playerID AS external_id,
                    CAST(yearID AS INTEGER) AS year,
                    CAST(NULL AS BIGINT) AS team_id,
                    teamID AS team_abbr,
                    NULL AS display_name
                FROM {lahman_cte}
            """)
        else:
            lahman_parts.append(f"""
                SELECT
                    '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                    'lahman' AS source,
                    CAST({lahman_col} AS DOUBLE) AS value,
                    CAST(NULL AS BIGINT) AS player_id,
                    playerID AS external_id,
                    CAST(NULL AS INTEGER) AS year,
                    CAST(NULL AS BIGINT) AS team_id,
                    CAST(NULL AS VARCHAR) AS team_abbr,
                    NULL AS display_name
                FROM {lahman_cte}
            """)
    # Chadwick Register — bbref_id ↔ mlb_id crosswalk. Optional; only
    # used to merge non-save career rows by bbref_id.
    chadwick_present = bool(con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'history_player_id_map'
    """).fetchone()[0])

    # BREF (Baseball-Reference) — fills the Lahman 2020-2024 gap for retirees.
    # Same shape as Lahman but per-season aggregates only.
    bref_present = bool(con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'history_bref_batting'
    """).fetchone()[0])
    bref_parts: list[str] = []
    if bref_present:
        for scope, disc, cat, save_col, save_cte, lahman_col in RECORD_CATEGORIES:
            # Only add BREF rows for categories Lahman would have covered
            # (i.e., lahman_col is not None — those are the universal classic
            # stats). WAR / QS stay save-only.
            if lahman_col is None:
                continue
            # Map Lahman col names to BREF col names. BREF uses the natural
            # baseball abbreviations directly; mostly the same as Lahman but
            # K → SO, IPouts → IPouts (we synthesized this in the loader).
            bref_col_map = {
                "hr": "HR", "rbi": "RBI", "r": "R", "h": "H",
                "bb": "BB", "sb": "SB", "d": '"2B"', "t": '"3B"',
                "pa": "PA",
                "w": "W", "sv": "SV", "so": "SO", "ipouts": "IPouts",
                # BREF pitching season frames don't expose SHO or CG —
                # those categories stay save+lahman only.
            }
            bref_col = bref_col_map.get(lahman_col)
            if bref_col is None:
                continue
            bref_table = "history_bref_batting" if disc == "batting" else "history_bref_pitching"
            if scope == "season":
                bref_parts.append(f"""
                    SELECT
                        '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                        'bref' AS source,
                        CAST({bref_col} AS DOUBLE) AS value,
                        CAST(NULL AS BIGINT) AS player_id,
                        mlbID AS external_id,
                        CAST(year AS INTEGER) AS year,
                        CAST(NULL AS BIGINT) AS team_id,
                        Tm AS team_abbr,
                        Name AS display_name
                    FROM {bref_table}
                    WHERE {bref_col} IS NOT NULL
                """)
            else:  # career — sum per mlbID across all years
                bref_parts.append(f"""
                    SELECT
                        '{scope}' AS scope, '{disc}' AS discipline, '{cat}' AS category,
                        'bref' AS source,
                        CAST(SUM({bref_col}) AS DOUBLE) AS value,
                        CAST(NULL AS BIGINT) AS player_id,
                        mlbID AS external_id,
                        CAST(NULL AS INTEGER) AS year,
                        CAST(NULL AS BIGINT) AS team_id,
                        CAST(NULL AS VARCHAR) AS team_abbr,
                        ANY_VALUE(Name) AS display_name
                    FROM {bref_table}
                    WHERE {bref_col} IS NOT NULL
                    GROUP BY mlbID
                """)

    # Statcast batting record parts — only when both Statcast loaded and
    # discipline is batting.
    statcast_parts: list[str] = []
    statcast_present = bool(con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'history_statcast_batting_season'
    """).fetchone()[0])
    if statcast_present:
        for scope, cat, src_col, agg_sql in STATCAST_BATTING_CATEGORIES:
            if scope == "season":
                statcast_parts.append(f"""
                    SELECT
                        '{scope}' AS scope, 'batting' AS discipline, '{cat}' AS category,
                        'statcast' AS source,
                        CAST({src_col} AS DOUBLE) AS value,
                        CAST(NULL AS BIGINT) AS player_id,
                        CAST(player_id AS VARCHAR) AS external_id,
                        CAST(year AS INTEGER) AS year,
                        CAST(NULL AS BIGINT) AS team_id,
                        CAST(NULL AS VARCHAR) AS team_abbr,
                        NULL AS display_name
                    FROM history_statcast_batting_season
                """)
            else:  # career
                statcast_parts.append(f"""
                    SELECT
                        '{scope}' AS scope, 'batting' AS discipline, '{cat}' AS category,
                        'statcast' AS source,
                        CAST({agg_sql} AS DOUBLE) AS value,
                        CAST(NULL AS BIGINT) AS player_id,
                        CAST(player_id AS VARCHAR) AS external_id,
                        CAST(NULL AS INTEGER) AS year,
                        CAST(NULL AS BIGINT) AS team_id,
                        CAST(NULL AS VARCHAR) AS team_abbr,
                        NULL AS display_name
                    FROM history_statcast_batting_season
                    GROUP BY player_id
                """)
    union_sql = "\n            UNION ALL".join(
        save_parts + lahman_parts + bref_parts + statcast_parts
    )

    # Detect whether Lahman is available — graceful fallback if user hasn't
    # run `diamond fetch-history` yet. We only build save-side records in
    # that case.
    lahman_present = (
        len(con.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN (
                'history_lahman_batting', 'history_lahman_pitching',
                'history_lahman_people'
            )
        """).fetchall()) == 3
    )

    if lahman_present:
        lahman_ctes = f"""
            lahman_season_bat AS (
                SELECT playerID, yearID,
                       ANY_VALUE(teamID) AS teamID,
                       SUM(HR)  AS hr, SUM(RBI) AS rbi, SUM(R) AS r,
                       SUM(H)   AS h,  SUM(BB)  AS bb,  SUM(SB) AS sb,
                       SUM("2B") AS d, SUM("3B") AS t,
                       SUM(AB) + COALESCE(SUM(BB), 0) + COALESCE(SUM(HBP), 0)
                              + COALESCE(SUM(SF), 0)  + COALESCE(SUM(SH), 0) AS pa
                FROM history_lahman_batting
                WHERE lgID IN ('AL', 'NL')
                GROUP BY playerID, yearID
            ),
            lahman_career_bat AS (
                SELECT playerID,
                       SUM(HR)  AS hr, SUM(RBI) AS rbi, SUM(R) AS r,
                       SUM(H)   AS h,  SUM(BB)  AS bb,  SUM(SB) AS sb,
                       SUM("2B") AS d, SUM("3B") AS t,
                       SUM(AB) + COALESCE(SUM(BB), 0) + COALESCE(SUM(HBP), 0)
                              + COALESCE(SUM(SF), 0)  + COALESCE(SUM(SH), 0) AS pa
                FROM history_lahman_batting
                WHERE lgID IN ('AL', 'NL')
                GROUP BY playerID
            ),
            lahman_season_pit AS (
                SELECT playerID, yearID,
                       ANY_VALUE(teamID) AS teamID,
                       SUM(W) AS w, SUM(L) AS l, SUM(SV) AS sv, SUM(SO) AS so,
                       SUM(IPouts) AS ipouts,
                       SUM(SHO) AS sho, SUM(CG) AS cg
                FROM history_lahman_pitching
                WHERE lgID IN ('AL', 'NL')
                GROUP BY playerID, yearID
            ),
            lahman_career_pit AS (
                SELECT playerID,
                       SUM(W) AS w, SUM(L) AS l, SUM(SV) AS sv, SUM(SO) AS so,
                       SUM(IPouts) AS ipouts,
                       SUM(SHO) AS sho, SUM(CG) AS cg
                FROM history_lahman_pitching
                WHERE lgID IN ('AL', 'NL')
                GROUP BY playerID
            ),"""
    else:
        # No Lahman tables yet — fall back to save + bref + statcast.
        lahman_ctes = ""
        union_sql = "\n            UNION ALL".join(
            save_parts + bref_parts + statcast_parts
        )

    con.execute(f"""
        CREATE OR REPLACE TABLE f_record_player AS
        WITH season_bat AS (
            SELECT
                player_id, year,
                ARG_MAX(team_id, pa) AS team_id,
                SUM(hr) AS hr, SUM(rbi) AS rbi, SUM(r) AS r, SUM(h) AS h,
                SUM(bb) AS bb, SUM(sb) AS sb, SUM(d) AS d, SUM(t) AS t,
                SUM(pa) AS pa, SUM(war) AS war
            FROM f_player_season_batting
            WHERE league_id = {RECORD_LEAGUE_ID}
              AND level_id  = {RECORD_LEVEL_ID}
              AND split_id  = 1
            GROUP BY player_id, year
        ),
        season_pit AS (
            SELECT
                player_id, year,
                ARG_MAX(team_id, outs) AS team_id,
                SUM(w) AS w, SUM(s) AS s, SUM(k) AS k, SUM(outs) AS outs,
                SUM(sho) AS sho, SUM(cg) AS cg, SUM(qs) AS qs, SUM(war) AS war
            FROM f_player_season_pitching
            WHERE league_id = {RECORD_LEAGUE_ID}
              AND level_id  = {RECORD_LEVEL_ID}
              AND split_id  = 1
            GROUP BY player_id, year
        ),
        career_bat AS (
            SELECT player_id,
                   SUM(hr) AS hr, SUM(rbi) AS rbi, SUM(r) AS r, SUM(h) AS h,
                   SUM(bb) AS bb, SUM(sb) AS sb, SUM(pa) AS pa, SUM(war) AS war
            FROM players_career_batting_event
            WHERE level_id = {RECORD_LEVEL_ID} AND split_id = 1
            GROUP BY player_id
        ),
        career_pit AS (
            SELECT player_id,
                   SUM(w) AS w, SUM(s) AS s, SUM(k) AS k, SUM(outs) AS outs,
                   SUM(sho) AS sho, SUM(cg) AS cg, SUM(war) AS war
            FROM players_career_pitching_event
            WHERE level_id = {RECORD_LEVEL_ID} AND split_id = 1
            GROUP BY player_id
        ),
            {lahman_ctes}
        all_records_raw AS ({union_sql}),
        -- bbref_id resolution: links every record row across the 4 sources
        -- by Lahman bbrefID where possible. OOTP players carry bbrefID
        -- in `players_current.historical_id`; BREF + Statcast use MLBAM
        -- ids that JOIN to `history_player_id_map` (Chadwick Register)
        -- to get bbrefID. When Chadwick isn't loaded, BREF / Statcast
        -- rows have NULL bbref_id_resolved and stay as their own source
        -- (no merge possible without the crosswalk).
        all_records AS (
            SELECT
                ar.*,
                CASE
                    WHEN ar.source = 'save' THEN
                        (SELECT historical_id FROM players_current
                         WHERE player_id = ar.player_id)
                    WHEN ar.source = 'lahman' THEN ar.external_id
                    WHEN ar.source IN ('bref', 'statcast') THEN
                        {(
                            "(SELECT bbref_id FROM history_player_id_map WHERE mlb_id = TRY_CAST(ar.external_id AS BIGINT))"
                            if chadwick_present else "NULL"
                        )}
                    ELSE NULL
                END AS bbref_id_resolved
            FROM all_records_raw ar
        ),
        -- Career dedup logic:
        --   1. Save career rows passthrough (save wins — OOTP imports each
        --      active player's full real career, so save rows for active
        --      players are complete).
        --   2. Non-save career rows for bbrefIDs that ARE in save: drop
        --      (avoid double-counting active players via Lahman/BREF).
        --   3. Non-save career rows for bbrefIDs NOT in save: MERGE across
        --      lahman + bref sources by bbrefID. This is the win — Pujols's
        --      Lahman 656 + BREF 30 collapse to one 686-HR row.
        --   4. Non-save career rows with no bbrefID linkage: passthrough
        --      with their original source (rare edge case).
        --   5. Season rows passthrough untouched (each year owned by one
        --      source by design — Lahman ≤2019, BREF 2020-2025, save covers
        --      its overlapping range with priority).
        save_career_bbrefs AS (
            SELECT DISTINCT bbref_id_resolved FROM all_records
            WHERE source = 'save' AND scope = 'career'
              AND bbref_id_resolved IS NOT NULL
        ),
        career_save AS (
            SELECT * FROM all_records WHERE scope = 'career' AND source = 'save'
        ),
        career_merged AS (
            SELECT
                scope, discipline, category,
                'merged' AS source,
                SUM(value) AS value,
                CAST(NULL AS BIGINT) AS player_id,
                ANY_VALUE(external_id) AS external_id,
                CAST(NULL AS INTEGER) AS year,
                CAST(NULL AS BIGINT) AS team_id,
                CAST(NULL AS VARCHAR) AS team_abbr,
                ANY_VALUE(display_name) AS display_name,
                bbref_id_resolved
            FROM all_records
            WHERE scope = 'career'
              AND source IN ('lahman', 'bref', 'statcast')
              AND bbref_id_resolved IS NOT NULL
              AND bbref_id_resolved NOT IN (
                  SELECT bbref_id_resolved FROM save_career_bbrefs
              )
            GROUP BY scope, discipline, category, bbref_id_resolved
        ),
        career_unlinked AS (
            SELECT * FROM all_records
            WHERE scope = 'career'
              AND source IN ('lahman', 'bref', 'statcast')
              AND bbref_id_resolved IS NULL
        ),
        season_passthrough AS (
            SELECT * FROM all_records WHERE scope = 'season'
        ),
        deduped_records AS (
            SELECT * FROM career_save
            UNION ALL SELECT * FROM career_merged
            UNION ALL SELECT * FROM career_unlinked
            UNION ALL SELECT * FROM season_passthrough
        ),
        -- Resolve display_name + team_abbr per source. Source-disambiguated
        -- name lookups: save → players_current; lahman → history_lahman_people;
        -- statcast → history_statcast_batting_season (the "last_name, first_name"
        -- combined col, splittable on ", ").
        named AS (
            SELECT
                ar.scope, ar.discipline, ar.category, ar.source,
                ar.value, ar.player_id, ar.external_id, ar.year, ar.team_id,
                COALESCE(
                    ar.team_abbr,
                    (SELECT abbr FROM teams WHERE team_id = ar.team_id)
                ) AS team_abbr,
                COALESCE(
                    ar.display_name,
                    (SELECT first_name || ' ' || last_name
                       FROM players_current WHERE player_id = ar.player_id),
                    {(
                        "(SELECT nameFirst || ' ' || nameLast FROM history_lahman_people WHERE playerID = ar.external_id)"
                        if lahman_present else "NULL"
                    )},
                    {(
                        # Statcast names are 'last_name, first_name' combined; flip them.
                        # Use a subquery against the table; pick MIN to dedup across years.
                        "(SELECT MIN(SPLIT_PART(\"last_name, first_name\", ', ', 2) || ' ' || SPLIT_PART(\"last_name, first_name\", ', ', 1)) FROM history_statcast_batting_season WHERE CAST(player_id AS VARCHAR) = ar.external_id)"
                        if statcast_present else "NULL"
                    )}
                ) AS display_name
            FROM deduped_records ar
        ),
        ranked AS (
            SELECT
                scope, discipline, category, source,
                CAST(ROW_NUMBER() OVER (
                    PARTITION BY scope, discipline, category, source
                    ORDER BY value DESC, COALESCE(external_id, CAST(player_id AS VARCHAR)) ASC
                ) AS INTEGER) AS rank_in_source,
                value, display_name, player_id, external_id,
                year, team_id, team_abbr
            FROM named
            WHERE value IS NOT NULL AND value > 0
        )
        SELECT * FROM ranked WHERE rank_in_source <= {RECORD_TOP_N}
    """)
    con.execute(
        "ALTER TABLE f_record_player "
        "ADD PRIMARY KEY (scope, discipline, category, source, rank_in_source)"
    )
    return con.execute("SELECT COUNT(*) FROM f_record_player").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# f_award_career_player + f_award_franchise
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_award_career_player(con: duckdb.DuckDBPyConnection) -> int:
    """Career award totals per player — save + lahman sources unioned.

    Each row is a per (source × identity × league × award) career-total
    capturing n_won and first/last year. Save rows carry OOTP `player_id`;
    Lahman rows carry the historical bbrefID in `external_id`.

    Lahman award strings are mapped to our `AwardId` enum where they
    line up. Awards Lahman has but we don't model (e.g., "TSN All-Star",
    "Hank Aaron Award") are dropped; we don't synthesize new IDs.
    All-Stars come from the separate `history_lahman_allstar` table and
    are mapped to `AwardId.ALL_STAR`.

    For Lahman rows `league_id` is set to 203 (MLB) regardless of AL/NL —
    we don't currently model AL vs NL as separate leagues since the user's
    save uses unified MLB league_id=203.

    Schema:
        source         VARCHAR  'save' | 'lahman'
        player_id      BIGINT   OOTP player_id (save only)
        external_id    VARCHAR  Lahman bbrefID (lahman only)
        display_name   VARCHAR  UI-ready
        league_id      BIGINT
        award_id       BIGINT   AwardId enum
        n_won          INTEGER
        first_year     INTEGER
        last_year      INTEGER
        first_team_id  BIGINT   save only
        last_team_id   BIGINT   save only
        first_team_abbr VARCHAR
        last_team_abbr  VARCHAR

    PK = (source, league_id, award_id, identity_key) — identity_key is
    materialized as COALESCE(external_id, player_id::VARCHAR) post-CTAS
    since DuckDB doesn't allow expressions in PK constraints.
    """
    lahman_present = bool(con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'history_lahman_awards'
    """).fetchone()[0])

    save_select = """
        SELECT
            'save' AS source,
            ae.player_id,
            CAST(NULL AS VARCHAR) AS external_id,
            (SELECT first_name || ' ' || last_name
               FROM players_current WHERE player_id = ae.player_id) AS display_name,
            ae.league_id,
            ae.award_id,
            CAST(COUNT(*) AS INTEGER) AS n_won,
            CAST(MIN(ae.year) AS INTEGER) AS first_year,
            CAST(MAX(ae.year) AS INTEGER) AS last_year,
            ARG_MIN(ae.team_id, ae.year) AS first_team_id,
            ARG_MAX(ae.team_id, ae.year) AS last_team_id,
            (SELECT abbr FROM teams WHERE team_id = ARG_MIN(ae.team_id, ae.year)) AS first_team_abbr,
            (SELECT abbr FROM teams WHERE team_id = ARG_MAX(ae.team_id, ae.year)) AS last_team_abbr
        FROM f_award_event ae
        GROUP BY ae.player_id, ae.league_id, ae.award_id
    """

    if lahman_present:
        # Lahman award-string → AwardId int mapping is materialized via a
        # CTE hoisted to the top of the CTAS so the subsequent SELECTs can
        # both reference it. Award strings not in the IN-list are simply
        # not modeled in our enum and get dropped (we don't synthesize
        # new ids).
        sql = f"""
        CREATE OR REPLACE TABLE f_award_career_player AS
        WITH lahman_mapped AS (
            SELECT
                a.playerID,
                CAST(203 AS BIGINT) AS league_id,
                CAST(CASE a.awardID
                    WHEN 'Most Valuable Player'         THEN 5
                    WHEN 'Cy Young Award'               THEN 4
                    WHEN 'Rookie of the Year'           THEN 6
                    WHEN 'Gold Glove'                   THEN 7
                    WHEN 'Silver Slugger'               THEN 11
                    WHEN 'World Series MVP'             THEN 15
                    WHEN 'Reliever of the Year Award'   THEN 13
                    WHEN 'Rolaids Relief Man Award'     THEN 13
                END AS BIGINT) AS award_id,
                a.yearID AS year
            FROM history_lahman_awards a
            WHERE a.awardID IN (
                'Most Valuable Player','Cy Young Award','Rookie of the Year',
                'Gold Glove','Silver Slugger','World Series MVP',
                'Reliever of the Year Award','Rolaids Relief Man Award'
            )
            UNION ALL
            -- All-Star comes from the separate AllstarFull table
            SELECT playerID, CAST(203 AS BIGINT), CAST(9 AS BIGINT), yearID
            FROM history_lahman_allstar
        )
        ({save_select})
        UNION ALL
        SELECT
            'lahman' AS source,
            CAST(NULL AS BIGINT) AS player_id,
            lm.playerID AS external_id,
            (SELECT nameFirst || ' ' || nameLast
               FROM history_lahman_people WHERE playerID = lm.playerID) AS display_name,
            lm.league_id,
            lm.award_id,
            CAST(COUNT(*) AS INTEGER) AS n_won,
            CAST(MIN(lm.year) AS INTEGER) AS first_year,
            CAST(MAX(lm.year) AS INTEGER) AS last_year,
            CAST(NULL AS BIGINT) AS first_team_id,
            CAST(NULL AS BIGINT) AS last_team_id,
            CAST(NULL AS VARCHAR) AS first_team_abbr,
            CAST(NULL AS VARCHAR) AS last_team_abbr
        FROM lahman_mapped lm
        WHERE lm.award_id IS NOT NULL
        GROUP BY lm.playerID, lm.league_id, lm.award_id
        """
    else:
        sql = f"CREATE OR REPLACE TABLE f_award_career_player AS {save_select}"

    con.execute(sql)

    # DuckDB PKs only accept column names (no expressions). Materialize a
    # synthetic identity-key column once so we can enforce uniqueness.
    con.execute("""
        ALTER TABLE f_award_career_player
        ADD COLUMN identity_key VARCHAR
    """)
    con.execute("""
        UPDATE f_award_career_player
        SET identity_key = COALESCE(external_id, CAST(player_id AS VARCHAR))
    """)
    con.execute(
        "ALTER TABLE f_award_career_player "
        "ADD PRIMARY KEY (source, league_id, award_id, identity_key)"
    )
    return con.execute("SELECT COUNT(*) FROM f_award_career_player").fetchone()[0]


def _build_f_award_franchise(con: duckdb.DuckDBPyConnection) -> int:
    """Franchise award totals — for each (team_at_time_of_winning, award),
    how many times has the franchise won?

    Differs from `f_award_career_player` in two ways:
      - Aggregates by team rather than player
      - Rolls farm-team team_ids up to their MLB-org parent (so an MVP
        with a Worcester team_id rolls to the Red Sox = team 4)

    Schema:
        team_id      BIGINT     MLB-org team_id (parent_team_id rollup)
        league_id    BIGINT
        award_id     BIGINT
        n_won        INTEGER
        first_year   INTEGER
        last_year    INTEGER

    PK = (team_id, league_id, award_id).
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_award_franchise AS
        WITH team_orgs AS (
            SELECT team_id,
                   COALESCE(NULLIF(parent_team_id, 0), team_id) AS org_id
            FROM teams
        )
        SELECT
            org.org_id   AS team_id,
            ae.league_id,
            ae.award_id,
            CAST(COUNT(*) AS INTEGER)  AS n_won,
            CAST(MIN(ae.year) AS INTEGER) AS first_year,
            CAST(MAX(ae.year) AS INTEGER) AS last_year
        FROM f_award_event ae
        LEFT JOIN team_orgs org ON org.team_id = ae.team_id
        WHERE org.org_id IS NOT NULL
        GROUP BY org.org_id, ae.league_id, ae.award_id
    """)
    con.execute(
        "ALTER TABLE f_award_franchise "
        "ADD PRIMARY KEY (team_id, league_id, award_id)"
    )
    return con.execute("SELECT COUNT(*) FROM f_award_franchise").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def build_l3(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build all L3 derived tables.

    Build order:
      1. f_trade_participant   (from trade_event)
      2. player_movements      (LEFT JOINs to f_trade_participant for trade_id)
      3. f_draft_class         (consumes player_movements for first_mlb_date)

    Requires L1 (players_snapshot, players_current, teams, trade_event,
    players_career_*_event) to be present.

    Returns dict of `{l3_table_name: row_count}`.
    """
    rows: dict[str, int] = {}

    n = _build_f_trade_participant(con)
    rows["f_trade_participant"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_trade_participant             "
            f"[dim]{n:>10,} rows  PK=(trade_id, player_id)[/dim]"
        )

    n = _build_player_movements(con)
    rows["player_movements"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] player_movements                "
            f"[dim]{n:>10,} rows  PK=(movement_id)[/dim]"
        )

    n = _build_f_draft_class(con)
    rows["f_draft_class"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_draft_class                   "
            f"[dim]{n:>10,} rows  PK=(player_id)[/dim]"
        )

    n = _build_f_record_player(con)
    rows["f_record_player"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_record_player                 "
            f"[dim]{n:>10,} rows  PK=(scope, discipline, category, source, rank_in_source)[/dim]"
        )

    n = _build_f_award_career_player(con)
    rows["f_award_career_player"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_award_career_player           "
            f"[dim]{n:>10,} rows  PK=(player_id, league_id, award_id)[/dim]"
        )

    n = _build_f_award_franchise(con)
    rows["f_award_franchise"] = n
    if verbose:
        console.print(
            f"  [green]✓[/green] f_award_franchise               "
            f"[dim]{n:>10,} rows  PK=(team_id, league_id, award_id)[/dim]"
        )

    return rows
