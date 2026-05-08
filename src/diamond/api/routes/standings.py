"""Standings endpoint — backs the ``/league`` page's standings tab.

Endpoint:
- ``GET /api/standings?league_id=&year=`` — sub-league × division × team
  rows for the selected scoped league at the latest dump in the chosen
  year. Defaults: league = MLB (203), year = latest year with any
  standings data.

Implementation notes:

- Source table is ``team_record_snapshot`` (one row per team per dump).
  We resolve a single ``(league_id, year)`` to its MAX(dump_date) and
  pull every team in that league at that snapshot.
- All-Star teams have ``g=0`` in the snapshot — the league registers
  them as roster slots but they don't play a real schedule. Filter them
  out at the WHERE clause.
- ``magic_number`` carries two OOTP sentinels:
    -1   → division clinched (we surface as ``clinched=True``,
           ``magic_number=None``)
    1000 → not applicable / out of contention (we surface as
           ``clinched=False``, ``magic_number=None``)
  Anything else passes through.
- Sub-league + division metadata comes from the ``sub_leagues`` and
  ``divisions`` reference tables. Both are nullable in the JOIN — many
  scoped leagues have only divisions (AAA/AA/A), or nothing at all
  (AFL is one flat list).

Available-leagues list is derived from ``team_record_snapshot`` JOINed
to ``leagues`` so we never expose a league that has no standings rows
(historical sims, deleted leagues, etc.).

Known limitation: AFL (league_id=70) is in the scope but absent from
the ``leagues`` table — it ships with team rows but no league-meta row,
so the JOIN drops it from ``available_leagues``. Acceptable for v1
(AFL is a 30-game fall league, niche standings). When the user hand-
types ``?league_id=70`` we fall back to MLB rather than 404 — the
picker never offers it, so no normal flow hits this.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import (
    StandingsDivision,
    StandingsLeagueRef,
    StandingsResponse,
    StandingsSubLeague,
    StandingsTeamRow,
)
from diamond.api.warehouse import get_active_save, get_cursor

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Magic number / streak helpers
# ─────────────────────────────────────────────────────────────────────────────
#
# OOTP sentinels in `team_record_snapshot.magic_number`:
#   -1   → clinched (division leader who has mathematically secured)
#   1000 → "not applicable" — out of contention OR season hasn't reached
#          the point where magic is meaningful. Both render as null.
# Any other value passes through as the live magic number.
_MAGIC_CLINCHED = -1
_MAGIC_NA = 1000


def _resolve_magic(raw: int | None) -> tuple[int | None, bool]:
    """Map raw `magic_number` to (surfaced_value, clinched_flag)."""
    if raw is None:
        return None, False
    if raw == _MAGIC_CLINCHED:
        return None, True
    if raw == _MAGIC_NA:
        return None, False
    return int(raw), False


# ─────────────────────────────────────────────────────────────────────────────
# Query builders
# ─────────────────────────────────────────────────────────────────────────────


_AVAILABLE_LEAGUES_QUERY = """
SELECT DISTINCT
    l.league_id,
    l.abbr,
    l.name,
    l.league_level
FROM team_record_snapshot trs
JOIN teams t  ON t.team_id = trs.team_id
JOIN leagues l ON l.league_id = t.league_id
WHERE trs.g > 0
ORDER BY l.league_level, l.league_id
"""


_AVAILABLE_YEARS_QUERY = """
SELECT DISTINCT EXTRACT(YEAR FROM trs.dump_date)::INTEGER AS yr
FROM team_record_snapshot trs
JOIN teams t ON t.team_id = trs.team_id
WHERE t.league_id = ?
  AND trs.g > 0
ORDER BY yr DESC
"""


_RESOLVED_DUMP_QUERY = """
SELECT MAX(trs.dump_date)
FROM team_record_snapshot trs
JOIN teams t ON t.team_id = trs.team_id
WHERE t.league_id = ?
  AND EXTRACT(YEAR FROM trs.dump_date) = ?
  AND trs.g > 0
"""


_LEAGUE_META_QUERY = """
SELECT league_id, abbr, name, league_level
FROM leagues
WHERE league_id = ?
"""


_STANDINGS_QUERY = """
SELECT
    t.sub_league_id,
    sl.name AS sub_league_name,
    t.division_id,
    d.name  AS division_name,
    trs.team_id,
    t.abbr,
    t.nickname,
    trs.g, trs.w, trs.l, trs.t,
    trs.pct, trs.gb, trs.streak, trs.magic_number,
    trs.pos
FROM team_record_snapshot trs
JOIN teams t ON t.team_id = trs.team_id
LEFT JOIN sub_leagues sl
       ON sl.league_id = t.league_id
      AND sl.sub_league_id = t.sub_league_id
LEFT JOIN divisions d
       ON d.league_id = t.league_id
      AND d.sub_league_id = t.sub_league_id
      AND d.division_id = t.division_id
WHERE t.league_id = ?
  AND trs.dump_date = ?
  AND trs.g > 0
