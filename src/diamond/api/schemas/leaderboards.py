"""Pydantic schemas for the custom-leaderboards endpoint.

Backs `/api/leaderboards?stat=&year=&league_id=&level_id=&pa_min=&limit=&order=`
under `/explore/leaderboards`. The endpoint produces a single ranked
list — the frontend can re-sort / filter the rows client-side via
TanStack Table without re-querying.
"""

from __future__ import annotations

from pydantic import BaseModel


class LeaderboardStatSpec(BaseModel):
    """Description of the requested stat — echoed in the response.

    `discipline` is "batting" / "pitching" / "statcast_b" / "statcast_p"
    so the frontend can render appropriate column headers (PA vs IP vs
    BIP qualifier). `direction` is "desc" (higher is better — HR, OPS+,
    bWAR) or "asc" (lower is better — ERA, FIP, SIERA).
    """

    id: str
    label: str
    discipline: str
    direction: str
    decimals: int


class LeaderboardRow(BaseModel):
    """One row in the leaderboard.

    `value` is the headline stat (formatted to `stat.decimals` on the
    frontend). `qualifier_value` is the PA / outs / BIP threshold the
    row passed (rendered as a secondary column for context). `team_abbr`
    is the dominant-team abbreviation at this level — null for players
    whose dominant team isn't in the active save's `teams` reference
    table (e.g., defunct historical franchises pre-2026).
    """

    rank: int
    player_id: int
    player_name: str
    team_id: int | None
    team_abbr: str | None
    league_id: int | None
    level_id: int | None
    year: int | None
    value: float | None
    qualifier_value: int


class LeaderboardOption(BaseModel):
    """An entry in the stat picker — one of the supported leaderboard stats.

    The frontend uses this to build a grouped dropdown ("Batting / Pitching
    / Statcast"). `qualifier_label` ("PA" / "IP" / "BIP") tells the picker
    UI what the default minimum gates against.
    """

    id: str
    label: str
    discipline: str
    direction: str
    decimals: int
    default_min: int
    qualifier_label: str


class LeaderboardOptionsResponse(BaseModel):
    """All supported leaderboard stats — used to build the picker."""

    options: list[LeaderboardOption]


class LeaderboardResponse(BaseModel):
    """A single leaderboard request's payload.

    Echoes the resolved stat spec + filters so the frontend doesn't
    have to re-derive labels / direction from the URL alone. `rows`
    is already pre-sorted by the requested direction.
    """

    stat: LeaderboardStatSpec
    year: int | None
    level_id: int | None
    league_id: int | None
    pa_min: int
    qualifier_label: str
    rows: list[LeaderboardRow]
