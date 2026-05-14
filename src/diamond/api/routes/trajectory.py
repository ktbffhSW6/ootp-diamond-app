"""Per-dump career trajectory endpoint — backs sparkline UI surfaces.

Endpoint:
- ``GET /api/players/{id}/trajectory`` — career + per-season trajectory
  points from the Phase 4b Tier B history tables.

Implementation notes:

- Source tables: ``f_player_career_history`` + ``f_player_season_*_history``.
- The career arrays are the cumulative-to-each-dump roll-up for the
  player's WHOLE career. Spotlight sparklines render this.
- The per-season arrays are the in-season month-by-month progression
  of the player's latest season (highest year × highest level) — for
  showing "how's the season going" charts.
- Pre-Tier-B-defense: empty arrays if the history tables are missing.
- Rate stats (AVG/OBP/SLG/OPS/ERA/WHIP/K-9) compute server-side from
  the counting stats, mirroring the helpers in ``recent.py``.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from diamond.api.schemas import TrajectoryPoint, TrajectoryResponse
from diamond.api.warehouse import get_cursor

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Rate-stat helpers (mirror ``routes/recent.py``)
# ─────────────────────────────────────────────────────────────────────────────


def _slash(h, ab, bb, hbp, sf, d, t, hr):
    """Standard slash line. None on zero denominators."""
    avg = round(h / ab, 3) if ab > 0 else None
    obp_denom = ab + bb + hbp + sf
    obp = round((h + bb + hbp) / obp_denom, 3) if obp_denom > 0 else None
    tb = (h - d - t - hr) + 2 * d + 3 * t + 4 * hr
    slg = round(tb / ab, 3) if ab > 0 else None
    ops = round((obp or 0) + (slg or 0), 3) if obp is not None and slg is not None else None
    return avg, obp, slg, ops


def _outs_to_ip_display(outs: int) -> float:
    return outs // 3 + (outs % 3) * 0.1


def _rate_per_9(num, outs):
    return round(num * 27.0 / outs, 2) if outs > 0 else None


def _whip(bb, h, outs):
    return round((bb + h) * 3.0 / outs, 2) if outs > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# Existence + setup
# ─────────────────────────────────────────────────────────────────────────────


def _has_history_tables(cursor: duckdb.DuckDBPyConnection) -> bool:
    row = cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name IN ("
        "  'f_player_career_history', "
        "  'f_player_season_batting_history', "
        "  'f_player_season_pitching_history'"
        ")"
    ).fetchone()
    return row[0] >= 3


def _player_exists(cursor: duckdb.DuckDBPyConnection, player_id: int) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM players_current WHERE player_id = ? LIMIT 1",
        [player_id],
    ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────────────────────────
# Query templates
# ─────────────────────────────────────────────────────────────────────────────


# Career-history rollup. f_player_career_history doesn't carry SF/SH
# (those columns exist but we don't expose them); slash calc uses
# SF=0 approximation (~3pp OBP error in worst case for high-SF batters).
_CAREER_HISTORY_SQL = """
SELECT
    dump_date,
    bat_g, bat_pa, bat_ab, bat_h, bat_d, bat_t, bat_hr, bat_rbi,
    bat_bb, bat_k, bat_hbp, bat_sf,
    pit_g, pit_gs, pit_outs, pit_sv, pit_w, pit_l,
    pit_ha, pit_bb, pit_er, pit_k, pit_hra
FROM f_player_career_history
WHERE player_id = ?
ORDER BY dump_date
"""


_SEASON_BAT_HISTORY_SQL = """
SELECT
    dump_date,
    g, pa, ab, h, d, t, hr, rbi, bb, k, hbp, sf
FROM f_player_season_batting_history
WHERE player_id = ? AND year = ? AND level_id = ? AND split_id = 1
ORDER BY dump_date
"""


_SEASON_PIT_HISTORY_SQL = """
SELECT
    dump_date,
    g, gs, sv, outs, ha AS h, bb, er, k, hra
