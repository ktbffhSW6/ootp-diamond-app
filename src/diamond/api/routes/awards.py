"""Awards leaderboards endpoint — backs ``/history/awards``.

Endpoint:
- ``GET /api/awards?league_id=&award_id=&era=&limit=`` — top-N
  trophy-count holders for one (league × award) with an optional
  era filter. Defaults: league=MLB (203), award=MVP (5), era=all,
  limit=25.

Implementation notes:

- Source table is ``f_award_career_player`` (L3 fact). Already
  rolled up to per-(player × league × award) career grain;
  ranking is just ``ORDER BY n_won DESC, last_year DESC`` with
  the era filter applied.
- "real" is a UI-side alias for ``source='merged'`` (cross-source
  Lahman + MLB Stats API dedup'd via Chadwick Register, scoped to
  bbref_ids NOT in the save). Maps that translation at the SQL
  layer.
- All four args forgiving: bad league/award/era/limit values fall
  back to defaults rather than 404'ing.
- ``available_leagues`` and ``available_awards`` are both computed
  per request: leagues from any with at least one award row;
  awards within the chosen league. Awards are ordered by prestige
  (MVP / Cy / RoY / GG / SS / Reliever / All-Star / WSC / Series
  MVP) with weekly/monthly minor awards trailing.
- Award labels are sourced from ``diamond.constants.AwardId`` +
  the same dictionary the CLI uses (see ``diamond/awards.py``
  AWARD_LABEL). Keep these aligned so terminology stays consistent
  across CLI + UI.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import (
    AwardCategoryRef,
    AwardHolderRow,
    AwardLeagueRef,
    AwardsResponse,
)
from diamond.api.warehouse import get_cursor
from diamond.constants import AwardId

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Defaults + validation
# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_LEAGUE_ID = 203  # MLB — the most-watched scope
_DEFAULT_AWARD_ID = int(AwardId.MVP)  # 5 — headline award
_DEFAULT_ERA = "all"
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100

_VALID_ERAS = {"all", "save", "real"}

# Era enum → list of underlying f_award_career_player.source values.
# "real" is the UI-side alias for cross-source merged real-life awards.
_ERA_TO_SOURCES: dict[str, list[str]] = {
    "all":    ["save", "merged"],
    "save":   ["save"],
    "real":   ["merged"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Award labels — mirror the CLI (``diamond/awards.py`` AWARD_LABEL)
#
# Keep these aligned with the CLI so users see consistent terminology
# across the terminal and the web UI. When the CLI gets new entries
# (e.g., for newly-decoded awards), add them here too.
# ─────────────────────────────────────────────────────────────────────────────


_AWARD_LABEL: dict[int, str] = {
    int(AwardId.PLAYER_OF_THE_WEEK):    "Player of the Week",
    int(AwardId.PITCHER_OF_THE_MONTH):  "Pitcher of the Month",
    int(AwardId.HITTER_OF_THE_MONTH):   "Hitter of the Month",
    int(AwardId.ROOKIE_OF_THE_MONTH):   "Rookie of the Month",
    int(AwardId.CY_YOUNG):              "Cy Young (top-3)",
    int(AwardId.MVP):                   "MVP (top-3)",
    int(AwardId.ROOKIE_OF_THE_YEAR):    "Rookie of the Year (top-3)",
    int(AwardId.GOLD_GLOVE):            "Gold Glove",
    int(AwardId.ALL_STAR):              "All-Star",
    int(AwardId.SILVER_SLUGGER):        "Silver Slugger",
    int(AwardId.RELIEVER_OF_THE_YEAR):  "Reliever of the Year",
    int(AwardId.WS_CHAMPION_ROSTER):    "WS Champion (roster)",
    int(AwardId.POSTSEASON_SERIES_MVP): "Postseason Series MVP",
}


# Picker order — MVP / Cy / RoY headlines first (the marquee awards
# users want at a glance), then per-position (GG / SS / Reliever),
# then participatory (All-Star / WS Champion / Series MVP), then
# weekly/monthly noise at the end. award_ids missing from the
# warehouse drop out at filter time.
_AWARD_PICKER_ORDER: list[int] = [
    int(AwardId.MVP),
    int(AwardId.CY_YOUNG),
    int(AwardId.ROOKIE_OF_THE_YEAR),
    int(AwardId.GOLD_GLOVE),
    int(AwardId.SILVER_SLUGGER),
    int(AwardId.RELIEVER_OF_THE_YEAR),
    int(AwardId.ALL_STAR),
    int(AwardId.WS_CHAMPION_ROSTER),
    int(AwardId.POSTSEASON_SERIES_MVP),
    int(AwardId.HITTER_OF_THE_MONTH),
    int(AwardId.PITCHER_OF_THE_MONTH),
    int(AwardId.ROOKIE_OF_THE_MONTH),
    int(AwardId.PLAYER_OF_THE_WEEK),
]


# ─────────────────────────────────────────────────────────────────────────────
# Argument coercion — forgiving fallbacks
# ─────────────────────────────────────────────────────────────────────────────


def _coerce_era(raw: str | None) -> str:
    e = (raw or "").lower()
    if e not in _VALID_ERAS:
        e = _DEFAULT_ERA
    return e


def _coerce_limit(raw: int | None) -> int:
    if raw is None:
        return _DEFAULT_LIMIT
    if raw < 1:
        return _DEFAULT_LIMIT
    if raw > _MAX_LIMIT:
        return _MAX_LIMIT
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────


_AVAILABLE_LEAGUES_QUERY = """
SELECT DISTINCT
    acp.league_id,
    l.abbr,
    l.name,
    COALESCE(l.league_level, 99) AS league_level
