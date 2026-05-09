"""Pressure-board endpoint — backs ``/pressure``.

Endpoint:
- ``GET /api/pressure?year=&limit=`` — per-level promotion-vs-pressure
  decomposition for the org tree at one year. Defaults: latest year
  with data, limit=6 (per side per level).

Implementation notes:

- Org scope is auto-derived from ``get_active_save().audit_team_id``.
  Players are pulled from the parent-team rollup (the audit team
  itself + every team with ``parent_team_id = audit_team_id``).
- Sample thresholds:
  - Batters: ``pa >= 50`` (plate-appearance floor; OPS+ stabilizes
    around this point at MLB).
  - Pitchers: ``outs >= 60`` (20 IP — slightly above the L3 build's
    minimum of 30 outs / 10 IP).
- Metric semantics — both OPS+ and ERA+ are park-adjusted league-
  relative scales where 100 = league average. Higher OPS+ = better
  hitter; lower ERA+ = WORSE pitcher (ERA+ is "league ERA / player
  ERA × park", so 130 ERA+ means 30% better than league). For the
  ranking direction:
    - **Batters**: high OPS+ = mash → promotion candidate; low
      OPS+ = pressure case.
    - **Pitchers**: high ERA+ = strong → promotion candidate;
      low ERA+ = pressure case.
  Both metrics use the same direction relative to "100 = average,"
  so the SQL ranks DESC for both, no per-role inversion needed.
- Levels with zero qualifying players drop out (a complex-league
  team with three pre-callup rookies on it doesn't render an
  empty card). The route also caps the rendered levels to ones
  the L3 advanced builders cover (level 1-7); higher-numbered
  levels (Indy / foreign) are skipped since they're outside the
  org-development pipeline.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import (
    PressureLevelGroup,
    PressurePlayer,
    PressureResponse,
)
from diamond.api.warehouse import get_active_save, get_cursor
from diamond.constants import LEVEL_NAMES

router = APIRouter()


_DEFAULT_LIMIT = 6  # per side per level
_MAX_LIMIT = 25
_MIN_BAT_PA = 50
_MIN_PIT_OUTS = 60  # 20 IP

# Levels we surface — the org-development pipeline. Indy / foreign
# (8+) drop out since they're not part of the call-up ladder.
_PIPELINE_LEVELS = (1, 2, 3, 4, 5, 6, 7)


def _coerce_limit(raw: int | None) -> int:
    if raw is None:
        return _DEFAULT_LIMIT
    if raw < 1:
        return _DEFAULT_LIMIT
    if raw > _MAX_LIMIT:
        return _MAX_LIMIT
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Available years — both batter + pitcher advanced rows, intersected
# with the org tree so we don't expose years where the org didn't
# field a roster.
# ─────────────────────────────────────────────────────────────────────────────


_AVAILABLE_YEARS_SQL = """
WITH org AS (
    SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?
)
SELECT DISTINCT ab.year
FROM (
    SELECT b.year, b.player_id
    FROM f_player_season_advanced_batting b
    JOIN players_current pc USING (player_id)
    WHERE pc.team_id IN (SELECT team_id FROM org)
    UNION
    SELECT p.year, p.player_id
    FROM f_player_season_advanced_pitching p
    JOIN players_current pc USING (player_id)
    WHERE pc.team_id IN (SELECT team_id FROM org)
) ab
ORDER BY ab.year DESC
"""


# Org-scoped batter rows for one year, with the dominant-team abbr
# joined in. We use the player's CURRENT team for the team_abbr
# label rather than the season's dominant team — matches the user's
# mental model ("where are they NOW") and the roster page convention.
_BATTERS_SQL = """
WITH org AS (
    SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?
)
SELECT
    b.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    b.level_id,
    b.pa,
    b.ops_plus,
    b.b_war,
    t.abbr AS team_abbr,
    pc.position
FROM f_player_season_advanced_batting b
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE b.year = ?
  AND b.pa >= ?
  AND b.ops_plus IS NOT NULL
  AND pc.team_id IN (SELECT team_id FROM org)
"""


_PITCHERS_SQL = """
WITH org AS (
    SELECT team_id FROM teams WHERE team_id = ? OR parent_team_id = ?
)
SELECT
    p.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    p.level_id,
    p.outs,
    p.ip_display,
    p.era_plus,
    p.p_war,
    t.abbr AS team_abbr
