"""Save-metadata endpoint — backs the landing page.

Endpoint:
- ``GET /api/save`` — active save identity, ingest health, scope counts.

One-shot read; everything is cheap aggregates over admin tables. Total
latency is dominated by the DuckDB cursor handoff (~10ms locally).
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends

from diamond.api.schemas import SaveResponse
from diamond.api.warehouse import get_active_save, get_cursor

router = APIRouter()


@router.get("/save", response_model=SaveResponse)
def get_save(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> SaveResponse:
    """Return the active save's identity + warehouse health.

    Reads:
    - ``SaveConfig`` for save-folder name and audit_team_id
    - ``teams`` for the org's headline display fields
    - ``_diamond_ingests`` for dump count + latest dump
    - ``f_player_season_batting`` for the year range observed in stats
    - ``_scoped_players`` / ``_scoped_teams`` for scope counts
    """
    save = get_active_save()

    # Org identity
    org_meta = con.execute(
        "SELECT abbr, nickname FROM teams WHERE team_id = ?",
        [save.audit_team_id],
    ).fetchone()
    org_abbr, org_nickname = (org_meta or (None, None))

    # Ingest health — count of successful ingests + latest dump.
    # Defensive: the warehouse might exist with zero successful ingests
    # if the only attempt failed mid-build.
    ingest_row = con.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'success')   AS dump_count,
            MAX(dump_date) FILTER (WHERE status = 'success') AS latest_date,
            arg_max(dump_name, dump_date)
                FILTER (WHERE status = 'success')        AS latest_name
        FROM _diamond_ingests
        """,
    ).fetchone()
    dump_count = int(ingest_row[0] or 0)
    latest_dump_date = ingest_row[1]
    latest_dump_name = ingest_row[2]
    latest_season = (
        latest_dump_date.year if latest_dump_date is not None else None
    )

    # Year range from the canonical season-batting fact table. This
    # spans pre-save real history (often back to 1871) plus all in-save
    # seasons. The advanced fact table only covers in-save years
    # (league-history coverage starts 2026 per CLAUDE.md gotchas).
    year_range = con.execute(
        "SELECT MIN(year), MAX(year) FROM f_player_season_batting"
    ).fetchone()
    earliest_season = (
        int(year_range[0]) if year_range and year_range[0] is not None
        else None
    )

    # Scope counts. Cheap COUNT(*) on per-save scope views.
    scoped_player_count = int(con.execute(
        "SELECT COUNT(*) FROM _scoped_players"
    ).fetchone()[0])
    scoped_team_count = int(con.execute(
        "SELECT COUNT(*) FROM _scoped_teams"
    ).fetchone()[0])

    return SaveResponse(
        save_name=save.save_name,
        org_team_id=save.audit_team_id,
        org_team_abbr=org_abbr,
        org_team_nickname=org_nickname,
        dump_count=dump_count,
        latest_dump_date=latest_dump_date,
        latest_dump_name=latest_dump_name,
        latest_season=latest_season,
        earliest_season=earliest_season,
        scoped_player_count=scoped_player_count,
        scoped_team_count=scoped_team_count,
    )
