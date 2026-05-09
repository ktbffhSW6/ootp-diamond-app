"""Parks API schemas (Slice 6, D26+D27).

Surfaces OOTP's canonical ballpark catalog from `lref_pt_ballparks`
(240 modern parks: MLB + minors). Replaces the hand-coded
`web/lib/stadiums.ts` dataset over time — the API alone is shipped
in Slice 6 v1; the frontend `StadiumSprayChart` refactor remains in
backlog (touches the renderer's geometry model deeply).

Each park carries:
  - 7-segment outfield dimensions (LL / LF / LCF / CF / RCF / RF / RL)
    and corresponding wall heights — strictly more precise than the
    5-point geometry the current frontend uses.
  - LH / RH split park factors per stat (BA / 2B / 3B / HR), plus
    Overall composite values.
  - Capacity, type (open/dome/retractable), surface (grass/turf).

Source: OOTP install-folder `database/pt_ballparks.txt`, frozen at
first ingest per D27.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ParkDimensions(BaseModel):
    """7-segment outfield wall geometry."""

    model_config = ConfigDict(frozen=True)

    # Distances (ft from home plate)
    ll_d: int | None     # Left-line distance
    lf_d: int | None     # Left-field power-alley
    lcf_d: int | None    # Left-center
    cf_d: int | None     # Dead center
    rcf_d: int | None    # Right-center
    rf_d: int | None     # Right-field power-alley
    rl_d: int | None     # Right-line distance

    # Wall heights (ft) at the same 7 segments
    ll_h: int | None
    lf_h: int | None
    lcf_h: int | None
    cf_h: int | None
    rcf_h: int | None
    rf_h: int | None
    rl_h: int | None


class ParkFactors(BaseModel):
    """Park factors. Overall + LH/RH splits."""

    model_config = ConfigDict(frozen=True)

    ba_overall: float | None
    hr_overall: float | None
    ba_lh: float | None
    hr_lh: float | None
    ba_rh: float | None
    hr_rh: float | None


class Park(BaseModel):
    """One ballpark from `lref_pt_ballparks`."""

    model_config = ConfigDict(frozen=True)

    team_id_br: str | None        # BBref team abbreviation (e.g. 'BOS')
    franch_id: str | None
    team_name: str | None
    park_name: str
    capacity: int | None
    park_type: str | None         # 'o' open / 'd' dome / 'r' retractable / etc.
    surface: str | None           # 'g' grass / 't' turf
    path: str | None              # Asset filename hint (e.g. 'fenway_park')
    dimensions: ParkDimensions
    factors: ParkFactors


class ParksResponse(BaseModel):
    """List of all parks in the OOTP install-folder catalog."""

    model_config = ConfigDict(frozen=True)

    count: int
    parks: list[Park]
