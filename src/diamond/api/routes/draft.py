"""Draft classes endpoint — backs ``/history/draft``.

Endpoint:
- ``GET /api/draft?year=`` — full retrospective for one draft year,
  rows grouped by outcome bucket. Default: oldest year with material
  outcome variation (for fresh classes everything is in_draft_org,
  which is a boring page).

Implementation notes:

- Source table is ``f_draft_class`` (L3 fact, ~575 rows per year).
- The route returns the *whole* class in one round-trip (~600 rows
  ≈ 70-100 KB JSON). Following the roster-page convention: ship
  everything, let the client render. Year-switching is a navigation,
  not a state change.
- Outcome buckets are sorted in fixed order (mlb_regular →
  mlb_callup → in_draft_org → traded_away → released → retired) so
  the high-impact picks render first. Within a bucket, rows sort by
  ``draft_overall_pick ASC`` (top of class first).
- Default-year resolution: pick the oldest year that has at least
  one non-``in_draft_org`` outcome. Newer save universes will
  shift this naturally as classes age.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import (
    DraftBucket,
    DraftClassResponse,
    DraftClassSummary,
    DraftPick,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()


# Outcome bucket order — most-impact first so MLB regulars top the
# page. Labels are hardcoded; if outcome semantics ever change, keep
# this in sync with the L3 builder's `_OUTCOME_*` constants.
_BUCKET_ORDER: list[tuple[str, str]] = [
    ("mlb_regular", "MLB Regulars"),
    ("mlb_callup", "MLB Callups"),
    ("in_draft_org", "Still Developing"),
    ("traded_away", "Traded Away"),
    ("released", "Released"),
    ("retired", "Retired"),
]


_AVAILABLE_YEARS_QUERY = """
SELECT DISTINCT draft_year FROM f_draft_class
WHERE draft_year IS NOT NULL
ORDER BY draft_year DESC
"""


_DEFAULT_YEAR_QUERY = """
SELECT MIN(draft_year)
FROM f_draft_class
WHERE outcome <> 'in_draft_org' AND draft_year IS NOT NULL
"""


_SUMMARY_QUERY = """
SELECT
    draft_year,
    COUNT(*)                                              AS total_picks,
    COUNT(*) FILTER (WHERE ever_made_mlb)                 AS ever_made_mlb,
    COUNT(*) FILTER (WHERE outcome = 'mlb_regular')       AS mlb_regular,
    COUNT(*) FILTER (WHERE outcome = 'mlb_callup')        AS mlb_callup,
    COUNT(*) FILTER (WHERE outcome = 'in_draft_org')      AS in_draft_org,
    COUNT(*) FILTER (WHERE outcome = 'traded_away')       AS traded_away,
    COUNT(*) FILTER (WHERE outcome = 'released')          AS released,
    COUNT(*) FILTER (WHERE outcome = 'retired')           AS retired
FROM f_draft_class
WHERE draft_year = ?
GROUP BY draft_year
"""


_CLASS_QUERY = """
SELECT
    player_id,
    first_name || ' ' || last_name AS display_name,
    position, bats, throws,
    draft_age, draft_round, draft_overall_pick,
    draft_team_name, current_team_name, current_level_id,
    outcome,
    ever_made_mlb, first_mlb_date,
    mlb_g, mlb_pa, mlb_hr, mlb_war_bat,
    mlb_g_pit, mlb_outs, mlb_w, mlb_s, mlb_war_pit,
    career_mlb_war
