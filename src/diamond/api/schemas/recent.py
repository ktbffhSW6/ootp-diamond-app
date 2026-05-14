"""Rolling-window stat aggregates for the player page (Phase 4b Tier D).

Returns per-(player, window-size) aggregated batting + pitching lines
from the game-grain fact tables (`f_player_game_batting` /
`f_player_game_pitching`). Used by the "Last 7 / 15 / 30 days" toggle
on the player page Stats tab.

Window semantics
----------------

The window is **calendar-day** based, anchored to the player's most
recent game (NOT today's date — relevant for retired players + mid-
season views). E.g. ``window_days=30`` returns aggregate stats for
every game where ``date`` is within ``[last_game_date - 30 days,
last_game_date]``.

Pitching uses the same date-window semantics (NOT "last N starts").
Reasoning: a closer with 30 appearances in 30 days vs a starter with
6 starts in 30 days are both useful "recent form" windows. The
frontend can compute "last N starts" via filter on `gs=1` if needed.

Game-type filter
----------------

Defaults to regular-season only (``game_type = 0``). Spring training
(2) and playoffs (4) skew the math when included by default. Frontend
toggle for playoff slices is a Phase 5 backlog item.

Empty windows
-------------

A player with zero games in the requested window returns
``games_in_window=0`` and ``None`` for all rate stats. Frontend renders
"No games in window" placeholder.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlayerRecentBatting(BaseModel):
    """Aggregate batting line over the most recent N calendar days.

    Slash line and rate stats are computed from the aggregated counting
    stats — same arithmetic as the season-totals helpers in
    ``routes/players.py``.
    """

    model_config = ConfigDict(frozen=True)

    window_days: int                 # 7 / 15 / 30 (or whatever's queried)
    games_in_window: int
    first_date: str | None           # ISO date of oldest game in window
    last_date: str | None            # ISO date of newest game in window (= anchor)
    pa: int
    ab: int
    h: int
    d: int                           # doubles
    t: int                           # triples
    hr: int
    r: int
    rbi: int
    bb: int
    k: int
    hbp: int
    sb: int
    cs: int
    # Computed slash + counting rates. None when denominator is zero
    # (avoids division-by-zero garbage values).
    avg: float | None
    obp: float | None
    slg: float | None
    ops: float | None


class PlayerRecentPitching(BaseModel):
    """Aggregate pitching line over the most recent N calendar days.

    Outs is the source-of-truth counting stat; ``ip_display`` is the
    Bref-style display ``int.frac`` (e.g. ``172.1`` = 172⅓ innings).
    """

    model_config = ConfigDict(frozen=True)

    window_days: int
    games_in_window: int
    starts: int                      # count of GS=1 appearances
    first_date: str | None
    last_date: str | None
    outs: int
    ip_display: float
    bf: int
    h: int
    r: int
    er: int
    bb: int
    k: int
    hr_allowed: int
    # Rate stats. None when IP=0 (no innings pitched in window).
    era: float | None
    whip: float | None
    k_per_9: float | None
    bb_per_9: float | None


class PlayerRecentResponse(BaseModel):
    """All standard rolling windows in one response.

    Returns aggregate stat lines for three pre-computed window sizes
    (7, 15, 30 days) so the frontend can toggle between them without
    extra round-trips. Both ``bat`` and ``pit`` arrays contain
    one row per window, in the order ``[7, 15, 30]``.

    Either array can be empty if the player has no batting / pitching
    appearances in the warehouse at all (e.g. position players who
    never pitched).
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    bat: list[PlayerRecentBatting]
    pit: list[PlayerRecentPitching]
