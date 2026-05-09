"""Batted-balls events endpoint — backs the spray chart + EV-LA scatter.

Endpoint:
- ``GET /api/players/{id}/batted_balls?year=&level_id=`` — list of BIP
  events for one (player, year, level). Returns hit_xy / exit_velo /
  launch_angle / result for every ball-in-play.

Implementation notes:

- Filter is BIP-only (`bip_flag = 1`). Strikeouts / walks / HBP have
  no spray or EV-LA to plot, so they're excluded server-side.
- `year` defaults to the most recent year with BIP data for this
  player at the requested level (so a deep-link without year still
  resolves to something useful).
- Response cap is implicit: a single MLB season is ~500-700 BIP per
  player. No need to paginate.
- `hit_xy` is left raw; the frontend caps the 130-255 outliers when
  binning. We could pre-cap server-side but exposing the raw values
  lets the chart code show "the ones that fell off the field" if we
  ever care to (e.g., debugging the codebook).
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import BattedBallEvent, BattedBallsResponse
from diamond.api.warehouse import get_cursor

router = APIRouter()


_PLAYER_NAME_SQL = """
SELECT first_name || ' ' || last_name FROM players_current WHERE player_id = ?
"""


_LATEST_YEAR_SQL = """
SELECT MAX(year)
FROM f_pa_event
WHERE batter_id = ? AND level_id = ? AND bip_flag = 1
"""


_BATTED_BALLS_SQL = """
SELECT
    hit_xy,
    hit_loc,
    exit_velo,
    launch_angle,
    result
FROM f_pa_event
WHERE batter_id = ?
  AND year = ?
  AND level_id = ?
  AND bip_flag = 1
ORDER BY game_id, pa_in_game_seq
"""


@router.get(
    "/players/{player_id}/batted_balls",
    response_model=BattedBallsResponse,
)
def get_batted_balls(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    player_id: int,
    year: Annotated[int | None, Query()] = None,
    level_id: Annotated[int, Query(ge=1, le=8)] = 1,
) -> BattedBallsResponse:
    """One batter's BIP events for a single (year, level)."""
    name_row = cursor.execute(_PLAYER_NAME_SQL, [player_id]).fetchone()
    if name_row is None or not name_row[0]:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
    player_name = name_row[0]

    if year is None:
        latest = cursor.execute(_LATEST_YEAR_SQL, [player_id, level_id]).fetchone()
        if latest is None or latest[0] is None:
            # No BIP rows at this level for this player.
            return BattedBallsResponse(
                player_id=player_id,
                player_name=player_name,
                year=0,
                level_id=level_id,
                bip_count=0,
                rows=[],
            )
        year = int(latest[0])

    raw = cursor.execute(_BATTED_BALLS_SQL, [player_id, year, level_id]).fetchall()
    rows = [
        BattedBallEvent(
            hit_xy=int(r[0]) if r[0] is not None else None,
            hit_loc=int(r[1]) if r[1] is not None else None,
            exit_velo=float(r[2]) if r[2] is not None else None,
            launch_angle=int(r[3]) if r[3] is not None else None,
            result=int(r[4]),
        )
        for r in raw
    ]

    return BattedBallsResponse(
        player_id=player_id,
        player_name=player_name,
        year=year,
        level_id=level_id,
        bip_count=len(rows),
        rows=rows,
    )
