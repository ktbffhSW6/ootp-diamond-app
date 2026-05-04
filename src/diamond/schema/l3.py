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


# (scope, discipline, category, value_sql, source_cte, sort_dir) — sort_dir is
# always DESC for v1 since we only model "more is better" counting stats.
# Scope to MLB (league_id=203, level_id=1, split_id=1).
RECORD_CATEGORIES: list[tuple[str, str, str, str, str]] = [
    # ──────────────── single-season batting ─────────────────
    ("season", "batting", "HR",  "hr",  "season_bat"),
    ("season", "batting", "RBI", "rbi", "season_bat"),
    ("season", "batting", "R",   "r",   "season_bat"),
    ("season", "batting", "H",   "h",   "season_bat"),
    ("season", "batting", "BB",  "bb",  "season_bat"),
    ("season", "batting", "SB",  "sb",  "season_bat"),
    ("season", "batting", "2B",  "d",   "season_bat"),
    ("season", "batting", "3B",  "t",   "season_bat"),
    ("season", "batting", "PA",  "pa",  "season_bat"),
    ("season", "batting", "WAR", "war", "season_bat"),
    # ──────────────── career batting ────────────────────────
    ("career", "batting", "HR",  "hr",  "career_bat"),
    ("career", "batting", "RBI", "rbi", "career_bat"),
    ("career", "batting", "R",   "r",   "career_bat"),
    ("career", "batting", "H",   "h",   "career_bat"),
    ("career", "batting", "BB",  "bb",  "career_bat"),
    ("career", "batting", "SB",  "sb",  "career_bat"),
    ("career", "batting", "PA",  "pa",  "career_bat"),
    ("career", "batting", "WAR", "war", "career_bat"),
    # ──────────────── single-season pitching ────────────────
    ("season", "pitching", "W",   "w",    "season_pit"),
    ("season", "pitching", "S",   "s",    "season_pit"),
    ("season", "pitching", "K",   "k",    "season_pit"),
    ("season", "pitching", "IP",  "outs", "season_pit"),  # value=outs; CLI converts
    ("season", "pitching", "SHO", "sho",  "season_pit"),
    ("season", "pitching", "CG",  "cg",   "season_pit"),
    ("season", "pitching", "QS",  "qs",   "season_pit"),
    ("season", "pitching", "WAR", "war",  "season_pit"),
    # ──────────────── career pitching ───────────────────────
    ("career", "pitching", "W",   "w",    "career_pit"),
    ("career", "pitching", "S",   "s",    "career_pit"),
    ("career", "pitching", "K",   "k",    "career_pit"),
    ("career", "pitching", "IP",  "outs", "career_pit"),
    ("career", "pitching", "SHO", "sho",  "career_pit"),
    ("career", "pitching", "CG",  "cg",   "career_pit"),
    ("career", "pitching", "WAR", "war",  "career_pit"),
]

# Top-N per (scope, discipline, category). 25 is plenty for surfacing on a UI.
RECORD_TOP_N = 25

# League / level scope — MLB only for v1. Foreign + minor-league records are
# left as a future extension (the same CTAS shape works with different
# WHERE clauses).
RECORD_LEAGUE_ID = 203
RECORD_LEVEL_ID = 1