ORDER BY t.sub_league_id, t.division_id, trs.pos
"""


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_LEAGUE_ID = 203  # MLB — the most-watched scope


@router.get("/standings", response_model=StandingsResponse)
def get_standings(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    league_id: Annotated[
        int | None,
        Query(description="Scoped league_id. Defaults to MLB (203)."),
    ] = None,
    year: Annotated[
        int | None,
        Query(description="Season year. Defaults to latest year with data."),
    ] = None,
) -> StandingsResponse:
    """League standings at one dump_date snapshot.

    Resolves to MAX(dump_date) within the selected year — that's the
    end-of-season cut for past years and the most-recent monthly dump
    for the live year.
    """
    save = get_active_save()
    org_team_id = save.audit_team_id

    # Available leagues — every league with at least one real standings row.
    available_leagues = [
        StandingsLeagueRef(
            league_id=int(r[0]),
            abbr=r[1],
            name=r[2],
            league_level=int(r[3]) if r[3] is not None else 0,
        )
        for r in con.execute(_AVAILABLE_LEAGUES_QUERY).fetchall()
    ]
    if not available_leagues:
        raise HTTPException(
            status_code=404,
            detail="No standings data in the warehouse.",
        )

    available_league_ids = {ref.league_id for ref in available_leagues}
    resolved_league_id = (
        league_id if league_id is not None else _DEFAULT_LEAGUE_ID
    )
    if resolved_league_id not in available_league_ids:
        # Fall back to the highest-level (lowest league_level) league with
        # data — matches "give me the most-watched standings" intent
        # better than 404'ing on a misspelled query string.
        resolved_league_id = available_leagues[0].league_id

    # Available years for this league.
    available_years = [
        int(r[0])
        for r in con.execute(
            _AVAILABLE_YEARS_QUERY, [resolved_league_id]
        ).fetchall()
    ]
    if not available_years:
        raise HTTPException(
            status_code=404,
            detail=f"No standings data for league {resolved_league_id}.",
        )

    resolved_year = year if year is not None else available_years[0]
    if resolved_year not in available_years:
        # Same fallback intent as league: pick latest with data rather than
        # 404. This keeps deep-linked URLs forgiving.
        resolved_year = available_years[0]

    # Resolve to a single dump_date — MAX within the chosen year.
    dump_row = con.execute(
        _RESOLVED_DUMP_QUERY, [resolved_league_id, resolved_year],
    ).fetchone()
    if not dump_row or dump_row[0] is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No dumps for league {resolved_league_id} in {resolved_year}."
            ),
        )
    resolved_dump_date: date = dump_row[0]

    league_meta = con.execute(
        _LEAGUE_META_QUERY, [resolved_league_id],
    ).fetchone()
    league_ref = StandingsLeagueRef(
        league_id=int(league_meta[0]),
        abbr=league_meta[1],
        name=league_meta[2],
        league_level=int(league_meta[3]) if league_meta[3] is not None else 0,
    )

    rows = con.execute(
        _STANDINGS_QUERY, [resolved_league_id, resolved_dump_date],
    ).fetchall()

    # Group: sub_league → division → teams. Preserve query order so
    # divisions come out in their natural OOTP arrangement.
    sub_leagues: list[StandingsSubLeague] = []
    sub_index: dict[int, StandingsSubLeague] = {}
    div_index: dict[tuple[int, int], StandingsDivision] = {}

    for r in rows:
        (
            sub_league_id, sub_league_name,
            division_id, division_name,
            team_id, abbr, nickname,
            g, w, l_, t, pct, gb, streak, magic_raw,
            pos,
        ) = r

        sub_league_id = int(sub_league_id) if sub_league_id is not None else 0
        division_id = int(division_id) if division_id is not None else 0

        sub = sub_index.get(sub_league_id)
        if sub is None:
            sub = StandingsSubLeague(
                sub_league_id=sub_league_id,
                sub_league_name=sub_league_name,
                divisions=[],
            )
            sub_index[sub_league_id] = sub
            sub_leagues.append(sub)

        div_key = (sub_league_id, division_id)
        div = div_index.get(div_key)
        if div is None:
            div = StandingsDivision(
                division_id=division_id,
                division_name=division_name,
                teams=[],
            )
            div_index[div_key] = div
            sub.divisions.append(div)

        magic_value, clinched = _resolve_magic(
            int(magic_raw) if magic_raw is not None else None
        )
        div.teams.append(
            StandingsTeamRow(
                team_id=int(team_id),
                abbr=abbr,
                nickname=nickname,
                g=int(g),
                w=int(w),
                l=int(l_),
                t=int(t),
                pct=float(pct) if pct is not None else 0.0,
                gb=float(gb) if gb is not None else 0.0,
                streak=int(streak) if streak is not None else 0,
                magic_number=magic_value,
                clinched=clinched,
                pos=int(pos) if pos is not None else 0,
                is_user_org=int(team_id) == org_team_id,
            )
        )

    return StandingsResponse(
        league=league_ref,
        year=resolved_year,
        dump_date=resolved_dump_date,
        available_leagues=available_leagues,
        available_years=available_years,
        org_team_id=org_team_id,
        sub_leagues=sub_leagues,
    )
