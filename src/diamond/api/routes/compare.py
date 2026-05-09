"""Compare endpoint — backs ``/explore/compare``.

Endpoint:
- ``GET /api/compare?ids=1,2,3,4`` — up to 4 players' compare-card
  payloads in one round-trip. Order in the response mirrors order
  of IDs in the query string. Missing IDs surface in ``not_found``.

Implementation notes:

- Career counters come from ``f_player_career`` (the L2 fact already
  rolled up across stints). One round-trip per player; for v1's
  ≤4-player ceiling that's negligible.
- Career WAR series mirrors the cockpit spotlight + CareerArc
  approach: sum b_war + p_war per year across the player's
  ``f_player_season_advanced_*`` rows, parallel arrays of years +
  WAR for the overlay sparkline.
- Headline metrics are the player's most-recent-year MLB-level
  ops_plus + era_plus. Both can be null (player only ever played
  MiLB, advanced data missing for pre-save imported real-history
  before D20 fix, etc.).

Cap on N=4 is hardcoded — at 5+ the side-by-side card layout on a
1080-wide laptop wraps awkwardly; the comparison narrative also
gets diffuse. Larger cohort comparison is a different surface
(would live as "cohort scatter" on Explore later).
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import ComparePlayer, CompareResponse
from diamond.api.warehouse import get_cursor
from diamond.constants import POSITION_NAMES

router = APIRouter()


_MAX_COMPARE = 4


def _parse_ids(raw: str) -> list[int]:
    """Parse a comma-separated list of player_ids. Tolerant — drops
    anything that doesn't parse as int, dedupes preserving order, caps
    at _MAX_COMPARE. Empty list when nothing parses."""
    out: list[int] = []
    seen: set[int] = set()
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            pid = int(tok)
        except ValueError:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        if len(out) >= _MAX_COMPARE:
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Per-player fetch
# ─────────────────────────────────────────────────────────────────────────────


_BIO_SQL = """
SELECT
    pc.player_id,
    pc.first_name || ' ' || pc.last_name AS display_name,
    pc.position,
    pc.bats, pc.throws,
    pc.age,
    t.abbr AS current_team_abbr,
    pc.retired, pc.hall_of_fame
FROM players_current pc
LEFT JOIN teams t ON t.team_id = pc.team_id
WHERE pc.player_id = ?
"""


_CAREER_BAT_SQL = """
SELECT
    SUM(g) AS g, SUM(pa) AS pa, SUM(ab) AS ab,
    SUM(h) AS h, SUM(hr) AS hr, SUM(rbi) AS rbi, SUM(sb) AS sb,
    SUM(d) AS d, SUM(t) AS t, SUM(bb) AS bb, SUM(hp) AS hp, SUM(sf) AS sf
FROM f_player_season_batting
WHERE player_id = ? AND split_id = 1
"""


_CAREER_PIT_SQL = """
SELECT
    SUM(g) AS g, SUM(w) AS w, SUM(l) AS l, SUM(s) AS s,
    SUM(outs) AS outs, SUM(k) AS k, SUM(er) AS er,
    SUM(ha) AS ha, SUM(bb) AS bb
FROM f_player_season_pitching
WHERE player_id = ? AND split_id = 1
"""


_CAREER_WAR_SQL = """
SELECT year,
       COALESCE(SUM(b_war), 0) + COALESCE(SUM(p_war), 0) AS war_yr
FROM (
    SELECT year, b_war, NULL::DOUBLE AS p_war
    FROM f_player_season_advanced_batting
    WHERE player_id = ?
    UNION ALL
    SELECT year, NULL::DOUBLE AS b_war, p_war
    FROM f_player_season_advanced_pitching
    WHERE player_id = ?
)
GROUP BY year ORDER BY year
"""


_LATEST_HEADLINE_SQL = """
WITH latest_year AS (
    SELECT MAX(year) AS y FROM (
        SELECT year FROM f_player_season_advanced_batting
        WHERE player_id = ? AND level_id = 1
        UNION
        SELECT year FROM f_player_season_advanced_pitching
        WHERE player_id = ? AND level_id = 1
    )
)
SELECT
    (SELECT y FROM latest_year) AS year,
    (SELECT MAX(ops_plus) FROM f_player_season_advanced_batting
        WHERE player_id = ? AND year = (SELECT y FROM latest_year)
          AND level_id = 1) AS ops_plus,
    (SELECT MAX(era_plus) FROM f_player_season_advanced_pitching
        WHERE player_id = ? AND year = (SELECT y FROM latest_year)
          AND level_id = 1) AS era_plus,
    (SELECT GREATEST(
        COALESCE((SELECT SUM(b_war) FROM f_player_season_advanced_batting
                  WHERE player_id = ? AND year = (SELECT y FROM latest_year)), 0),
        COALESCE((SELECT SUM(p_war) FROM f_player_season_advanced_pitching
                  WHERE player_id = ? AND year = (SELECT y FROM latest_year)), 0)
     )) AS latest_war