FROM f_award_career_player acp
LEFT JOIN leagues l ON l.league_id = acp.league_id
ORDER BY COALESCE(l.league_level, 99), acp.league_id
"""


def _fetch_available_leagues(
    con: duckdb.DuckDBPyConnection,
) -> list[AwardLeagueRef]:
    return [
        AwardLeagueRef(
            league_id=int(r[0]),
            abbr=r[1],
            name=r[2],
            league_level=int(r[3]),
        )
        for r in con.execute(_AVAILABLE_LEAGUES_QUERY).fetchall()
    ]


def _fetch_available_awards(
    con: duckdb.DuckDBPyConnection,
    league_id: int,
) -> list[AwardCategoryRef]:
    """Awards present in the selected league + which sources have data.
    Ordered by ``_AWARD_PICKER_ORDER``; awards absent from the
    warehouse are skipped, awards present but absent from the picker
    list (shouldn't happen given the AwardId enum is exhaustive) are
    appended at the end so they don't silently disappear."""
    rows = con.execute(
        """
        SELECT award_id, source
        FROM f_award_career_player
        WHERE league_id = ?
        GROUP BY award_id, source
        """,
        [league_id],
    ).fetchall()

    by_award: dict[int, set[str]] = {}
    for award_id, source in rows:
        by_award.setdefault(int(award_id), set()).add(source)

    out: list[AwardCategoryRef] = []
    seen: set[int] = set()
    for aid in _AWARD_PICKER_ORDER:
        if aid not in by_award:
            continue
        sources = sorted(
            by_award[aid],
            key=lambda s: 0 if s == "save" else 1,
        )
        out.append(
            AwardCategoryRef(
                award_id=aid,
                label=_AWARD_LABEL.get(aid, f"Award {aid}"),
                available_sources=sources,  # type: ignore[arg-type]
            )
        )
        seen.add(aid)

    # Defensive: any award_id present in data but missing from
    # _AWARD_PICKER_ORDER appears at the tail with a fallback label.
    for aid, sources_set in by_award.items():
        if aid in seen:
            continue
        sources = sorted(
            sources_set, key=lambda s: 0 if s == "save" else 1,
        )
        out.append(
            AwardCategoryRef(
                award_id=aid,
                label=_AWARD_LABEL.get(aid, f"Award {aid}"),
                available_sources=sources,  # type: ignore[arg-type]
            )
        )
    return out


def _fetch_holders(
    con: duckdb.DuckDBPyConnection,
    *,
    league_id: int,
    award_id: int,
    sources: list[str],
    limit: int,
) -> tuple[list[AwardHolderRow], int]:
    """Top-N rows for the (league, award, era→sources) intersection.

    Returns ``(rows, total_before_limit)`` so the UI can render
    "showing top 25 of 173" hints.
    """
    if not sources:
        return [], 0
    placeholders = ", ".join("?" for _ in sources)
    args = [league_id, award_id, *sources]

    total = con.execute(
        f"""
        SELECT COUNT(*) FROM f_award_career_player
        WHERE league_id = ? AND award_id = ? AND source IN ({placeholders})
        """,
        args,
    ).fetchone()[0]

    rows = con.execute(
        f"""
        SELECT
            source, player_id, external_id, display_name,
            n_won, first_year, last_year,
            first_team_abbr, last_team_abbr
        FROM f_award_career_player
        WHERE league_id = ? AND award_id = ? AND source IN ({placeholders})
        ORDER BY n_won DESC, last_year DESC NULLS LAST, display_name ASC
        LIMIT ?
        """,
        [*args, limit],
    ).fetchall()

    out: list[AwardHolderRow] = []
    for new_rank, r in enumerate(rows, start=1):
        (source, player_id, external_id, display_name,
         n_won, first_year, last_year,
         first_team_abbr, last_team_abbr) = r
        out.append(
            AwardHolderRow(
                rank=new_rank,
                source=source,
                player_id=int(player_id) if player_id is not None else None,
                external_id=external_id,
                display_name=display_name,
                n_won=int(n_won) if n_won is not None else 0,
                first_year=int(first_year) if first_year is not None else None,
                last_year=int(last_year) if last_year is not None else None,
                first_team_abbr=first_team_abbr,
                last_team_abbr=last_team_abbr,
            )
        )
    return out, int(total)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/awards", response_model=AwardsResponse)
def get_awards(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    league_id: Annotated[
        int | None,
        Query(description="Scoped league_id. Defaults to MLB (203)."),
    ] = None,
    award_id: Annotated[
        int | None,
        Query(
            description=(
                "AwardId enum value. Defaults to MVP (5). See "
                "diamond.constants.AwardId for the full enumeration."
            ),
        ),
    ] = None,
    era: Annotated[
        str | None,
        Query(description="all | save | real"),
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=_MAX_LIMIT, description=f"Top-N rows. Defaults to {_DEFAULT_LIMIT}."),
    ] = None,
) -> AwardsResponse:
    """One award's career-leader board, top-N rows."""
    resolved_era = _coerce_era(era)
    resolved_limit = _coerce_limit(limit)

    # Available leagues — every league with at least one award row.
    available_leagues = _fetch_available_leagues(con)
    if not available_leagues:
        # Empty warehouse — return an empty response with sane defaults.
        return AwardsResponse(
            league=AwardLeagueRef(
                league_id=_DEFAULT_LEAGUE_ID,
                abbr=None,
                name=None,
                league_level=1,
            ),
            award_id=_DEFAULT_AWARD_ID,
            era=resolved_era,  # type: ignore[arg-type]
            available_leagues=[],
            available_awards=[],
            rows=[],
            total_in_source=0,
        )

    available_league_ids = {lg.league_id for lg in available_leagues}
    resolved_league_id = (
        league_id if league_id is not None else _DEFAULT_LEAGUE_ID
    )
    if resolved_league_id not in available_league_ids:
        # Fall back to MLB if available, else first league with data.
        resolved_league_id = (
            _DEFAULT_LEAGUE_ID
            if _DEFAULT_LEAGUE_ID in available_league_ids
            else available_leagues[0].league_id
        )

    league_meta = next(
        lg for lg in available_leagues if lg.league_id == resolved_league_id
    )

    # Available awards in this league.
    available_awards = _fetch_available_awards(con, resolved_league_id)
    if not available_awards:
        return AwardsResponse(
            league=league_meta,
            award_id=_DEFAULT_AWARD_ID,
            era=resolved_era,  # type: ignore[arg-type]
            available_leagues=available_leagues,
            available_awards=[],
            rows=[],
            total_in_source=0,
        )

    available_award_ids = {a.award_id for a in available_awards}
    resolved_award_id = (
        award_id if award_id is not None else _DEFAULT_AWARD_ID
    )
    if resolved_award_id not in available_award_ids:
        # Default to MVP if available; else first award with data.
        resolved_award_id = (
            _DEFAULT_AWARD_ID
            if _DEFAULT_AWARD_ID in available_award_ids
            else available_awards[0].award_id
        )

    # Era → source filter, intersected with what's actually available
    # for this (league, award) so an era=real query for an award that
    # only has save data returns 0 rows + a hint instead of a stack
    # trace.
    award_meta = next(
        a for a in available_awards if a.award_id == resolved_award_id
    )
    requested_sources = _ERA_TO_SOURCES[resolved_era]
    effective_sources = [
        s for s in requested_sources if s in award_meta.available_sources
    ]

    rows, total = _fetch_holders(
        con,
        league_id=resolved_league_id,
        award_id=resolved_award_id,
        sources=effective_sources,
        limit=resolved_limit,
    )

    return AwardsResponse(
        league=league_meta,
        award_id=resolved_award_id,
        era=resolved_era,  # type: ignore[arg-type]
        available_leagues=available_leagues,
        available_awards=available_awards,
        rows=rows,
        total_in_source=total,
    )
