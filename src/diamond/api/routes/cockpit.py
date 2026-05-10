"""Cockpit dashboard endpoint — backs the new ``/`` landing.

Endpoint:
- ``GET /api/cockpit`` — composes standings strip + pressure
  summary + spotlight cards + recent movements into a single
  payload. Always defaults to "now" — no year picker on the cockpit
  itself; year-spanning views live on their dedicated pages.

Implementation notes:

- Org scope auto-derived from ``get_active_save().audit_team_id``.
- Standings strip resolves the user's MLB division at the latest
  dump within the latest year. Reuses the team_record_snapshot
  table; same magic-number sentinels as the standings page but
  collapsed since the cockpit only shows one division.
- Pressure summary is MLB-only. Top 3 batters/pitchers by OPS+/
  ERA+ ASC and DESC. Same sample bars as the dedicated pressure
  page (50 PA / 60 outs).
- Spotlight cards favor MLB-level rows. The current-year headline
  metric is the player's MLB-level OPS+ for batters / ERA+ for
  pitchers. Career WAR sparkline series spans every year that has
  any advanced row (across all levels) — minor-league time still
  shows up so a prospect's call-up moment reads visually as a
  step-up.
- Recent movements is the last N ledger rows for the current year,
  ordered by movement_date DESC.
- Auto-generated insights are server-side NLG templates. Three
  patterns:
    (a) "Career year — X vs prior peak Y" when current beats prior peak
    (b) "Bounceback — X after last year's Y" when current > prior year
    (c) "Off year — X down from Y peak" when current < prior peak by ≥20%
  Returns null when no useful comparison exists (rookie season).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends

from diamond.api.schemas import (
    CockpitMovementRow,
    CockpitPressureRow,
    CockpitPressureSummary,
    CockpitResponse,
    CockpitSpotlightCard,
    CockpitStandingsBlock,
    CockpitStandingsRow,
)
from diamond.api.warehouse import get_active_save, get_cursor

router = APIRouter()


# Defaults — these intentionally match the dedicated pages for
# consistency. Sample bars for pressure summary mirror /api/pressure;
# spotlight count + movements count are display-only knobs.
_PRESSURE_SUMMARY_LIMIT = 3
_SPOTLIGHT_COUNT = 6
_RECENT_MOVEMENTS_LIMIT = 8
_MIN_BAT_PA = 50
_MIN_PIT_OUTS = 60  # 20 IP

# Spotlight selection: prefer MLB-level rows. We pull the top N at
# MLB-level by current-year WAR; if that yields fewer than N (small
# org / call-up window), pad with the top non-MLB performers.
_MLB_LEVEL = 1


# ─────────────────────────────────────────────────────────────────────────────
# Latest year resolution
# ─────────────────────────────────────────────────────────────────────────────


_LATEST_YEAR_SQL = """
SELECT MAX(year) FROM f_player_season_advanced_batting
"""


# ─────────────────────────────────────────────────────────────────────────────
# Standings strip — find the user's MLB division and pull just that one
# ─────────────────────────────────────────────────────────────────────────────


_USER_DIVISION_SQL = """
SELECT t.sub_league_id, t.division_id
FROM teams t WHERE t.team_id = ?
"""


_USER_DIV_STANDINGS_SQL = """
WITH latest_dump AS (
    SELECT MAX(trs.dump_date) AS d
    FROM team_record_snapshot trs
    JOIN teams t ON t.team_id = trs.team_id
    WHERE t.league_id = 203
      AND EXTRACT(YEAR FROM trs.dump_date) = ?
      AND trs.g > 0
)
SELECT
    trs.team_id, t.abbr, t.nickname,
    trs.w, trs.l, trs.pct, trs.gb, trs.streak, trs.pos,
    d.name AS division_name,
    (SELECT d FROM latest_dump) AS dump_date
FROM team_record_snapshot trs
JOIN teams t ON t.team_id = trs.team_id
LEFT JOIN divisions d
       ON d.league_id = t.league_id
      AND d.sub_league_id = t.sub_league_id
      AND d.division_id = t.division_id
