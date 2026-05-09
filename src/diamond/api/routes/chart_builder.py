"""Chart Builder endpoint — backs the redesigned /explore page.

Endpoint:
- ``GET /api/chart-builder?x=&y=&color=&year=&level_id=&league_id=&qualifier_min=&limit=``
  — row-per-player dataset for one or two stats. Mode auto-detects
  from `y`: present → scatter; absent → histogram (y=null in payload,
  frontend bins client-side).

Reuses the ``LEADERBOARD_STATS`` catalog so we don't maintain two
"what stats are exposable" lists. Each stat has a known source table
+ value expression; the route LEFT-JOINs the requested tables into
one wide row keyed on (player_id, year, league_id, level_id) and
emits the projection.

Cross-table support (v1): all supported stats key on the same grain,
so JOINing is straightforward. Counting tables (`f_player_season_*`)
need a `split_id = 1` filter + GROUP BY to collapse stints; advanced
+ Statcast tables are pre-aggregated and don't carry split_id (same
distinction handled in the leaderboards route).

Qualifier: a single stat picks its own qualifier (PA for batting, IP
for pitching, BIP for Statcast). When X and Y disagree (rare —
"Avg EV vs ERA" picks BIP for X and IP for Y), we use the X stat's
qualifier as the primary gate and add the Y stat's qualifier as a
secondary filter only if both are >0 in the row.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.routes.leaderboards import (
    LEADERBOARD_STATS,
    StatSpec,
    _BAT,
    _PIT,
)
from diamond.api.schemas import (
    ChartBuilderPoint,
    ChartBuilderResponse,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()


# Tables that hold split_id (counting tables) — others are pre-aggregated.
_HAS_SPLIT = {_BAT, _PIT}


def _build_subquery(spec: StatSpec, alias: str) -> str:
    """SQL fragment that produces (player_id, year, league_id, level_id, value)
    for one stat, ready to be LEFT JOIN'd by the outer query.

    Pre-aggregated tables (advanced / Statcast) don't have `split_id`
    so we skip that filter for them. The qualifier_expr is also
    surfaced so the outer SELECT can apply HAVING-style filtering.
    """
    base_split_filter = "AND split_id = 1" if spec.table in _HAS_SPLIT else ""
    return f"""
    SELECT
        player_id, year, league_id, level_id,
        {spec.value_expr}     AS {alias}_value,
        {spec.qualifier_expr} AS {alias}_qual
    FROM {spec.table}
    WHERE year = ? AND level_id = ?
          {base_split_filter}
          {{league_filter}}
    GROUP BY player_id, year, league_id, level_id
    """


def _latest_year_with_data(con: duckdb.DuckDBPyConnection, level_id: int) -> int:
    """Most recent year with any batting rows at this level.

    Mirrors the leaderboards helper — same fallback behavior so the
    two routes resolve "year omitted" identically.
    """
    row = con.execute(
        f"""
        SELECT MAX(year) FROM {_BAT}
        WHERE level_id = ? AND split_id = 1
        """,
        [level_id],
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 2026


@router.get("/chart-builder", response_model=ChartBuilderResponse)
def chart_builder(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    x: Annotated[str, Query(description="X-axis stat id (LEADERBOARD_STATS keys)")],
    y: Annotated[str | None, Query(description="Y-axis stat id (omit for histogram)")] = None,
    color: Annotated[str | None, Query(description="Optional color-encoding stat")] = None,
    year: Annotated[int | None, Query()] = None,
    level_id: Annotated[int, Query(ge=1, le=8)] = 1,
    league_id: Annotated[int | None, Query()] = None,
    qualifier_min: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> ChartBuilderResponse:
    """Row-per-player dataset for the Chart Builder.

    - X is required; Y + color are optional.
    - Returns up to `limit` rows ordered by X descending (so Plot.dot
      doesn't have to re-sort if it wants strict z-order).
    - Qualifier defaults to the X stat's `default_min`. Override via
      `qualifier_min`.
    """
    x_spec = LEADERBOARD_STATS.get(x)
    if x_spec is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown X stat '{x}'."
        )
    y_spec = LEADERBOARD_STATS.get(y) if y else None
    if y and y_spec is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown Y stat '{y}'."
        )
    color_spec = LEADERBOARD_STATS.get(color) if color else None
    if color and color_spec is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown color stat '{color}'."
        )

    resolved_year = year if year is not None else _latest_year_with_data(cursor, level_id)
    resolved_qual_min = (
        qualifier_min if qualifier_min is not None else x_spec.default_min
    )

    league_filter = "AND league_id = ?" if league_id is not None else ""
    league_args: list[object] = [league_id] if league_id is not None else []

    # Build a CTE per requested stat. Use distinct aliases so duplicate
    # stats (e.g., the same stat picked for X and color) don't collide.
    specs: list[tuple[StatSpec, str]] = [(x_spec, "x")]
    if y_spec:
        specs.append((y_spec, "y"))
    if color_spec and color_spec.id != x_spec.id and (
        not y_spec or color_spec.id != y_spec.id
    ):
        specs.append((color_spec, "color"))

    cte_blocks: list[str] = []
    cte_args: list[object] = []
    select_value_cols: list[str] = []
    select_qual_cols: list[str] = []
    for spec, alias in specs:
        block = _build_subquery(spec, alias).replace("{league_filter}", league_filter)
        cte_blocks.append(f"{alias}_cte AS ({block})")
        cte_args += [resolved_year, level_id, *league_args]
        select_value_cols.append(f"{alias}_cte.{alias}_value")
        select_qual_cols.append(f"{alias}_cte.{alias}_qual")

    # Dominant-team subquery for the team_abbr column. Always uses the
    # counting table (which has split_id) for stability across X-stat
    # source choices.
    dominant_source = (
        _PIT if x_spec.discipline.startswith("pitching") else _BAT
    )
    dominant_qual = "outs" if x_spec.discipline.startswith("pitching") else "pa"

    # Compose the final SQL. The first stat's CTE drives the FROM (so
    # rows missing from x_cte are dropped); subsequent CTEs LEFT JOIN.
    # Filter on x's qualifier_value >= resolved_qual_min as the primary
    # gate; if y was requested, also require y_qual > 0 so a player
    # with PA but no IP doesn't pollute "ERA vs OPS+" charts.
    lead_alias = "x"
    join_clauses = [
        f"LEFT JOIN {a}_cte USING (player_id, year, league_id, level_id)"
        for _, a in specs[1:]
    ]
    aux_qual_filters = (
        ["y_cte.y_qual > 0"] if y_spec else []
    )
    # Build select expressions
    x_color_value = "x_cte.x_value"
    y_value = "y_cte.y_value" if y_spec else "NULL"
    color_value = (
        f"{color_spec.id == x_spec.id and 'x_cte.x_value' or color_spec.id == (y_spec and y_spec.id) and 'y_cte.y_value' or 'color_cte.color_value'}"
        if color_spec else "NULL"
    )

    sql = f"""
    WITH {",".join(cte_blocks)},
    dom_team AS (
        SELECT player_id, year, league_id, level_id, team_id
        FROM (
            SELECT player_id, year, league_id, level_id, team_id, {dominant_qual},
                   ROW_NUMBER() OVER (
                       PARTITION BY player_id, year, league_id, level_id
                       ORDER BY {dominant_qual} DESC, team_id ASC
                   ) AS rn
            FROM {dominant_source}
            WHERE year = ? AND level_id = ? AND split_id = 1 {league_filter}
        ) WHERE rn = 1
    )
    SELECT
        x_cte.player_id, x_cte.year, x_cte.league_id, x_cte.level_id,
        p.first_name || ' ' || p.last_name AS player_name,
        t.abbr AS team_abbr,
        {x_color_value}      AS x_value,
        {y_value}            AS y_value,
        {color_value}        AS color_value,
        x_cte.x_qual         AS qualifier_value
    FROM {lead_alias}_cte
    {" ".join(join_clauses)}
    LEFT JOIN dom_team dt USING (player_id, year, league_id, level_id)
    LEFT JOIN players_current p ON p.player_id = x_cte.player_id
    LEFT JOIN teams t           ON t.team_id  = dt.team_id
    WHERE x_cte.x_qual >= ?
          {" AND " + " AND ".join(aux_qual_filters) if aux_qual_filters else ""}
    ORDER BY x_cte.x_value DESC NULLS LAST
    LIMIT ?
    """

    args = list(cte_args)
    args += [resolved_year, level_id, *league_args]  # dom_team
    args += [resolved_qual_min, limit]

    raw = cursor.execute(sql, args).fetchall()

    points = [
        ChartBuilderPoint(
            player_id=int(r[0]),
            player_name=r[4] or f"#{int(r[0])}",
            team_abbr=r[5],
            year=int(r[1]) if r[1] is not None else None,
            x=float(r[6]) if r[6] is not None else None,
            y=float(r[7]) if r[7] is not None else None,
            color=float(r[8]) if r[8] is not None else None,
            qualifier_value=int(r[9] or 0),
        )
        for r in raw
    ]

    return ChartBuilderResponse(
        mode="scatter" if y_spec else "histogram",
        x_stat=x_spec.id,
        y_stat=y_spec.id if y_spec else None,
        color_stat=color_spec.id if color_spec else None,
        year=resolved_year,
        level_id=level_id,
        league_id=league_id,
        qualifier_min=resolved_qual_min,
        points=points,
    )
