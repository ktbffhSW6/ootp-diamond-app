"""Schemas for the batted-balls (spray + EV-LA) endpoint.

Backs `/api/players/{id}/batted_balls?year=&level_id=` for the
spray-chart and EV-LA-scatter views under /explore. Per-PA event
data is heavy — we cap each request to a single (player, year, level)
to keep payloads under ~1 MB.
"""

from __future__ import annotations

from pydantic import BaseModel


class BattedBallEvent(BaseModel):
    """One ball-in-play event for a single batter.

    `hit_xy` is OOTP's batter-relative spray code (0-130 covers the
    field arc; 0 = pull-side foul line, 65 = center, 130 = oppo
    foul line; 130-255 are mostly out-of-play codes that we cap on
    the frontend). `result` is the AtBatResult enum (4=GO, 5=FO,
    6=1B, 7=2B, 8=3B, 9=HR — only BIP outcomes shown here).

    `exit_velo` is in mph (OOTP scale runs ~5 mph below real Statcast).
    `launch_angle` is in degrees (-90 to +90 — negative = chopper,
    positive = fly ball). Both can be null for events where the
    Statcast simulator didn't fire (very rare in modern saves).
    """

    hit_xy: int | None
    hit_loc: int | None
    exit_velo: float | None
    launch_angle: int | None
    result: int


class BattedBallsResponse(BaseModel):
    """Single (player, year, level) batted-ball event list.

    `rows` only includes BIP events (`bip_flag = 1`) — strikeouts,
    walks, HBP are filtered server-side since they have no spray /
    EV / LA to plot. `bip_count` is for sanity-checking the cohort
    threshold (Statcast cohort tables use BIP ≥ 30 minimum).
    """

    player_id: int
    player_name: str
    year: int
    level_id: int
    bip_count: int
    rows: list[BattedBallEvent]