def _build_f_record_player(con: duckdb.DuckDBPyConnection) -> int:
    """Top-25 per category leaderboard table — single-season + career,
    batting + pitching. MLB-only (league_id=203, level_id=1).

    Long format keeps the UI / CLI layer simple: one filter per
    (scope, discipline, category) returns the leaderboard ready to
    render. Counting stats only for v1; rate stats (AVG/OBP/SLG/ERA/
    FIP/etc.) need PA / IP gates and live one layer up — they can be
    derived from `f_player_season_batting/pitching` in advanced.py
    when needed.

    Schema:
        scope        VARCHAR  'season' or 'career'
        discipline   VARCHAR  'batting' or 'pitching'
        category     VARCHAR  e.g. 'HR', 'IP'
        rank         INTEGER  1 = best
        value        DOUBLE   stat value (outs for IP — CLI converts)
        player_id    BIGINT
        year         INTEGER  NULL for career
        team_id      BIGINT   NULL for career; the team they were on
                              when they set the season mark (one team
                              per record, MAX in case of mid-year trade)

    PK = (scope, discipline, category, rank).
    """
    # Build the union-all of all (scope×discipline×category) records.
    # Each entry produces a SELECT yielding (scope, discipline, category,
    # value, player_id, year, team_id).
    parts: list[str] = []
    for scope, disc, cat, value_col, src_cte in RECORD_CATEGORIES:
        if scope == "season":
            parts.append(f"""
                SELECT
                    '{scope}'      AS scope,
                    '{disc}'       AS discipline,
                    '{cat}'        AS category,
                    CAST({value_col} AS DOUBLE) AS value,
                    player_id,
                    CAST(year AS INTEGER) AS year,
                    team_id
                FROM {src_cte}
            """)
        else:  # career
            parts.append(f"""
                SELECT
                    '{scope}'      AS scope,
                    '{disc}'       AS discipline,
                    '{cat}'        AS category,
                    CAST({value_col} AS DOUBLE) AS value,
                    player_id,
                    CAST(NULL AS INTEGER) AS year,
                    CAST(NULL AS BIGINT)  AS team_id
                FROM {src_cte}
            """)
    union_sql = "\n            UNION ALL".join(parts)

    con.execute(f"""
        CREATE OR REPLACE TABLE f_record_player AS
        WITH season_bat AS (
            SELECT
                player_id,
                year,
                -- One team per (player, year) for the record's team_id.
                -- Mid-season trades produce multiple teams; pick whichever
                -- saw the most stats by max-arg.
                ARG_MAX(team_id, pa) AS team_id,
                SUM(hr)  AS hr,
                SUM(rbi) AS rbi,
                SUM(r)   AS r,
                SUM(h)   AS h,
                SUM(bb)  AS bb,
                SUM(sb)  AS sb,
                SUM(d)   AS d,
                SUM(t)   AS t,
                SUM(pa)  AS pa,
                SUM(war) AS war
            FROM f_player_season_batting
            WHERE league_id = {RECORD_LEAGUE_ID}
              AND level_id  = {RECORD_LEVEL_ID}
              AND split_id  = 1
            GROUP BY player_id, year
        ),
        season_pit AS (
            SELECT
                player_id,
                year,
                ARG_MAX(team_id, outs) AS team_id,
                SUM(w)    AS w,
                SUM(s)    AS s,
                SUM(k)    AS k,
                SUM(outs) AS outs,
                SUM(sho)  AS sho,
                SUM(cg)   AS cg,
                SUM(qs)   AS qs,
                SUM(war)  AS war
            FROM f_player_season_pitching
            WHERE league_id = {RECORD_LEAGUE_ID}
              AND level_id  = {RECORD_LEVEL_ID}
              AND split_id  = 1
            GROUP BY player_id, year
        ),
        career_bat AS (
            SELECT
                player_id,
                SUM(hr)  AS hr,
                SUM(rbi) AS rbi,
                SUM(r)   AS r,
                SUM(h)   AS h,
                SUM(bb)  AS bb,
                SUM(sb)  AS sb,
                SUM(pa)  AS pa,
                SUM(war) AS war
            FROM players_career_batting_event
            WHERE level_id = {RECORD_LEVEL_ID} AND split_id = 1
            GROUP BY player_id
        ),
        career_pit AS (
            SELECT
                player_id,
                SUM(w)    AS w,
                SUM(s)    AS s,
                SUM(k)    AS k,
                SUM(outs) AS outs,
                SUM(sho)  AS sho,
                SUM(cg)   AS cg,
                SUM(war)  AS war
            FROM players_career_pitching_event
            WHERE level_id = {RECORD_LEVEL_ID} AND split_id = 1
            GROUP BY player_id
        ),
        all_records AS ({union_sql}),
        ranked AS (
            SELECT
                scope, discipline, category,
                CAST(ROW_NUMBER() OVER (
                    PARTITION BY scope, discipline, category
                    ORDER BY value DESC, player_id ASC
                ) AS INTEGER) AS rank,
                value, player_id, year, team_id
            FROM all_records
            WHERE value IS NOT NULL AND value > 0
        )
        SELECT * FROM ranked WHERE rank <= {RECORD_TOP_N}
    """)
    con.execute(
        "ALTER TABLE f_record_player ADD PRIMARY KEY (scope, discipline, category, rank)"
    )
    return con.execute("SELECT COUNT(*) FROM f_record_player").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# f_award_career_player + f_award_franchise
# ─────────────────────────────────────────────────────────────────────────────


def _build_f_award_career_player(con: duckdb.DuckDBPyConnection) -> int:
    """Career award totals per player.

    One row per (player, league, award_id). Captures count + first /
    last year won, plus the team they were on at first / last win
    (useful for "Mookie Betts won 3 MVPs as a Sox" framings).

    Schema:
        player_id    BIGINT
        league_id    BIGINT
        award_id     BIGINT       constants.AwardId enum
        n_won        INTEGER
        first_year   INTEGER
        last_year    INTEGER
        first_team_id BIGINT      team at first win
        last_team_id BIGINT       team at last win

    PK = (player_id, league_id, award_id).
    """
    con.execute("""
        CREATE OR REPLACE TABLE f_award_career_player AS
        SELECT
            player_id,
            league_id,
            award_id,
            CAST(COUNT(*) AS INTEGER)     AS n_won,
            CAST(MIN(year) AS INTEGER)    AS first_year,
            CAST(MAX(year) AS INTEGER)    AS last_year,
            ARG_MIN(team_id, year)        AS first_team_id,
            ARG_MAX(team_id, year)        AS last_team_id
        FROM f_award_event
        GROUP BY player_id, league_id, award_id
    """)
    con.execute(
        "ALTER TABLE f_award_career_player "
        "ADD PRIMARY KEY (player_id, league_id, award_id)"
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
            f"[dim]{n:>10,} rows  PK=(scope, discipline, category, rank)[/dim]"
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