FROM f_draft_class
WHERE draft_year = ?
ORDER BY draft_overall_pick NULLS LAST
"""


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


def _row_to_pick(r: tuple) -> DraftPick:
    (player_id, display_name, position, bats, throws,
     draft_age, draft_round, draft_overall_pick,
     draft_team_name, current_team_name, current_level_id,
     outcome,
     ever_made_mlb, first_mlb_date,
     mlb_g, mlb_pa, mlb_hr, mlb_war_bat,
     mlb_g_pit, mlb_outs, mlb_w, mlb_s, mlb_war_pit,
     career_mlb_war) = r
    return DraftPick(
        player_id=int(player_id),
        display_name=display_name,
        position=int(position) if position is not None else 0,
        bats=int(bats) if bats is not None else None,
        throws=int(throws) if throws is not None else None,
        draft_age=int(draft_age) if draft_age is not None else None,
        draft_round=int(draft_round) if draft_round is not None else None,
        draft_overall_pick=(
            int(draft_overall_pick) if draft_overall_pick is not None else None
        ),
        draft_team_name=draft_team_name,
        current_team_name=current_team_name,
        current_level_id=(
            int(current_level_id) if current_level_id is not None else None
        ),
        outcome=outcome,  # type: ignore[arg-type]
        ever_made_mlb=bool(ever_made_mlb) if ever_made_mlb is not None else False,
        first_mlb_date=first_mlb_date if isinstance(first_mlb_date, date) else None,
        mlb_g=int(mlb_g) if mlb_g is not None else 0,
        mlb_pa=int(mlb_pa) if mlb_pa is not None else 0,
        mlb_hr=int(mlb_hr) if mlb_hr is not None else 0,
        mlb_war_bat=float(mlb_war_bat) if mlb_war_bat is not None else 0.0,
        mlb_g_pit=int(mlb_g_pit) if mlb_g_pit is not None else 0,
        mlb_outs=int(mlb_outs) if mlb_outs is not None else 0,
        mlb_w=int(mlb_w) if mlb_w is not None else 0,
        mlb_s=int(mlb_s) if mlb_s is not None else 0,
        mlb_war_pit=float(mlb_war_pit) if mlb_war_pit is not None else 0.0,
        career_mlb_war=float(career_mlb_war) if career_mlb_war is not None else 0.0,
    )


@router.get("/draft", response_model=DraftClassResponse)
def get_draft(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    year: Annotated[
        int | None,
        Query(description="Draft year. Defaults to oldest year with material outcome variation."),
    ] = None,
) -> DraftClassResponse:
    """Full draft class retrospective for one year, bucketed by outcome."""
    available_years = [
        int(r[0])
        for r in con.execute(_AVAILABLE_YEARS_QUERY).fetchall()
    ]
    if not available_years:
        raise HTTPException(
            status_code=404,
            detail="No draft data in the warehouse — run `diamond ingest` first.",
        )

    available_set = set(available_years)
    if year is not None and year in available_set:
        resolved_year = year
    else:
        # Default — oldest year with non-in_draft_org outcomes.
        default_row = con.execute(_DEFAULT_YEAR_QUERY).fetchone()
        if default_row and default_row[0] is not None:
            resolved_year = int(default_row[0])
        else:
            # Fresh save with no aged classes — pick the oldest year
            # available even if it's all in_draft_org.
            resolved_year = available_years[-1]

    # Summary
    summary_row = con.execute(_SUMMARY_QUERY, [resolved_year]).fetchone()
    if summary_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No picks recorded for draft year {resolved_year}.",
        )
    (s_year, total_picks, ever_made_mlb,
     mlb_regular, mlb_callup, in_draft_org,
     traded_away, released, retired) = summary_row
    summary = DraftClassSummary(
        year=int(s_year),
        total_picks=int(total_picks),
        ever_made_mlb=int(ever_made_mlb),
        mlb_regular=int(mlb_regular),
        mlb_callup=int(mlb_callup),
        in_draft_org=int(in_draft_org),
        traded_away=int(traded_away),
        released=int(released),
        retired=int(retired),
    )

    # Class rows, grouped by bucket.
    rows_raw = con.execute(_CLASS_QUERY, [resolved_year]).fetchall()
    by_bucket: dict[str, list[DraftPick]] = {}
    for r in rows_raw:
        pick = _row_to_pick(r)
        by_bucket.setdefault(pick.outcome, []).append(pick)

    buckets: list[DraftBucket] = []
    for outcome_key, label in _BUCKET_ORDER:
        rows = by_bucket.get(outcome_key, [])
        if not rows:
            continue  # skip empty buckets to keep the page tidy
        buckets.append(
            DraftBucket(
                outcome=outcome_key,  # type: ignore[arg-type]
                label=label,
                count=len(rows),
                rows=rows,
            )
        )

    return DraftClassResponse(
        year=resolved_year,
        available_years=available_years,
        summary=summary,
        buckets=buckets,
    )
