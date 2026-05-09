"""Compare Pydantic schemas — backs ``/explore/compare``.

The first live mode in the Explore sandbox: pick N players (≤4 in
v1), render side-by-side career stat blocks + an overlaid CareerArc.
Trout-vs-Cobb is the canonical demo; cross-era support comes free
because we already have D20's pre-save MLB league baselines feeding
career WAR for imported real-history players.

Response shape — slim by design. We don't echo the full
``PlayerResponse`` per player (which would balloon to ~50KB × N);
instead we surface just what side-by-side comparison actually
needs: bio header, career counters (slash + counting + IP-shaped
pitching), career WAR series for sparkline overlay, and the most
recent qualifying season's headline metric.

The frontend reuses Sparkline + heat-scale to keep the visual
language consistent with the rest of the app — no compare-specific
viz primitives.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ComparePlayer(BaseModel):
    """One player's compare card payload.

    All career counters are sums across stints. ``career_avg/obp/slg``
    are recomputed from totals (not averaged from per-season rates),
    which matches the canonical Bref career line.

    ``career_years`` + ``career_war`` are parallel arrays for the
    overlay sparkline — same shape as
    ``CockpitSpotlightCard.career_*`` so the frontend can reuse
    Sparkline directly. Years with no advanced data render as null
    in the WAR list (gap in the line).

    ``latest_year`` is the most recent season the player appeared
    in. ``latest_ops_plus`` / ``latest_era_plus`` are the headline
    rate metric for that year (when populated); the frontend picks
    one based on which is non-null.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    position_name: str
    bats_throws: str | None
    age: int | None
    current_team_abbr: str | None
    is_retired: bool
    is_hall_of_fame: bool

    # Career batting line
    career_g_bat: int
    career_pa: int
    career_ab: int
    career_h: int
    career_hr: int
    career_rbi: int
    career_sb: int
    career_avg: float | None
    career_obp: float | None
    career_slg: float | None

    # Career pitching line (when applicable)
    career_g_pit: int
    career_w: int
    career_l: int
    career_sv: int
    career_outs: int
    career_so: int
    career_era: float | None
    career_whip: float | None

    # Career WAR
    career_years: list[int]
    career_war: list[float | None]
    career_total_war: float

    # Most recent year's headline numbers (null when never advanced
    # data in this discipline)
    latest_year: int | None
    latest_ops_plus: int | None
    latest_era_plus: int | None
    latest_war: float | None


class CompareResponse(BaseModel):
    """Whole compare payload.

    ``players`` is in the same order the user passed IDs; missing
    IDs surface in ``not_found`` so the frontend can render an
    "X not in scope" hint without breaking the layout.
    """

    model_config = ConfigDict(frozen=True)

    players: list[ComparePlayer]
    not_found: list[int]
