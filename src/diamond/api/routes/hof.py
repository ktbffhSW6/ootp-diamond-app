"""Hall of Fame endpoint — backs ``/history/hof``.

Endpoint:
- ``GET /api/hof?view=&limit=`` — either the inductees roster or the
  candidates list. Defaults: view=inductees, limit=25 for candidates
  (inductees aren't capped — show all 285).

Implementation notes:

- Inductees come from ``players_current.hall_of_fame = 1``, ordered
  by ``inducted DESC NULLS LAST`` (recent first; null inducted means
  pre-tracking enshrinement).
- Candidates come from the ``f_record_player`` career-WAR leaderboard
  (top WAR holders) filtered to bbref-id-resolvable players whose
  ``hall_of_fame`` flag is 0. The ranking is by career batting WAR
  (the canonical "Hall worthiness" proxy in fWAR-era thinking;
  pitchers with high career pitching-WAR are picked up via the
  same `f_record_player` rollup since the career-WAR record is
  per-discipline).
- Career WAR for inductee rows comes from
  ``f_player_season_advanced_batting`` summed across the player's
  seasons. Non-batters return null (UI renders a dash).
- ``last_team_abbr`` is from ``players_current.team_id`` → ``teams.abbr``
  for active retirees, null for ancient retirees whose final team
  didn't survive the dump's team-history tracking.

Why no era picker: HoF flag is save-only (OOTP imports the real
Cooperstown roster as save data, so the inductees view already
shows real-life HoFers — Aaron, Mays, Mantle — alongside in-save
inductees like Pujols 2028 / Cabrera 2029).
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import HofPlayer, HofResponse
from diamond.api.warehouse import get_cursor

router = APIRouter()


_DEFAULT_VIEW = "inductees"
_DEFAULT_CANDIDATES_LIMIT = 25
_MAX_LIMIT = 100

_VALID_VIEWS = {"inductees", "candidates"}


def _coerce_view(raw: str | None) -> str:
    v = (raw or "").lower()
    if v not in _VALID_VIEWS:
        v = _DEFAULT_VIEW
    return v


def _coerce_limit(raw: int | None) -> int:
    if raw is None:
        return _DEFAULT_CANDIDATES_LIMIT
    if raw < 1:
        return _DEFAULT_CANDIDATES_LIMIT
    if raw > _MAX_LIMIT:
        return _MAX_LIMIT
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────


# Inductees — every player flagged hall_of_fame=1 in players_current,
# joined to f_player_season_advanced_batting for career WAR (summed
# across all seasons) and to teams for the last-known team abbr.
#
# career_war is null for pure-pitcher inductees (no advanced-batting
# rows). Pitcher career WAR could be UNIONed in via
# f_player_season_advanced_pitching.p_war but that requires a separate
# query path — deferred. For v1 the dash on pitcher rows is acceptable.
_INDUCTEES_QUERY = """
WITH career_bat_war AS (
    SELECT player_id, ROUND(SUM(b_war), 1) AS war
    FROM f_player_season_advanced_batting
    GROUP BY player_id
),
career_pit_war AS (
    SELECT player_id, ROUND(SUM(p_war), 1) AS war
    FROM f_player_season_advanced_pitching
    GROUP BY player_id
)
SELECT
    pc.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    pc.inducted,
    pc.retired,
    COALESCE(cb.war, cp.war) AS career_war,
    t.abbr AS last_team_abbr
FROM players_current pc
LEFT JOIN career_bat_war cb USING (player_id)
LEFT JOIN career_pit_war cp USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE pc.hall_of_fame = 1
ORDER BY pc.inducted DESC NULLS LAST, display_name
"""


# Candidates — top career-batting-WAR players who are NOT yet inducted.
# Joined to players_current to get current name + retired flag + last
# team. The career-WAR sort is the Hall-worthiness proxy.
#
# Limit applied at SQL level since we don't need the full sorted set.
# Pitcher candidates are surfaced via the same WAR rollup (the
# f_record_player "career WAR" lookup is batting-only; we'd need a
# pitching variant for pure pitchers — Verlander, Clemens — to show.
# For v1 the batting-WAR ranking covers most marquee non-inductees.
_CANDIDATES_QUERY = """
WITH career_bat_war AS (
    SELECT player_id, ROUND(SUM(b_war), 1) AS war
    FROM f_player_season_advanced_batting
    GROUP BY player_id
),
career_pit_war AS (
    SELECT player_id, ROUND(SUM(p_war), 1) AS war
    FROM f_player_season_advanced_pitching
    GROUP BY player_id
),
combined_war AS (
    SELECT
        COALESCE(cb.player_id, cp.player_id) AS player_id,
        GREATEST(COALESCE(cb.war, 0), COALESCE(cp.war, 0)) AS war
    FROM career_bat_war cb
    FULL OUTER JOIN career_pit_war cp USING (player_id)
)
SELECT
    pc.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    NULL::BIGINT AS inducted,
    pc.retired,
    cw.war AS career_war,
    t.abbr AS last_team_abbr
FROM combined_war cw
JOIN players_current pc USING (player_id)
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE pc.hall_of_fame = 0
ORDER BY cw.war DESC NULLS LAST, display_name
LIMIT ?
"""


_INDUCTEES_COUNT_QUERY = (
    "SELECT COUNT(*) FROM players_current WHERE hall_of_fame = 1"
)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/hof", response_model=HofResponse)
def get_hof(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    view: Annotated[
        str | None,
        Query(description="inductees | candidates"),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            ge=1, le=_MAX_LIMIT,
            description=(
                f"Top-N candidates (inductees aren't capped). Defaults to "
                f"{_DEFAULT_CANDIDATES_LIMIT}."
            ),
        ),
    ] = None,
) -> HofResponse:
    """Hall of Fame inductees or candidates."""
    resolved_view = _coerce_view(view)
    resolved_limit = _coerce_limit(limit)

    inductees_count = int(con.execute(_INDUCTEES_COUNT_QUERY).fetchone()[0])

    if resolved_view == "inductees":
        rows_raw = con.execute(_INDUCTEES_QUERY).fetchall()
        rows = [
            HofPlayer(
                player_id=int(r[0]),
                display_name=r[1],
                inducted_year=int(r[2]) if r[2] is not None else None,
                rank=None,  # ordered by induction year, not WAR rank
                career_war=float(r[4]) if r[4] is not None else None,
                last_team_abbr=r[5],
                retired=bool(r[3]) if r[3] is not None else True,
            )
            for r in rows_raw
        ]
        return HofResponse(
            view="inductees",
            rows=rows,
            inductees_count=inductees_count,
            candidates_count=resolved_limit,
        )

    # candidates
    rows_raw = con.execute(_CANDIDATES_QUERY, [resolved_limit]).fetchall()
    rows: list[HofPlayer] = []
    for rank, r in enumerate(rows_raw, start=1):
        rows.append(
            HofPlayer(
                player_id=int(r[0]),
                display_name=r[1],
                inducted_year=None,
                rank=rank,
                career_war=float(r[4]) if r[4] is not None else None,
                last_team_abbr=r[5],
                retired=bool(r[3]) if r[3] is not None else False,
            )
        )
    return HofResponse(
        view="candidates",
        rows=rows,
        inductees_count=inductees_count,
        candidates_count=len(rows),
    )