FROM f_player_season_pitching_history
WHERE player_id = ? AND year = ? AND level_id = ? AND split_id = 1
ORDER BY dump_date
"""


_LATEST_BAT_SEASON_SQL = """
SELECT year, level_id
FROM f_player_season_batting_history
WHERE player_id = ? AND split_id = 1
GROUP BY year, level_id
ORDER BY year DESC, SUM(pa) DESC
LIMIT 1
"""


_LATEST_PIT_SEASON_SQL = """
SELECT year, level_id
FROM f_player_season_pitching_history
WHERE player_id = ? AND split_id = 1
GROUP BY year, level_id
ORDER BY year DESC, SUM(outs) DESC
LIMIT 1
"""


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────


def _build_career_bat_point(row) -> TrajectoryPoint:
    (dump_date, bg, bpa, bab, bh, bd, bt, bhr, brbi, bbb, bk, bhbp, bsf,
     _pg, _pgs, _po, _psv, _pw, _pl, _pha, _pbb, _per, _pk, _phra) = row
    pa = bpa or 0
    ab = bab or 0
    h = bh or 0
    bb_ = bbb or 0
    hbp = bhbp or 0
    sf = bsf or 0
    d = bd or 0
    t = bt or 0
    hr = bhr or 0
    avg, obp, slg, ops = _slash(h, ab, bb_, hbp, sf, d, t, hr)
    return TrajectoryPoint(
        dump_date=dump_date.isoformat() if dump_date else "",
        pa=pa, ab=ab, h=h, hr=hr, rbi=(brbi or 0),
        bb=bb_, k=(bk or 0),
        avg=avg, obp=obp, slg=slg, ops=ops,
    )


def _build_career_pit_point(row) -> TrajectoryPoint:
    (dump_date, _bg, _bpa, _bab, _bh, _bd, _bt, _bhr, _brbi, _bbb, _bk, _bhbp, _bsf,
     pg, pgs, po, psv, _pw, _pl, pha, pbb, per_, pk, _phra) = row
    outs = po or 0
    bb_ = pbb or 0
    h = pha or 0
    er = per_ or 0
    k = pk or 0
    return TrajectoryPoint(
        dump_date=dump_date.isoformat() if dump_date else "",
        g=(pg or 0), gs=(pgs or 0), sv=(psv or 0),
        outs=outs,
        ip_display=_outs_to_ip_display(outs),
        era=_rate_per_9(er, outs),
        whip=_whip(bb_, h, outs),
        k_per_9=_rate_per_9(k, outs),
    )


def _build_season_bat_point(row) -> TrajectoryPoint:
    dump_date, g, pa, ab, h, d, t, hr, rbi, bb_, k, hbp, sf = row
    avg, obp, slg, ops = _slash(h or 0, ab or 0, bb_ or 0, hbp or 0, sf or 0,
                                 d or 0, t or 0, hr or 0)
    return TrajectoryPoint(
        dump_date=dump_date.isoformat() if dump_date else "",
        pa=pa or 0, ab=ab or 0, h=h or 0, hr=hr or 0, rbi=rbi or 0,
        bb=bb_ or 0, k=k or 0,
        avg=avg, obp=obp, slg=slg, ops=ops,
    )


def _build_season_pit_point(row) -> TrajectoryPoint:
    dump_date, g, gs, sv, outs, h, bb_, er, k, hra = row
    outs_i = outs or 0
    return TrajectoryPoint(
        dump_date=dump_date.isoformat() if dump_date else "",
        g=g or 0, gs=gs or 0, sv=sv or 0,
        outs=outs_i,
        ip_display=_outs_to_ip_display(outs_i),
        era=_rate_per_9(er or 0, outs_i),
        whip=_whip(bb_ or 0, h or 0, outs_i),
        k_per_9=_rate_per_9(k or 0, outs_i),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/players/{player_id}/trajectory",
    response_model=TrajectoryResponse,
)
def get_player_trajectory(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    player_id: int,
) -> TrajectoryResponse:
    """Per-dump career + latest-season trajectory points for one player.

    Phase 4b Tier B. Source = ``f_player_career_history`` +
    ``f_player_season_*_history``. Graceful degrade to empty arrays
    on warehouses predating the Tier B build.
    """
    if not _player_exists(cursor, player_id):
        raise HTTPException(
            status_code=404, detail=f"Player {player_id} not found"
        )

    if not _has_history_tables(cursor):
        return TrajectoryResponse(
            player_id=player_id,
            career_bat=[], career_pit=[],
            season_year=None, season_level_id=None,
            season_bat=[], season_pit=[],
        )

    # Career history — single query returns both bat + pit cols per dump.
    career_rows = cursor.execute(_CAREER_HISTORY_SQL, [player_id]).fetchall()
    career_bat = [_build_career_bat_point(r) for r in career_rows]
    career_pit = [_build_career_pit_point(r) for r in career_rows]

    # Filter to only points where the player ACTUALLY had stats that side
    # (e.g. a position player will have all-zero pit rows we should drop).
    career_bat = [p for p in career_bat if (p.pa or 0) > 0]
    career_pit = [p for p in career_pit if (p.outs or 0) > 0]

    # Latest season slice — pick the highest year with the largest
    # workload (so a pinch-hitting cup-of-coffee doesn't outrank a
    # full season at a lower level).
    season_year: int | None = None
    season_level_id: int | None = None
    season_bat: list[TrajectoryPoint] = []
    season_pit: list[TrajectoryPoint] = []

    latest_bat = cursor.execute(_LATEST_BAT_SEASON_SQL, [player_id]).fetchone()
    latest_pit = cursor.execute(_LATEST_PIT_SEASON_SQL, [player_id]).fetchone()

    # Use the most-recent year of either side; ties → whichever exists.
    candidates = []
    if latest_bat:
        candidates.append(("bat", latest_bat[0], latest_bat[1]))
    if latest_pit:
        candidates.append(("pit", latest_pit[0], latest_pit[1]))
    if candidates:
        candidates.sort(key=lambda c: c[1], reverse=True)
        _kind, season_year, season_level_id = candidates[0]

    if season_year is not None and season_level_id is not None:
        bat_rows = cursor.execute(
            _SEASON_BAT_HISTORY_SQL,
            [player_id, season_year, season_level_id],
        ).fetchall()
        season_bat = [_build_season_bat_point(r) for r in bat_rows]
        pit_rows = cursor.execute(
            _SEASON_PIT_HISTORY_SQL,
            [player_id, season_year, season_level_id],
        ).fetchall()
        season_pit = [_build_season_pit_point(r) for r in pit_rows]
        # Drop pitcher rows with no work
        season_pit = [p for p in season_pit if (p.outs or 0) > 0]

    return TrajectoryResponse(
        player_id=player_id,
        career_bat=career_bat,
        career_pit=career_pit,
        season_year=season_year,
        season_level_id=season_level_id,
        season_bat=season_bat,
        season_pit=season_pit,
    )