WHERE t.league_id = 203
  AND t.sub_league_id = ?
  AND t.division_id = ?
  AND trs.g > 0
  AND trs.dump_date = (SELECT d FROM latest_dump)
ORDER BY trs.pos
"""


def _fetch_standings(
    con: duckdb.DuckDBPyConnection,
    *,
    org_team_id: int,
    year: int,
) -> CockpitStandingsBlock | None:
    """Resolve user's division at MLB level, pull standings for it."""
    div_row = con.execute(_USER_DIVISION_SQL, [org_team_id]).fetchone()
    if not div_row or div_row[0] is None or div_row[1] is None:
        return None
    sub_league_id, division_id = int(div_row[0]), int(div_row[1])

    rows = con.execute(
        _USER_DIV_STANDINGS_SQL,
        [year, sub_league_id, division_id],
    ).fetchall()
    if not rows:
        return None

    snapshot_date: date = rows[0][10]
    division_name = rows[0][9]
    standings_rows: list[CockpitStandingsRow] = []
    for r in rows:
        (team_id, abbr, nickname, w, l_, pct, gb, streak, pos,
         _div_name, _dump) = r
        standings_rows.append(
            CockpitStandingsRow(
                team_id=int(team_id),
                abbr=abbr,
                nickname=nickname,
                w=int(w) if w is not None else 0,
                l=int(l_) if l_ is not None else 0,
                pct=float(pct) if pct is not None else 0.0,
                gb=float(gb) if gb is not None else 0.0,
                streak=int(streak) if streak is not None else 0,
                is_user_org=int(team_id) == org_team_id,
            )
        )
    return CockpitStandingsBlock(
        division_name=division_name,
        snapshot_date=snapshot_date,
        rows=standings_rows,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pressure summary — MLB-only, top 3 promotion + top 3 pressure
# ─────────────────────────────────────────────────────────────────────────────


_MLB_BATTERS_SQL = """
WITH org AS (SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?)
SELECT
    b.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    b.pa, b.ops_plus, t.abbr AS team_abbr
FROM f_player_season_advanced_batting b
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE b.year = ? AND b.level_id = 1
  AND b.pa >= ? AND b.ops_plus IS NOT NULL
  AND pc.team_id IN (SELECT team_id FROM org)
"""


_MLB_PITCHERS_SQL = """
WITH org AS (SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?)
SELECT
    p.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    p.outs, p.ip_display, p.era_plus, t.abbr AS team_abbr
FROM f_player_season_advanced_pitching p
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE p.year = ? AND p.level_id = 1
  AND p.outs >= ? AND p.era_plus IS NOT NULL
  AND pc.team_id IN (SELECT team_id FROM org)
"""


def _fetch_pressure_summary(
    con: duckdb.DuckDBPyConnection,
    *,
    org_team_id: int,
    year: int,
) -> CockpitPressureSummary:
    """Top 3 promotion / top 3 pressure across MLB batters + pitchers."""
    bat_rows = con.execute(
        _MLB_BATTERS_SQL,
        [org_team_id, org_team_id, year, _MIN_BAT_PA],
    ).fetchall()
    pit_rows = con.execute(
        _MLB_PITCHERS_SQL,
        [org_team_id, org_team_id, year, _MIN_PIT_OUTS],
    ).fetchall()

    combined: list[CockpitPressureRow] = []
    for r in bat_rows:
        player_id, display_name, pa, ops_plus, team_abbr = r
        combined.append(
            CockpitPressureRow(
                player_id=int(player_id),
                display_name=display_name,
                role="batter",
                level_name="MLB",
                metric=int(ops_plus),
                sample=f"{int(pa)} PA",
                team_abbr=team_abbr,
            )
        )
    for r in pit_rows:
        player_id, display_name, outs, ip_display, era_plus, team_abbr = r
        combined.append(
            CockpitPressureRow(
                player_id=int(player_id),
                display_name=display_name,
                role="pitcher",
                level_name="MLB",
                metric=int(era_plus),
                sample=f"{float(ip_display):.1f} IP",
                team_abbr=team_abbr,
            )
        )

    # Top promotion (highest metric) + top pressure (lowest metric).
    # Tiebreak on volume so an MVP candidate with 600 PA outranks a
    # 60-PA cup-of-coffee fluke.
    def vol(p: CockpitPressureRow) -> int:
        # Pull volume from the sample string we just baked. Cheap.
        # Format: "200 PA" or "45.2 IP"
        try:
            return int(float(p.sample.split()[0]))
        except (ValueError, IndexError):
            return 0

    promotion = sorted(combined, key=lambda p: (-p.metric, -vol(p)))[
        :_PRESSURE_SUMMARY_LIMIT
    ]
    pressure = sorted(combined, key=lambda p: (p.metric, -vol(p)))[
        :_PRESSURE_SUMMARY_LIMIT
    ]
    return CockpitPressureSummary(promotion=promotion, pressure=pressure)


# ─────────────────────────────────────────────────────────────────────────────
# Spotlight cards — top MLB-level Sox by current-year WAR
# ─────────────────────────────────────────────────────────────────────────────


_SPOTLIGHT_RANK_SQL = """
WITH org AS (SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?),
year_rows AS (
    SELECT player_id, level_id, b_war AS war_val,
           pa AS sample_n, ops_plus AS metric, 'batter' AS role
    FROM f_player_season_advanced_batting
    WHERE year = ? AND b_war IS NOT NULL
      AND player_id IN (SELECT player_id FROM players_current
                        WHERE team_id IN (SELECT team_id FROM org))
    UNION ALL
    SELECT player_id, level_id, p_war AS war_val,
           outs AS sample_n, era_plus AS metric, 'pitcher' AS role
    FROM f_player_season_advanced_pitching
    WHERE year = ? AND p_war IS NOT NULL
      AND player_id IN (SELECT player_id FROM players_current
                        WHERE team_id IN (SELECT team_id FROM org))
),
ranked AS (
    -- One row per (player_id, role) — pick the MAX-WAR level for
    -- that role. MLB-level wins ties so the spotlight prefers MLB
    -- numbers when the player split a season.
    SELECT player_id, role, level_id, war_val, sample_n, metric
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY player_id, role
            ORDER BY war_val DESC, level_id ASC
        ) AS rn
        FROM year_rows
    ) WHERE rn = 1
),
collapsed AS (
    -- One row per player overall — pick the role with the highest
    -- WAR. Two-way players (Ohtani-style) get whichever discipline
    -- led, plus a 'two-way' role flag at the schema layer.
    SELECT player_id,
           ANY_VALUE(role) FILTER (WHERE rn_player = 1) AS role,
           SUM(war_val) AS total_war,
           ANY_VALUE(level_id) FILTER (WHERE rn_player = 1) AS level_id,
           ANY_VALUE(sample_n) FILTER (WHERE rn_player = 1) AS sample_n,
           ANY_VALUE(metric) FILTER (WHERE rn_player = 1) AS metric,
           COUNT(*) AS role_count
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY player_id ORDER BY war_val DESC
        ) AS rn_player
        FROM ranked
    ) GROUP BY player_id
)
SELECT
    c.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    pc.position,
    c.role, c.role_count,
    c.level_id, c.metric, c.sample_n, c.total_war,
    pc.team_id, t.abbr AS team_abbr
FROM collapsed c
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
ORDER BY (c.level_id = 1) DESC, c.total_war DESC
LIMIT ?
"""


_CAREER_WAR_SQL = """
SELECT year,
       COALESCE(SUM(b_war), 0) + COALESCE(SUM(p_war), 0) AS war_yr
FROM (
    SELECT year, b_war, NULL::DOUBLE AS p_war
    FROM f_player_season_advanced_batting
    WHERE player_id = ?
    UNION ALL
    SELECT year, NULL::DOUBLE AS b_war, p_war
    FROM f_player_season_advanced_pitching
    WHERE player_id = ?
)
GROUP BY year ORDER BY year
"""


def _generate_insight(
    *, role: str, year: int, current: int, prior_peak: int | None,
    prior_year: int | None, prior_year_metric: int | None,
) -> str | None:
    """Server-side NLG. Three patterns; null if no useful comparison.

    All metrics are 100-relative (OPS+ or ERA+). Direction logic is
    same for both (higher = better), so the templates don't branch
    on role.
    """
    if prior_peak is None or prior_peak == 0:
        # Pre-peak rookie → no comparable yet.
        return None

    if current >= prior_peak + 10:
        # Strict improvement on prior peak.
        return f"Career year — {current} vs prior peak {prior_peak}."
    if (
        prior_year_metric is not None
        and prior_year is not None
        and current >= prior_year_metric + 15
    ):
        return (
            f"Bounceback — {current} after {prior_year_metric} in {prior_year}."
        )
    if current <= round(prior_peak * 0.8):
        return f"Off year — {current} down from {prior_peak} peak."
    return None


def _fetch_spotlight(
    con: duckdb.DuckDBPyConnection,
    *,
    org_team_id: int,
    year: int,
) -> list[CockpitSpotlightCard]:
    """Top-N Sox players for the current year + their career WAR series."""
    rank_rows = con.execute(
        _SPOTLIGHT_RANK_SQL,
        [
            org_team_id, org_team_id,  # org for batters
            year,
            year,  # used for pitchers
            _SPOTLIGHT_COUNT,
        ],
    ).fetchall()

    out: list[CockpitSpotlightCard] = []
    for r in rank_rows:
        (player_id, display_name, position, role, role_count,
         _level_id, metric, sample_n, war_current, team_id, team_abbr) = r
        # Career arc — full WAR series across all years
        career_rows = con.execute(
            _CAREER_WAR_SQL, [player_id, player_id]
        ).fetchall()
        career_years = [int(yr) for yr, _ in career_rows]
        career_war = [
            float(w) if w is not None else None for _yr, w in career_rows
        ]

        # Insight — compare current to prior peak + prior year, both
        # in the SAME role. If the player has multi-role history,
        # this just uses the role they led with this year.
        same_role_table = (
            "f_player_season_advanced_batting"
            if role == "batter"
            else "f_player_season_advanced_pitching"
        )
        metric_col = "ops_plus" if role == "batter" else "era_plus"
        prior_peak_row = con.execute(
            f"""
            SELECT MAX({metric_col})
            FROM {same_role_table}
            WHERE player_id = ? AND year < ? AND level_id = 1
              AND {metric_col} IS NOT NULL
            """,
            [player_id, year],
        ).fetchone()
        prior_peak = (
            int(prior_peak_row[0])
            if prior_peak_row and prior_peak_row[0] is not None
            else None
        )
        prior_year_row = con.execute(
            f"""
            SELECT year, {metric_col}
            FROM {same_role_table}
            WHERE player_id = ? AND year < ? AND level_id = 1
              AND {metric_col} IS NOT NULL
            ORDER BY year DESC LIMIT 1
            """,
            [player_id, year],
        ).fetchone()
        prior_year = (
            int(prior_year_row[0])
            if prior_year_row and prior_year_row[0] is not None
            else None
        )
        prior_year_metric = (
            int(prior_year_row[1])
            if prior_year_row and prior_year_row[1] is not None
            else None
        )

        # Insight skips entirely when current metric is NULL — comparing
        # a missing value to a prior peak would render nonsense like
        # "Off year — 0 down from 135 peak." We'd rather render no
        # insight than a misleading one.
        if metric is None:
            insight = None
        else:
            insight = _generate_insight(
                role=role,
                year=year,
                current=int(metric),
                prior_peak=prior_peak,
                prior_year=prior_year,
                prior_year_metric=prior_year_metric,
            )

        # Headline metric label per role.
        metric_label = "OPS+" if role == "batter" else "ERA+"

        # Sample formatting: PA for batters, IP for pitchers (decimal).
        if role == "batter":
            sample = f"{int(sample_n)} PA"
        else:
            outs = int(sample_n) if sample_n is not None else 0
            sample = f"{outs // 3}.{outs % 3} IP"

        # Two-way detection — role_count > 1 means the player had
        # both batting AND pitching advanced rows this year.
        ui_role = (
            "two-way" if int(role_count) > 1 else role  # type: ignore[assignment]
        )

        out.append(
            CockpitSpotlightCard(
                player_id=int(player_id),
                display_name=display_name,
                position=int(position) if position is not None else 0,
                role=ui_role,  # type: ignore[arg-type]
                team_id=int(team_id) if team_id is not None else None,
                team_abbr=team_abbr,
                headline_metric_label=metric_label,
                headline_metric_value=(
                    int(metric) if metric is not None else None
                ),
                sample=sample,
                war_current=float(war_current) if war_current is not None else 0.0,
                career_years=career_years,
                career_war=career_war,
                insight=insight,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Recent movements feed
# ─────────────────────────────────────────────────────────────────────────────


_RECENT_MOVES_SQL = """
WITH org AS (SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?)
SELECT
    pm.movement_id,
    pm.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    pm.movement_type,
    -- direction inference matches /api/movements semantics
    CASE
        WHEN pm.from_team_id IN (SELECT team_id FROM org)
         AND pm.to_team_id   IN (SELECT team_id FROM org) THEN 'internal'
        WHEN pm.to_team_id   IN (SELECT team_id FROM org) THEN 'incoming'
        ELSE 'outgoing'
    END AS direction,
    tf.abbr AS from_team_abbr,
    tt.abbr AS to_team_abbr,
    pm.dump_date_observed AS movement_date
FROM player_movements pm
LEFT JOIN players_current pc USING (player_id)
LEFT JOIN teams tf ON tf.team_id = pm.from_team_id
LEFT JOIN teams tt ON tt.team_id = pm.to_team_id
WHERE EXTRACT(YEAR FROM pm.dump_date_observed) = ?
  AND (pm.from_team_id IN (SELECT team_id FROM org)
       OR pm.to_team_id IN (SELECT team_id FROM org))
ORDER BY pm.dump_date_observed DESC, pm.movement_id DESC
LIMIT ?
"""


def _fetch_recent_movements(
    con: duckdb.DuckDBPyConnection,
    *,
    org_team_id: int,
    year: int,
) -> list[CockpitMovementRow]:
    rows = con.execute(
        _RECENT_MOVES_SQL,
        [org_team_id, org_team_id, year, _RECENT_MOVEMENTS_LIMIT],
    ).fetchall()
    out: list[CockpitMovementRow] = []
    for r in rows:
        (movement_id, player_id, display_name, movement_type, direction,
         from_team_abbr, to_team_abbr, movement_date) = r
        out.append(
            CockpitMovementRow(
                movement_id=int(movement_id),
                player_id=int(player_id) if player_id is not None else 0,
                display_name=display_name or "—",
                movement_type=movement_type or "",
                direction=direction or "",
                from_team_abbr=from_team_abbr,
                to_team_abbr=to_team_abbr,
                movement_date=movement_date,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/cockpit", response_model=CockpitResponse)
def get_cockpit(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> CockpitResponse:
    """Compose all four sub-payloads for the cockpit landing."""
    save = get_active_save()
    org_team_id = save.audit_team_id

    year_row = con.execute(_LATEST_YEAR_SQL).fetchone()
    if not year_row or year_row[0] is None:
        # No advanced data at all — return empty cockpit instead of
        # 404 so the page renders a friendly empty state.
        return CockpitResponse(
            year=0,
            org_team_id=org_team_id,
            standings=None,
            pressure=CockpitPressureSummary(promotion=[], pressure=[]),
            spotlight=[],
            recent_movements=[],
        )
    year = int(year_row[0])

    standings = _fetch_standings(con, org_team_id=org_team_id, year=year)
    pressure = _fetch_pressure_summary(con, org_team_id=org_team_id, year=year)
    spotlight = _fetch_spotlight(con, org_team_id=org_team_id, year=year)
    recent_movements = _fetch_recent_movements(
        con, org_team_id=org_team_id, year=year,
    )

    return CockpitResponse(
        year=year,
        org_team_id=org_team_id,
        standings=standings,
        pressure=pressure,
        spotlight=spotlight,
        recent_movements=recent_movements,
    )
