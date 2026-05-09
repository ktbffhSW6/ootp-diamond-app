"""Records leaderboards endpoint — backs the ``/history/records`` page.

Endpoint:
- ``GET /api/records?scope=&discipline=&category=&era=&limit=`` — top-N
  rows for one (scope × discipline × category) leaderboard with an
  optional era filter. Defaults: scope=season, discipline=batting,
  category=HR, era=all, limit=25.

Implementation notes:

- Source table is ``f_record_player`` (L3 fact). Pre-ranked per source;
  this route either re-ranks across sources (era=all) or filters to a
  source bucket and uses the stored ``rank_in_source`` (era=save / real
  / statcast).
- "real" is a UI-side alias for {lahman, bref, merged} — the user thinks
  in "real-life MLB history" terms; we map that to the underlying
  source enum at the SQL layer.
- All four args are forgiving: bad scope/discipline/category/era values
  fall back to defaults rather than 404'ing, matching the standings
  route's "deep-linked URLs stay forgiving" behavior.
- ``available_categories`` is computed per (scope, discipline) at request
  time so the picker only offers leaderboards that have data. Ordering
  matches the CLI's category lists (the canonical Bref ordering).
- Category labels + unit labels are hardcoded in this module rather
  than read from ``diamond.dictionary`` because the records vocabulary
  uses short keys (HR, RBI, MAX_EV) that don't map 1:1 to dictionary
  ids. When the dictionary grows entries for these record-specific
  keys, switch to dictionary lookup.

Direction handling: pitching rate-stats-allowed (AVG_EV, BARREL_PCT,
HARD_HIT_PCT, SWEET_SPOT_PCT) sort ASC — lowest = rank 1, the
achievement. Everything else sorts DESC. The category metadata
surfaces this so the UI can prefix "Fewest" vs "Most" when rendering
the page header.
"""

from __future__ import annotations

