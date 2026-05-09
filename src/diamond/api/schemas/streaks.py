"""Streaks Pydantic schemas — backs ``/history/streaks``.

Backed by the L3 fact ``f_player_streak``: top-50 holders per
(``streak_id`` × ``scope``) for 21 streak codes (hitting / scoreless
innings / multi-hit / on-base / saves / etc.). 2,100 rows total.

Picker hierarchy (2 axes):

- **Streak type** — the 21 codes from ``StreakId`` IntEnum. Display
  labels come from ``f_player_streak.streak_label`` directly (the
  L3 builder denormalizes them). Ordered by relevance — headline
  streaks (Hitting / Scoreless Innings / On-Base / Win) first,
  then per-skill streaks, then rare/edge codes.
- **Scope** — ``active`` (currently alive in the latest dump) vs
  ``all_time`` (every streak ever observed in the latest dump's
  ``players_streak.csv``, including ones that have ended).

Each streak carries ``has_ended`` (false → currently active),
``started`` date, ``ended`` date (nullable when active). The
distinction matters for the UI — active streaks render the start
date + a "Live" badge, ended streaks render a date range.

Per D17 streaks lives under ``/history``. Single endpoint
``GET /api/streaks?streak_id=&scope=&limit=`` returns one
leaderboard at a time.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


StreakScope = Literal["active", "all_time"]


class StreakCategoryRef(BaseModel):
    """Lightweight streak handle for the picker. ``available_scopes``
    lists which scopes have data for this streak type — every code
    has both in our build, but the field is present in case a future
    save loses one (e.g., zero active games-played streaks because
    the season just rolled over).
    """

    model_config = ConfigDict(frozen=True)

    streak_id: int  # StreakId enum value
    label: str
    available_scopes: list[StreakScope]


class StreakRow(BaseModel):
    """One streak-leaderboard row.

    ``rank`` mirrors ``rank_in_scope`` (no re-ranking needed; the
    L3 build already top-50'd per (streak_id, scope)).

    ``has_ended`` distinguishes active vs ended streaks. When
    ``scope='active'``, ``has_ended`` is always false; when
    ``scope='all_time'``, it can be either (active streaks
    naturally appear in both scopes — same player, same value).

    ``ended`` is the date string from the dump (e.g., ``"2028-7-29"``
    or ``"NULL"`` for active rows). The L3 builder leaves it as a
    string because the dump's date format isn't always parseable
    (single-digit months don't zero-pad). The UI renders it
    verbatim when present.

    ``team_abbr`` is the team at the start of the streak; nullable
    when the dump didn't carry team metadata for that game (pre-2026
    real-history streaks).
    """

    model_config = ConfigDict(frozen=True)

    rank: int
    player_id: int | None
    display_name: str
    value: int
    has_ended: bool
    started: date | None
    ended: str | None
    league_id: int | None
    team_abbr: str | None


class StreaksResponse(BaseModel):
    """One streak's leaderboard, top-N holders.

    ``available_streaks`` is the full picker list (all 21 streak_ids
    in the warehouse, with their labels). ``streak_id`` + ``scope``
    are the active selection.

    Like records / awards, the rendered ``rows`` is the source of
    truth for ordering — server already ordered by rank ASC.
    """

    model_config = ConfigDict(frozen=True)

    streak_id: int
    streak_label: str
    scope: StreakScope
    available_streaks: list[StreakCategoryRef]
    rows: list[StreakRow]
    total_in_scope: int