"""


def _bats_throws_label(bats: int | None, throws: int | None) -> str | None:
    bat_map = {1: "R", 2: "L", 3: "S"}
    thw_map = {1: "R", 2: "L"}
    b = bat_map.get(bats) if bats is not None else None
    t = thw_map.get(throws) if throws is not None else None
    if b is None and t is None:
        return None
    return f"{b or '?'}/{t or '?'}"


def _slash_or_none(num: int, denom: int) -> float | None:
    if not denom:
        return None
    return round(num / denom, 4)


def _slg_or_none(h: int, d: int, t: int, hr: int, ab: int) -> float | None:
    if not ab:
        return None
    s = h - d - t - hr  # singles
    return round((s + 2 * d + 3 * t + 4 * hr) / ab, 4)


def _era_or_none(er: int, outs: int) -> float | None:
    if not outs:
        return None
    return round(9.0 * er / (outs / 3.0), 3)


def _whip_or_none(ha: int, bb: int, outs: int) -> float | None:
    if not outs:
        return None
    return round((ha + bb) / (outs / 3.0), 3)


def _fetch_one(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> ComparePlayer | None:
    bio = con.execute(_BIO_SQL, [player_id]).fetchone()
    if bio is None:
        return None
    (pid, display_name, position, bats, throws, age,
     current_team_abbr, retired, hof) = bio

    bat = con.execute(_CAREER_BAT_SQL, [player_id]).fetchone()
    bg, bpa, bab, bh, bhr, brbi, bsb, bd, bt, bbb, bhp, bsf = (
        [int(x or 0) for x in bat] if bat else [0] * 12
    )
    avg = _slash_or_none(bh, bab)
    obp_num = bh + bbb + bhp
    obp_den = bab + bbb + bhp + bsf
    obp = _slash_or_none(obp_num, obp_den)
    slg = _slg_or_none(bh, bd, bt, bhr, bab)

    pit = con.execute(_CAREER_PIT_SQL, [player_id]).fetchone()
    pg, pw, pl, ps, pouts, pk, per_, pha, pbb = (
        [int(x or 0) for x in pit] if pit else [0] * 9
    )
    era = _era_or_none(per_, pouts)
    whip = _whip_or_none(pha, pbb, pouts)

    war_rows = con.execute(_CAREER_WAR_SQL, [player_id, player_id]).fetchall()
    career_years = [int(r[0]) for r in war_rows]
    career_war = [
        round(float(r[1]), 1) if r[1] is not None else None for r in war_rows
    ]
    career_total_war = round(
        sum(w for w in career_war if w is not None), 1
    )

    headline = con.execute(
        _LATEST_HEADLINE_SQL,
        [player_id, player_id, player_id, player_id, player_id, player_id],
    ).fetchone()
    latest_year, ops_plus, era_plus, latest_war = headline if headline else (None, None, None, None)

    return ComparePlayer(
        player_id=int(pid),
        display_name=display_name,
        position_name=POSITION_NAMES.get(int(position) if position else 0, "—"),
        bats_throws=_bats_throws_label(
            int(bats) if bats is not None else None,
            int(throws) if throws is not None else None,
        ),
        age=int(age) if age is not None else None,
        current_team_abbr=current_team_abbr,
        is_retired=bool(retired) if retired is not None else False,
        is_hall_of_fame=bool(hof) if hof is not None else False,
        career_g_bat=bg,
        career_pa=bpa,
        career_ab=bab,
        career_h=bh,
        career_hr=bhr,
        career_rbi=brbi,
        career_sb=bsb,
        career_avg=avg,
        career_obp=obp,
        career_slg=slg,
        career_g_pit=pg,
        career_w=pw,
        career_l=pl,
        career_sv=ps,
        career_outs=pouts,
        career_so=pk,
        career_era=era,
        career_whip=whip,
        career_years=career_years,
        career_war=career_war,
        career_total_war=career_total_war,
        latest_year=int(latest_year) if latest_year is not None else None,
        latest_ops_plus=int(ops_plus) if ops_plus is not None else None,
        latest_era_plus=int(era_plus) if era_plus is not None else None,
        latest_war=round(float(latest_war), 1) if latest_war is not None else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/compare", response_model=CompareResponse)
def get_compare(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    ids: Annotated[
        str,
        Query(description="Comma-separated player_ids, up to 4."),
    ] = "",
) -> CompareResponse:
    """Side-by-side compare cards for ≤4 players."""
    parsed = _parse_ids(ids)
    if not parsed:
        return CompareResponse(players=[], not_found=[])

    out: list[ComparePlayer] = []
    not_found: list[int] = []
    for pid in parsed:
        card = _fetch_one(con, pid)
        if card is None:
            not_found.append(pid)
        else:
            out.append(card)
    return CompareResponse(players=out, not_found=not_found)