FROM f_player_season_advanced_pitching p
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE p.year = ?
  AND p.outs >= ?
  AND p.era_plus IS NOT NULL
  AND pc.team_id IN (SELECT team_id FROM org)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _bat_row_to_player(row: tuple) -> PressurePlayer:
    (player_id, display_name, level_id, pa, ops_plus, b_war,
     team_abbr, position) = row
    metric = int(ops_plus)
    return PressurePlayer(
        player_id=int(player_id),
        display_name=display_name,
        role="batter",
        pa=int(pa) if pa is not None else None,
        ip=None,
        metric=metric,
        delta=metric - 100,
        war=float(b_war) if b_war is not None else 0.0,
        team_abbr=team_abbr,
        position=int(position) if position is not None else None,
    )


def _pit_row_to_player(row: tuple) -> PressurePlayer:
    (player_id, display_name, level_id, outs, ip_display, era_plus,
     p_war, team_abbr) = row
    metric = int(era_plus)
    return PressurePlayer(
        player_id=int(player_id),
        display_name=display_name,
        role="pitcher",
        pa=None,
        ip=float(ip_display) if ip_display is not None else None,
        metric=metric,
        delta=metric - 100,
        war=float(p_war) if p_war is not None else 0.0,
        team_abbr=team_abbr,
        position=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/pressure", response_model=PressureResponse)
def get_pressure(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    year: Annotated[
        int | None,
        Query(description="Season year. Defaults to latest year with org data."),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            ge=1, le=_MAX_LIMIT,
            description=f"Top-N per side per level. Defaults to {_DEFAULT_LIMIT}.",
        ),
    ] = None,
) -> PressureResponse:
    """Per-level promotion vs pressure decomposition for the org tree."""
    save = get_active_save()
    org_team_id = save.audit_team_id
    resolved_limit = _coerce_limit(limit)

    available_years = [
        int(r[0])
        for r in con.execute(
            _AVAILABLE_YEARS_SQL, [org_team_id, org_team_id]
        ).fetchall()
    ]
    if not available_years:
        raise HTTPException(
            status_code=404,
            detail="No org-scoped advanced data — run `diamond ingest` first.",
        )

    available_set = set(available_years)
    if year is not None and year in available_set:
        resolved_year = year
    else:
        resolved_year = available_years[0]  # latest

    # Pull both rosters in parallel, then group by level.
    batter_rows = con.execute(
        _BATTERS_SQL,
        [org_team_id, org_team_id, resolved_year, _MIN_BAT_PA],
    ).fetchall()
    pitcher_rows = con.execute(
        _PITCHERS_SQL,
        [org_team_id, org_team_id, resolved_year, _MIN_PIT_OUTS],
    ).fetchall()

    by_level: dict[int, list[PressurePlayer]] = {}
    for r in batter_rows:
        level_id = int(r[2])
        by_level.setdefault(level_id, []).append(_bat_row_to_player(r))
    for r in pitcher_rows:
        level_id = int(r[2])
        by_level.setdefault(level_id, []).append(_pit_row_to_player(r))

    levels: list[PressureLevelGroup] = []
    for level_id in _PIPELINE_LEVELS:
        players = by_level.get(level_id, [])
        if not players:
            continue
        # DESC by metric for promotion, ASC for pressure. Tiebreak
        # on volume (more PA / outs = more confidence in the rate).
        promotion_sorted = sorted(
            players,
            key=lambda p: (
                -p.metric,
                -(p.pa or int((p.ip or 0) * 3)),
            ),
        )
        pressure_sorted = sorted(
            players,
            key=lambda p: (
                p.metric,
                -(p.pa or int((p.ip or 0) * 3)),
            ),
        )
        # Cap each side, but if a level has fewer than 2*limit
        # players, the top-of-pressure list will overlap with the
        # bottom-of-promotion list. That's fine — small levels render
        # naturally with the same handful of players showing up on
        # both sides (and the user sees they're the only options).
        levels.append(
            PressureLevelGroup(
                level_id=level_id,
                level_name=LEVEL_NAMES.get(level_id, f"Level {level_id}"),
                qualifying_count=len(players),
                promotion_candidates=promotion_sorted[:resolved_limit],
                pressure_cases=pressure_sorted[:resolved_limit],
            )
        )

    return PressureResponse(
        year=resolved_year,
        available_years=available_years,
        org_team_id=org_team_id,
        levels=levels,
    )
