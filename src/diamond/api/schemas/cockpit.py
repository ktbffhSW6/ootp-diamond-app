"""Cockpit dashboard Pydantic schemas — backs the new ``/`` landing.

Composes existing surfaces into a single GM-morning-coffee view:

- **Save header** — already on the landing today (kept on the page,
  not in this payload).
- **Standings strip** — user's MLB division. Just the rows; the
  picker / cross-league navigation lives on ``/league``.
- **Pressure summary** — top 3 promotion candidates + top 3 pressure
  cases at MLB level, the highest-stakes view.
- **Spotlight cards** — top N (default 6) MLB-level Sox players by
  current-year WAR, each with their full career WAR-by-year series
  for the inline sparkline. Auto-generated one-line insight on each
  ("Career year — wRC+ 198 vs prior peak 174.").
- **Recent movements** — last N (default 8) ledger rows for the
  current year.

Per Decision D17 the cockpit lives at ``/`` (Club tab landing).
This payload is the composition; per-section semantics mirror the
dedicated pages they came from. One round-trip — no client-side
state.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# Standings strip
# ─────────────────────────────────────────────────────────────────────────────


class CockpitStandingsRow(BaseModel):
    """One team line in the user's division standings.

    ``is_user_org`` flags the row for the audit team (Boston) so the
    UI highlights it without having to know the team_id.
    """

    model_config = ConfigDict(frozen=True)

    team_id: int
    abbr: str | None
    nickname: str | None
    w: int
    l: int
    pct: float
    gb: float
    streak: int
    is_user_org: bool


class CockpitStandingsBlock(BaseModel):
    """The user's division standings only — single block, no
    sub-league / cross-division clutter on the landing.

    ``division_name`` may be null for leagues without divisions; the
    UI hides the header in that case. ``snapshot_date`` is the
    resolved MAX(dump_date) within the cockpit's chosen year so the
    user knows which monthly cut they're seeing.
    """

    model_config = ConfigDict(frozen=True)

    division_name: str | None
    snapshot_date: date
    rows: list[CockpitStandingsRow]


# ─────────────────────────────────────────────────────────────────────────────
# Pressure summary
# ─────────────────────────────────────────────────────────────────────────────


CockpitPressureRole = Literal["batter", "pitcher"]


class CockpitPressureRow(BaseModel):
    """One pressure-summary row — slimmer than ``/api/pressure``'s
    ``PressurePlayer`` since the cockpit only needs name + headline
    metric + level for at-a-glance scanning.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    role: CockpitPressureRole
    level_name: str  # MLB / AAA / etc.
    metric: int  # OPS+ or ERA+
    sample: str  # "200 PA" or "45.2 IP" — pre-formatted by route
    team_abbr: str | None


class CockpitPressureSummary(BaseModel):
    """Top 3 promotion candidates + top 3 pressure cases at MLB level.

    The cockpit intentionally limits to MLB to keep the strip tight —
    the full per-level board lives on ``/pressure``. A user landing
    on the cockpit asks "what does my big-league roster need?";
    minor-league pressure is one click away.
    """

    model_config = ConfigDict(frozen=True)

    promotion: list[CockpitPressureRow]
    pressure: list[CockpitPressureRow]


# ─────────────────────────────────────────────────────────────────────────────
# Spotlight cards
# ─────────────────────────────────────────────────────────────────────────────


CockpitSpotlightRole = Literal["batter", "pitcher", "two-way"]


class CockpitSpotlightCard(BaseModel):
    """One marquee Sox player. The card combines a current-year
    headline metric, a career WAR sparkline, and a one-line auto-
    generated insight.

    ``career_war_by_year`` is a parallel-list pair of (year, war)
    aligned by index. Years with no advanced data render as nulls
    in the WAR list so the sparkline draws gaps cleanly.

    ``insight`` is server-generated NLG ("Career year — 9.3 WAR
    blows past prior 6.1 peak") and is null when no comparable can
    be computed (e.g., rookie season). The UI renders it as a small
    italic line under the name.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    position: int  # 1-9 = P-RF
    role: CockpitSpotlightRole
    team_abbr: str | None

    # Current-year headline
    headline_metric_label: str  # e.g. "OPS+" / "ERA+"
    headline_metric_value: int  # 198, 127, etc.
    sample: str  # "555 PA" / "172.1 IP"
    war_current: float

    # Career arc — for inline Sparkline component on the card
    career_years: list[int]
    career_war: list[float | None]

    insight: str | None


# ─────────────────────────────────────────────────────────────────────────────
# Recent movements feed
# ─────────────────────────────────────────────────────────────────────────────


class CockpitMovementRow(BaseModel):
    """Slimmed-down ledger row for the recent-moves strip."""

    model_config = ConfigDict(frozen=True)

    movement_id: int
    player_id: int
    display_name: str
    movement_type: str  # promotion | demotion | trade | ...
    direction: str  # internal | incoming | outgoing
    from_team_abbr: str | None
    to_team_abbr: str | None
    movement_date: date


# ─────────────────────────────────────────────────────────────────────────────
# Top-level response
# ─────────────────────────────────────────────────────────────────────────────


class CockpitResponse(BaseModel):
    """Whole dashboard payload — one round-trip composes everything.

    ``year`` is the current cockpit year (defaults to latest with
    data; ``available_years`` is omitted because the cockpit is
    intentionally fixed to "now" — historical snapshots live on
    ``/league`` / ``/pressure`` / ``/movements`` per their own pickers).
    """

    model_config = ConfigDict(frozen=True)

    year: int
    org_team_id: int
    standings: CockpitStandingsBlock | None
    pressure: CockpitPressureSummary
    spotlight: list[CockpitSpotlightCard]
    recent_movements: list[CockpitMovementRow]
