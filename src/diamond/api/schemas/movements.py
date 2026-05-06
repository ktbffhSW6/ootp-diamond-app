"""Movement-ledger Pydantic schemas — backs the GM-sidekick page.

The page answers two questions for the user's org (audit_team_id):

1. **Did the moves we made stick?** For every promotion/demotion in
   the season, show before/after performance and a verdict glyph
   (working / reconsider / struggling / too_small).
2. **Which moves were marginal?** The verdict thresholds surface the
   ambiguous cases — players who are still scuffling at the new level
   or mashing the lower level after a send-down.

Grain notes:
- One row per `movement_id` (one row per actual transition recorded
  in `player_movements`). Multi-stop moves on the same day get one
  row each.
- Before/after stats are season-totals at each level (from
  `f_player_season_advanced_*`). Per-stint splits are deferred —
  if a player has bounced multiple times in one season the stats
  conflate stints, but the move's chronology is still readable from
  `dump_date_observed`. Documented in v1; refine when we have evidence
  it matters.
- v1 covers ``promotion`` + ``demotion`` only. Trade pickups and FA
  signings have a different evaluation question (no
  before-stats-at-our-org) and ship in a follow-up slice.

Per D15: every numeric field maps to a `STATS[id]` in the dictionary
(e.g. ops_plus, wrc_plus, era_plus, fip, war).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# Enumerated string types (mirrored as TS string-literal unions)
# ─────────────────────────────────────────────────────────────────────────────

MovementType = Literal[
    "promotion", "demotion", "trade", "signed", "waiver_or_other", "released",
]
"""Subset of ``player_movements.movement_type`` we surface.

Categorized into three evaluation flavors on the page:

- **Internal moves** — ``promotion`` / ``demotion``. Both teams in the
  user's org; verdict reads off post-move performance at the new
  level vs. league average.
- **Acquisitions** — ``trade`` / ``signed`` / ``waiver_or_other`` with
  ``to_team`` in the user's org. Same verdict semantics as a promotion.
- **Departures** — ``released`` plus ``trade`` / ``waiver_or_other``
  with ``from_team`` in the user's org. Verdict semantics **invert**:
  a player thriving elsewhere after we let them go is *bad news* for
  the GM (we made the wrong call), so the rationale text is reframed
  from the move's perspective. The ``MovementDirection`` discriminant
  on each row tells the frontend which bucket a given row belongs in,
  since ``trade`` / ``waiver_or_other`` can fire in either direction.

Excluded: ``drafted`` / ``first_appearance`` / ``retired`` /
``unretired`` / ``intra_org_lateral`` — not evaluative for this page.
"""

MovementDirection = Literal["internal", "incoming", "outgoing"]
"""Bucket for a move from the GM's perspective.

- ``internal``  — both teams in the user's org (promotion/demotion).
- ``incoming``  — to_team in user's org, from_team outside (acquisition).
- ``outgoing``  — from_team in user's org, to_team outside or absent
  (departure: trade-away, waiver-out, released).

Movement type alone isn't a discriminant since ``trade`` /
``waiver_or_other`` can fire either way; the route resolves direction
when it builds the row.
"""

MovementVerdict = Literal["working", "reconsider", "struggling", "too_small"]
"""Verdict glyph shown next to each row.

- ``working``     — post-move performance vindicates the move.
- ``reconsider``  — middle zone or "demotion-but-mashing" — should the GM revisit?
- ``struggling``  — post-move performance contradicts the move.
- ``too_small``   — insufficient sample at the new level (< 30 PA / < 10 IP).
"""

MovementRole = Literal["batter", "pitcher"]
"""Which side's stats drive the verdict. Derived from `players.position`
(1 = pitcher; everything else = batter). Two-way players are evaluated
on their primary position for v1 — refining requires a per-side stint
table that doesn't exist yet."""


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────────────────────


class MovementTeamRef(BaseModel):
    """The from-team or to-team side of a move. Slimmer than the player
    page's ``TeamRef`` since we don't carry the league_abbr — the
    headline display is "MLB → AAA Worcester" so we need level + nickname,
    not league. Kept distinct so the contract for movements is self-contained.
    """

    model_config = ConfigDict(frozen=True)

    team_id: int
    abbr: str | None
    nickname: str | None
    level_id: int | None
    level_name: str | None


class MovementBattingStats(BaseModel):
    """Headline batting line shown in the before / after columns.

    ``ops_plus`` is the verdict driver (already park-adjusted, league-
    relative, scale 100 = average). ``wrc_plus`` is shown alongside
    for the wOBA-leaning reader; both come from the same L3 fact row.
    ``pa`` is the sample size — also drives the ``too_small`` verdict
    when below 30 at the new level.
    """

    model_config = ConfigDict(frozen=True)

    pa: int
    ops_plus: int | None
    wrc_plus: int | None
    woba: float | None
    o_war: float | None


class MovementPitchingStats(BaseModel):
    """Headline pitching line. Mirrors the batting model but for
    pitchers. ``era_plus`` is the verdict driver (same 100=avg
    convention). ``fip`` is included for a peripheral cross-check;
    ``ip_display`` uses the OOTP convention (FLOOR(outs/3) + (outs%3)*0.1)
    rather than decimal. ``outs`` is the raw sample size used in the
    too_small check (< 30 outs = < 10 IP)."""

    model_config = ConfigDict(frozen=True)

    outs: int
    ip_display: float | None
    era_plus: int | None
    fip: float | None
    pit_war: float | None


# ─────────────────────────────────────────────────────────────────────────────
# Top-level row + response
# ─────────────────────────────────────────────────────────────────────────────


class MovementRow(BaseModel):
    """One movement event with before/after stats and a verdict."""

    model_config = ConfigDict(frozen=True)

    movement_id: int
    player_id: int
    player_name: str
    primary_position: str        # "3B", "P", "SS", ...
    role: MovementRole
    movement_type: MovementType
    direction: MovementDirection
    dump_date_observed: date

    from_team: MovementTeamRef
    to_team: MovementTeamRef

    # Both batter and pitcher stats are returned (one set will be empty
    # for most players). The frontend reads ``role`` to pick which side
    # to render. Two-way players get both populated and can be flagged
    # explicitly in a future slice.
    before_batting: MovementBattingStats | None
    after_batting: MovementBattingStats | None
    before_pitching: MovementPitchingStats | None
    after_pitching: MovementPitchingStats | None

    verdict: MovementVerdict
    verdict_note: str            # Short human-readable rationale


class MovementsResponse(BaseModel):
    """Whole payload for the movements page.

    ``available_seasons`` lets the page render a year picker without a
    second round-trip; ``org_team_*`` lets the header show the user's
    team. ``rows`` is sorted DESC by date — most recent moves first.
    """

    model_config = ConfigDict(frozen=True)

    season: int
    available_seasons: list[int]
    org_team_id: int
    org_team_abbr: str | None
    org_team_nickname: str | None
    rows: list[MovementRow]
