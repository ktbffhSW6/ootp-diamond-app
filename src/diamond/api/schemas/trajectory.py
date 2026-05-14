"""Per-dump career trajectory schemas for the sparkline surface.

Backs ``GET /api/players/{id}/trajectory`` — returns per-dump-date
counting + derived stats so the frontend can render real sparklines
(replacing the prior season-only-aggregated approximation on cockpit
spotlight cards).

Sourced from the L2 history tables shipped in Phase 4b Tier B
(``f_player_career_history`` + ``f_player_season_*_history``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TrajectoryPoint(BaseModel):
    """One sample of a per-(player, year?, level?) timeline.

    `dump_date` is the canonical x-axis (ISO date string). Counting
    stats are pre-summed; rate stats (avg/era/etc.) compute on the
    backend so the frontend doesn't have to know the formulas.

    Any stat field can be None when the denominator is zero or the
    player has no data for that dump.
    """

    model_config = ConfigDict(frozen=True)

    dump_date: str                # ISO date
    # Batting counts (None for pitcher-only career-history rows)
    pa: int | None = None
    ab: int | None = None
    h: int | None = None
    hr: int | None = None
    rbi: int | None = None
    bb: int | None = None
    k: int | None = None
    avg: float | None = None
    obp: float | None = None
    slg: float | None = None
    ops: float | None = None
    # Pitching counts (None for batter-only career-history rows)
    g: int | None = None
    gs: int | None = None
    sv: int | None = None
    outs: int | None = None
    ip_display: float | None = None
    era: float | None = None
    whip: float | None = None
    k_per_9: float | None = None


class TrajectoryResponse(BaseModel):
    """Career + per-season trajectories for one player.

    `career` is the cumulative-to-each-dump roll-up — what you'd want
    on a spotlight card's "career arc" sparkline.

    `per_season[year]` is the in-season month-by-month trajectory for
    a single season (year+level fixed). Use the latest year for the
    most-relevant view.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    career_bat: list[TrajectoryPoint]   # batting career roll-up over time
    career_pit: list[TrajectoryPoint]   # pitching career roll-up over time
    # Optional per-season slice (latest year only — keeps payload small).
    # year + level_id echoed back so frontend can label the axis.
    season_year: int | None
    season_level_id: int | None
    season_bat: list[TrajectoryPoint]
    season_pit: list[TrajectoryPoint]
