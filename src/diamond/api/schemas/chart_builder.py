"""Pydantic schemas for the Chart Builder (D23 → /explore reset).

The Chart Builder is intentionally minimal in v1: pick one or two stats
from the existing leaderboards catalog + optional color stat, plus
year/level/qualifier filters, and the API returns a row-per-player
dataset the frontend renders as a histogram (1 stat) or scatter (2
stats). It reuses the LEADERBOARD_STATS catalog so we don't maintain
two parallel "what stats are exposable" lists.

Cross-table joins (e.g., wOBA on the X axis from advanced batting +
HR on the Y axis from counting batting) live in v1 — every supported
stat keys on (player_id, year, league_id, level_id) so the SQL can
LEFT JOIN multiple source tables into one wide row.
"""

from __future__ import annotations

from pydantic import BaseModel


class ChartBuilderPoint(BaseModel):
    """One row in a chart-builder result.

    `x` is always populated; `y` is null in 1-stat (histogram) mode;
    `color` is null when the user didn't pick a color encoding.
    `qualifier_value` is the gating volume metric (PA / IP-outs /
    BIP) — surfaced as a tooltip / size encoding option.
    """

    player_id: int
    player_name: str
    team_abbr: str | None
    year: int | None
    x: float | None
    y: float | None
    color: float | None
    qualifier_value: int


class ChartBuilderResponse(BaseModel):
    """Echoed picker state + the data rows.

    `mode` is "scatter" (X + Y both set) or "histogram" (Y is null).
    The frontend uses this to pick the Plot mark type without re-
    deriving from the URL params.
    """

    mode: str
    x_stat: str
    y_stat: str | None
    color_stat: str | None
    year: int | None
    level_id: int | None
    league_id: int | None
    qualifier_min: int
    points: list[ChartBuilderPoint]
