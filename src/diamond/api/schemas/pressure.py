"""Pressure-board Pydantic schemas — backs ``/pressure``.

The "who *should* move" view, companion to the movement ledger
(which shows who DID move). For each level in the org tree, surface
two cohorts:

- **Promotion candidates** — players mashing at this level relative
  to the level baseline (OPS+ / ERA+ well above 100). The "ready
  for the next call-up" cohort.
- **Pressure cases** — players underperforming at this level
  (OPS+ / ERA+ well below 100). The "send-down or replace"
  cohort.

Cross-level reading: a 130 OPS+ at AAA next to a 75 OPS+ at MLB
is a clear "swap them" signal. The page renders each level's
two columns side-by-side so the eye can pattern-match across
levels. v1 is org-scoped (Sox + affiliates); a future v2 would
add per-team filtering / per-position pivots.

Picker:
- **Year** — default latest year with data. Year-switching is a
  navigation; whole payload re-fetches.

Metrics:
- **Batters** — OPS+ as the headline (park-aware, league-relative,
  100 = average). Sample threshold: ``pa >= 50``.
- **Pitchers** — ERA+ as the headline (park-aware via 80%-leverage
  factor, league-relative). Sample threshold: ``outs >= 60`` (20 IP).

Both metrics carry the same "100 = average" semantic so the
``delta`` field (metric - 100) is comparable across roles.
b_WAR / p_WAR are surfaced alongside as the value summary
(rate-stat performance plus volume signal).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


PressureRole = Literal["batter", "pitcher"]


class PressurePlayer(BaseModel):
    """One player-row on a pressure-board card.

    ``role`` distinguishes batters vs pitchers (their metric column
    + sample-volume column are different). Batter rows surface
    ``ops_plus`` + ``pa``; pitcher rows surface ``era_plus`` + ``ip``.
    The frontend picks the right column based on ``role``.

    ``team_abbr`` is the team where the player accumulated the
    most volume at this level — matches the dominant-team rollup
    in ``f_player_season_advanced_*``.

    ``war`` is OOTP's directly-supplied combined WAR (b_war for
    batters, p_war for pitchers). Useful as a value sanity-check
    alongside the rate stat.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    role: PressureRole
    pa: int | None  # batter sample (PA); null for pitcher rows
    ip: float | None  # pitcher sample (decimal IP); null for batter rows
    metric: int  # OPS+ for batters, ERA+ for pitchers (100 = avg)
    delta: int  # metric - 100 (positive = above avg)
    war: float
    team_abbr: str | None
    position: int | None  # batter primary position (1-9); null for pitchers


class PressureLevelGroup(BaseModel):
    """One level's pressure-board card.

    ``promotion_candidates`` is sorted by ``metric DESC`` (best
    performers first). ``pressure_cases`` is sorted by ``metric
    ASC`` (worst first). Each is capped to a small N (configurable
    via the route's ``limit``; default 6) so the per-level card
    stays scannable.

    ``level_name`` is the display label (MLB / AAA / AA / A+ / A /
    Rk / DSL). ``level_id`` mirrors OOTP's level numeric.
    """

    model_config = ConfigDict(frozen=True)

    level_id: int
    level_name: str
    qualifying_count: int  # total org players at this level meeting the sample bar
    promotion_candidates: list[PressurePlayer]
    pressure_cases: list[PressurePlayer]


class PressureResponse(BaseModel):
    """Whole payload — every level with org rows above the sample bar.

    Levels with no qualifying players drop out (an A-ball complex
    with three pre-call-up rookies hits zero qualifiers and is
    skipped). ``available_years`` lets the year picker render
    without a second round-trip.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    available_years: list[int]
    org_team_id: int
    levels: list[PressureLevelGroup]
