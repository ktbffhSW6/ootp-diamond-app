"""Parks API routes (Slice 6, D26+D27)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from diamond.api.schemas.parks import Park, ParkDimensions, ParkFactors, ParksResponse
from diamond.api.warehouse import get_cursor

router = APIRouter()


@router.get("/parks", response_model=ParksResponse)
def list_parks(con=Depends(get_cursor)) -> ParksResponse:
    """Return all 240 parks from `lref_pt_ballparks` (modern catalog).

    Frontend (`StadiumSprayChart`) currently uses a hand-coded 30-park
    dataset in `web/lib/stadiums.ts`. This endpoint is the data layer
    that lets the frontend swap to OOTP-canonical 7-segment geometry
    + handedness-split park factors when ready (Slice 6 v2).
    """
    rows = con.execute(
        """
        SELECT
            teamIDBR, franchID, "team name", "park name",
            CAST(Capacity AS INTEGER) AS capacity, Type, Surface, path,
            CAST(LLd AS INTEGER) AS ll_d, CAST(LFd AS INTEGER) AS lf_d,
            CAST(LCd AS INTEGER) AS lcf_d, CAST(CFd AS INTEGER) AS cf_d,
            CAST(RCd AS INTEGER) AS rcf_d, CAST(RFd AS INTEGER) AS rf_d,
            CAST(RLd AS INTEGER) AS rl_d,
            CAST(LLh AS INTEGER) AS ll_h, CAST(LFh AS INTEGER) AS lf_h,
            CAST(LCh AS INTEGER) AS lcf_h, CAST(CFh AS INTEGER) AS cf_h,
            CAST(RCh AS INTEGER) AS rcf_h, CAST(RFh AS INTEGER) AS rf_h,
            CAST(RLh AS INTEGER) AS rl_h,
            TRY_CAST("BA Overall" AS DOUBLE) AS ba_overall,
            TRY_CAST("HR Overall" AS DOUBLE) AS hr_overall,
            TRY_CAST("BA LH" AS DOUBLE)      AS ba_lh,
            TRY_CAST("HR LH" AS DOUBLE)      AS hr_lh,
            TRY_CAST("BA RH" AS DOUBLE)      AS ba_rh,
            TRY_CAST("HR RH" AS DOUBLE)      AS hr_rh
        FROM lref_pt_ballparks
        WHERE "park name" IS NOT NULL
        ORDER BY teamIDBR, "park name"
        """
    ).fetchall()
    parks = [
        Park(
            team_id_br=r[0],
            franch_id=r[1],
            team_name=r[2],
            park_name=r[3],
            capacity=r[4],
            park_type=r[5],
            surface=r[6],
            path=r[7],
            dimensions=ParkDimensions(
                ll_d=r[8],   lf_d=r[9],   lcf_d=r[10], cf_d=r[11],
                rcf_d=r[12], rf_d=r[13],  rl_d=r[14],
                ll_h=r[15],  lf_h=r[16],  lcf_h=r[17], cf_h=r[18],
                rcf_h=r[19], rf_h=r[20],  rl_h=r[21],
            ),
            factors=ParkFactors(
                ba_overall=r[22], hr_overall=r[23],
                ba_lh=r[24], hr_lh=r[25],
                ba_rh=r[26], hr_rh=r[27],
            ),
        )
        for r in rows
    ]
    return ParksResponse(count=len(parks), parks=parks)