from typing import Annotated, Any

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import (
    RecordCategoryRef,
    RecordRow,
    RecordsResponse,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Defaults + validation
# ─────────────────────────────────────────────────────────────────────────────


_DEFAULT_SCOPE = "season"
_DEFAULT_DISCIPLINE = "batting"
_DEFAULT_CATEGORY = "HR"
_DEFAULT_ERA = "all"
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100  # cap so a hand-typed ?limit=10000 stays sensible

_VALID_SCOPES = {"season", "career"}
_VALID_DISCIPLINES = {"batting", "pitching"}
_VALID_ERAS = {"all", "save", "real", "statcast"}

# Era enum → list of underlying f_record_player.source values.
_ERA_TO_SOURCES: dict[str, list[str]] = {
    "all":      ["save", "lahman", "bref", "merged", "statcast"],
    "save":     ["save"],
    "real":     ["lahman", "bref", "merged"],
    "statcast": ["statcast"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Category vocabulary — mirrors the CLI's category lists (records.py)
# ─────────────────────────────────────────────────────────────────────────────


# Per-(scope, discipline) ordered category list. Ordering matches the
# Bref-canonical leaderboard ordering: counting stats first
# (HR/RBI/R/H/BB/SB/2B/3B/PA/WAR), then Statcast (MAX_EV/AVG_EV/HH%/Brl%/SS%/MAX_DIST).
_CATEGORIES_BY_AXES: dict[tuple[str, str], list[str]] = {
    ("season", "batting"):  ["HR", "RBI", "R", "H", "BB", "SB", "2B", "3B", "PA", "WAR",
                             "MAX_EV", "AVG_EV", "HARD_HIT_PCT", "BARREL_PCT",
                             "SWEET_SPOT_PCT", "MAX_DIST"],
    ("career", "batting"):  ["HR", "RBI", "R", "H", "BB", "SB", "PA", "WAR",
                             "MAX_EV", "MAX_DIST"],
    ("season", "pitching"): ["W", "S", "K", "IP", "SHO", "CG", "QS", "WAR",
                             "MAX_EV", "AVG_EV", "HARD_HIT_PCT", "BARREL_PCT",
                             "SWEET_SPOT_PCT", "MAX_DIST"],
    ("career", "pitching"): ["W", "S", "K", "IP", "SHO", "CG", "WAR",
                             "MAX_EV", "MAX_DIST"],
}


# Display labels (full English) — used in the page header and picker tooltips.
_CATEGORY_LABEL: dict[str, str] = {
    "HR": "Home Runs", "RBI": "Runs Batted In", "R": "Runs",
    "H": "Hits", "BB": "Walks", "SB": "Stolen Bases",
    "2B": "Doubles", "3B": "Triples", "PA": "Plate Appearances",
    "WAR": "Wins Above Replacement",
    "W": "Wins", "S": "Saves", "K": "Strikeouts", "IP": "Innings Pitched",
    "SHO": "Shutouts", "CG": "Complete Games", "QS": "Quality Starts",
    "MAX_EV": "Max Exit Velocity",
    "AVG_EV": "Avg Exit Velocity",
    "HARD_HIT_PCT": "Hard-Hit %",
    "BARREL_PCT": "Barrel %",
    "SWEET_SPOT_PCT": "Sweet-Spot %",
    "MAX_DIST": "Max Hit Distance",
}


# Unit suffix appended after the value in the UI ("100.5 mph", "27.5%").
_CATEGORY_UNIT: dict[str, str] = {
    "MAX_EV": "mph", "AVG_EV": "mph",
    "HARD_HIT_PCT": "%", "BARREL_PCT": "%", "SWEET_SPOT_PCT": "%",
    "MAX_DIST": "ft",
    # IP renders as "172.1" baseball convention — handled in formatter,
    # no unit suffix.
}


# ─────────────────────────────────────────────────────────────────────────────
# Argument coercion — forgiving fallbacks (deep-linked URLs stay alive)
# ─────────────────────────────────────────────────────────────────────────────


def _coerce_axes(scope: str | None, discipline: str | None) -> tuple[str, str]:
    """Map raw query strings to (scope, discipline). Falls back to
    defaults on any mismatch — empty string, typo, capitalization."""
    s = (scope or "").lower()
    d = (discipline or "").lower()
    if s not in _VALID_SCOPES:
        s = _DEFAULT_SCOPE
    if d not in _VALID_DISCIPLINES:
        d = _DEFAULT_DISCIPLINE
    return s, d


def _coerce_category(scope: str, discipline: str, raw: str | None) -> str:
    """Pick a category for the given axes. Falls back to the first
    available category for those axes (HR for batting, W for pitching,
    by ordering convention)."""
    cats = _CATEGORIES_BY_AXES.get((scope, discipline), [])
    if not cats:
        return _DEFAULT_CATEGORY  # shouldn't hit; defensive
    if raw and raw.upper() in cats:
        return raw.upper()
    return cats[0]


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


def _fetch_available_categories(
    con: duckdb.DuckDBPyConnection,
    scope: str,
    discipline: str,
) -> list[RecordCategoryRef]:
    """List every (category, direction, sources[]) tuple that has at
    least one row at this (scope, discipline). Output ordered by the
    canonical category list above; categories absent from the warehouse
    are skipped (e.g., a fresh save without `fetch-history` won't have
    Statcast records, so those entries drop out)."""
    rows = con.execute(
        """
        SELECT category, direction, source, COUNT(*) AS n
        FROM f_record_player
        WHERE scope = ? AND discipline = ?
        GROUP BY category, direction, source
        """,
        [scope, discipline],
    ).fetchall()

    # Coalesce rows into category → (direction, source set).
    by_cat: dict[str, dict[str, Any]] = {}
    for cat, direction, source, _n in rows:
        entry = by_cat.setdefault(
            cat, {"direction": direction, "sources": set()},
        )
        entry["sources"].add(source)
        # Direction within a category should be stable; first row wins.

    canonical_order = _CATEGORIES_BY_AXES.get((scope, discipline), [])
    out: list[RecordCategoryRef] = []
    for cat in canonical_order:
        entry = by_cat.get(cat)
        if entry is None:
            continue
        # Sources ordered by the conventional save → lahman → bref →
        # merged → statcast progression for stable rendering.
        sources_ordered = [
            s for s in ("save", "lahman", "bref", "merged", "statcast")
            if s in entry["sources"]
        ]
        out.append(
            RecordCategoryRef(
                category=cat,
                label=_CATEGORY_LABEL.get(cat, cat),
                unit_label=_CATEGORY_UNIT.get(cat, ""),
                direction=entry["direction"],
                available_sources=sources_ordered,  # type: ignore[arg-type]
            )
        )
    return out


def _fetch_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    scope: str,
    discipline: str,
    category: str,
    sources: list[str],
    direction: str,
    limit: int,
) -> tuple[list[RecordRow], int]:
    """Pull all matching rows for the (scope, discipline, category)
    intersected with the era's source list, then re-rank globally
    (the source's stored ``rank_in_source`` is per-source, so a
    multi-source query needs a fresh rank). Returns
    ``(rows, total_in_source)`` — the second is the total count
    *before* the LIMIT is applied so the UI can render
    "showing top 25 of 150" hints.
    """
    if not sources:
        return [], 0

    placeholders = ", ".join("?" for _ in sources)
    sort_dir = "ASC" if direction == "asc" else "DESC"
    args = [scope, discipline, category, *sources]

    total = con.execute(
        f"""
        SELECT COUNT(*) FROM f_record_player
        WHERE scope = ? AND discipline = ? AND category = ?
          AND source IN ({placeholders})
        """,
        args,
    ).fetchone()[0]

    rows = con.execute(
        f"""
        SELECT
            rank_in_source, source, player_id, external_id,
            display_name, year, team_abbr, value
        FROM f_record_player
        WHERE scope = ? AND discipline = ? AND category = ?
          AND source IN ({placeholders})
        ORDER BY value {sort_dir}, rank_in_source ASC
        LIMIT ?
        """,
        [*args, limit],
    ).fetchall()

    out: list[RecordRow] = []
    for new_rank, r in enumerate(rows, start=1):
        (rank_in_source, source, player_id, external_id,
         display_name, year, team_abbr, value) = r
        out.append(
            RecordRow(
                rank=new_rank,
                rank_in_source=int(rank_in_source),
                source=source,
                player_id=int(player_id) if player_id is not None else None,
                external_id=external_id,
                display_name=display_name,
                year=int(year) if year is not None else None,
                team_abbr=team_abbr,
                value=float(value) if value is not None else 0.0,
            )
        )
    return out, int(total)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/records", response_model=RecordsResponse)
def get_records(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    scope: Annotated[
        str | None,
        Query(description="season | career"),
    ] = None,
    discipline: Annotated[
        str | None,
        Query(description="batting | pitching"),
    ] = None,
    category: Annotated[
        str | None,
        Query(
            description=(
                "Stat code (HR, RBI, WAR, MAX_EV, etc.) — depends on "
                "scope+discipline. See the available_categories list "
                "for the legal values at the chosen axes."
            ),
        ),
    ] = None,
    era: Annotated[
        str | None,
        Query(description="all | save | real | statcast"),
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=_MAX_LIMIT, description=f"Top-N rows. Defaults to {_DEFAULT_LIMIT}."),
    ] = None,
) -> RecordsResponse:
    """One leaderboard, top-N rows, optionally filtered to a source bucket."""
    resolved_scope, resolved_discipline = _coerce_axes(scope, discipline)
    resolved_era = _coerce_era(era)
    resolved_limit = _coerce_limit(limit)

    # Available categories — used both to validate the picker AND to
    # narrow the requested category to a legal value. If the user
    # passes a category that's available in the warehouse but not
    # listed in our canonical order, we still fall back to default.
    available_categories = _fetch_available_categories(
        con, resolved_scope, resolved_discipline,
    )
    available_keys = {c.category for c in available_categories}

    if category and category.upper() in available_keys:
        resolved_category = category.upper()
    elif _DEFAULT_CATEGORY in available_keys:
        resolved_category = _DEFAULT_CATEGORY
    elif available_categories:
        resolved_category = available_categories[0].category
    else:
        # No data at all — empty response with sane defaults so the
        # frontend can render a "no records yet" state.
        return RecordsResponse(
            scope=resolved_scope,  # type: ignore[arg-type]
            discipline=resolved_discipline,  # type: ignore[arg-type]
            category=_DEFAULT_CATEGORY,
            era=resolved_era,  # type: ignore[arg-type]
            direction="desc",
            available_categories=[],
            rows=[],
            total_in_source=0,
        )

    # Look up direction + sources from available_categories so we
    # don't refetch.
    category_meta = next(
        c for c in available_categories if c.category == resolved_category
    )
    requested_sources = _ERA_TO_SOURCES[resolved_era]
    # Intersect: only query sources actually present for this category.
    effective_sources = [
        s for s in requested_sources if s in category_meta.available_sources
    ]

    rows, total = _fetch_rows(
        con,
        scope=resolved_scope,
        discipline=resolved_discipline,
        category=resolved_category,
        sources=effective_sources,
        direction=category_meta.direction,
        limit=resolved_limit,
    )

    return RecordsResponse(
        scope=resolved_scope,  # type: ignore[arg-type]
        discipline=resolved_discipline,  # type: ignore[arg-type]
        category=resolved_category,
        era=resolved_era,  # type: ignore[arg-type]
        direction=category_meta.direction,
        available_categories=available_categories,
        rows=rows,
        total_in_source=total,
    )
