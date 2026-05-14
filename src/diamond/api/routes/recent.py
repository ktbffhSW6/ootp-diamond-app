"""Rolling-window stats endpoint — backs the "Last 7 / 15 / 30 days"
toggle on the player page Stats tab (Phase 4b Tier D, D40).

Endpoint:
- ``GET /api/players/{id}/recent?windows=7,15,30`` — aggregated batting
  + pitching stat lines over each requested window. Default windows
  are ``7,15,30``.

Implementation notes:

- Source tables: ``f_player_game_batting`` + ``f_player_game_pitching``
  (Phase 4b Tier A, built 2026-05-14). Both filtered to
  ``game_type = 0`` (regular season).
- Window anchor: the player's most recent game date in the warehouse.
  NOT today's date — works for retired players + mid-season views.
- Each window returns ``games_in_window=0`` + all-null rate stats if
  the player has no games in range (rendered as "No games" on the
  frontend).
- One round-trip returns all requested windows. Default 7 / 15 / 30
  yields a tiny payload (3 batting rows + 3 pitching rows) so we
  don't bother caching client-side.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import (
    PlayerRecentBatting,
    PlayerRecentPitching,
    PlayerRecentResponse,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — slash + rate stat computation (mirrors players.py)
# ─────────────────────────────────────────────────────────────────────────────


def _slash(h: int, ab: int, bb: int, hbp: int, sf: int,
           d: int, t: int, hr: int) -> tuple[float | None, float | None, float | None, float | None]:
    """Standard slash line. None on zero denominators."""
    avg = round(h / ab, 3) if ab > 0 else None
    obp_denom = ab + bb + hbp + sf
    obp = round((h + bb + hbp) / obp_denom, 3) if obp_denom > 0 else None
    tb = (h - d - t - hr) + 2 * d + 3 * t + 4 * hr
    slg = round(tb / ab, 3) if ab > 0 else None
    ops = round((obp or 0) + (slg or 0), 3) if obp is not None and slg is not None else None
    return avg, obp, slg, ops


def _outs_to_ip_display(outs: int) -> float:
    """Bref-style int.frac IP display (517 outs → 172.1)."""
    return outs // 3 + (outs % 3) * 0.1


def _rate_per_9(num: int, outs: int) -> float | None:
    """Per-9-innings rate (ERA / WHIP / K-9 / BB-9 use this shape)."""
    if outs <= 0:
        return None
    return round(num * 27.0 / outs, 2)


def _whip(bb: int, h: int, outs: int) -> float | None:
    if outs <= 0:
        return None
    return round((bb + h) * 3.0 / outs, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Query templates
# ─────────────────────────────────────────────────────────────────────────────


_BATTING_WINDOW_SQL = """
WITH latest AS (
    SELECT MAX(date) AS d
    FROM f_player_game_batting
    WHERE player_id = ? AND game_type = 0
),
windowed AS (
    SELECT g.*
    FROM f_player_game_batting g, latest
    WHERE g.player_id = ?
      AND g.game_type = 0
      AND g.date BETWEEN latest.d - INTERVAL (?) DAY AND latest.d
)
SELECT
    COUNT(*)             AS games,
    COALESCE(SUM(pa), 0) AS pa,
    COALESCE(SUM(ab), 0) AS ab,
    COALESCE(SUM(h), 0)  AS h,
    COALESCE(SUM(d), 0)  AS d,
    COALESCE(SUM(t), 0)  AS t,
    COALESCE(SUM(hr), 0) AS hr,
    COALESCE(SUM(r), 0)  AS r,
    COALESCE(SUM(rbi), 0) AS rbi,
    COALESCE(SUM(bb), 0) AS bb,
    COALESCE(SUM(k), 0)  AS k,
    COALESCE(SUM(hbp), 0) AS hbp,
    COALESCE(SUM(sb), 0) AS sb,
    COALESCE(SUM(cs), 0) AS cs,
    MIN(date)            AS first_date,
    MAX(date)            AS last_date
FROM windowed
"""


_PITCHING_WINDOW_SQL = """
WITH latest AS (
    SELECT MAX(date) AS d
    FROM f_player_game_pitching
    WHERE player_id = ? AND game_type = 0
),
windowed AS (
    SELECT g.*
    FROM f_player_game_pitching g, latest
    WHERE g.player_id = ?
      AND g.game_type = 0
      AND g.date BETWEEN latest.d - INTERVAL (?) DAY AND latest.d
)
SELECT
    COUNT(*)              AS games,
    COALESCE(SUM(gs), 0)  AS starts,
    COALESCE(SUM(outs), 0) AS outs,
    COALESCE(SUM(bf), 0)  AS bf,
    COALESCE(SUM(h), 0)   AS h,
    COALESCE(SUM(r), 0)   AS r,
    COALESCE(SUM(er), 0)  AS er,
    COALESCE(SUM(bb), 0)  AS bb,
    COALESCE(SUM(k), 0)   AS k,
    COALESCE(SUM(hr_allowed), 0) AS hr_allowed,
    MIN(date)             AS first_date,
    MAX(date)             AS last_date
FROM windowed
"""


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────


def _build_batting_window(
    cursor: duckdb.DuckDBPyConnection,
    player_id: int,
    window_days: int,
) -> PlayerRecentBatting:
    row = cursor.execute(
        _BATTING_WINDOW_SQL, [player_id, player_id, window_days]
    ).fetchone()
    (games, pa, ab, h, d, t, hr, r, rbi, bb, k, hbp, sb, cs,
     first_date, last_date) = row
    # SF not tracked in game-grain — assume 0 for slash-line OBP denom.
    # Edge case: closer estimate; full season SF dilutes ~3pp OBP.
    avg, obp, slg, ops = _slash(h, ab, bb, hbp, 0, d, t, hr)
    return PlayerRecentBatting(
        window_days=window_days,
        games_in_window=int(games),
        first_date=first_date.isoformat() if first_date else None,
        last_date=last_date.isoformat() if last_date else None,
        pa=int(pa), ab=int(ab), h=int(h), d=int(d), t=int(t), hr=int(hr),
        r=int(r), rbi=int(rbi), bb=int(bb), k=int(k), hbp=int(hbp),
        sb=int(sb), cs=int(cs),
        avg=avg, obp=obp, slg=slg, ops=ops,
    )


def _build_pitching_window(
    cursor: duckdb.DuckDBPyConnection,
    player_id: int,
    window_days: int,
) -> PlayerRecentPitching:
    row = cursor.execute(
        _PITCHING_WINDOW_SQL, [player_id, player_id, window_days]
    ).fetchone()
    (games, starts, outs, bf, h, r, er, bb, k, hr_allowed,
     first_date, last_date) = row
    outs_int = int(outs)
    era = _rate_per_9(int(er), outs_int)
    whip = _whip(int(bb), int(h), outs_int)
    k9 = _rate_per_9(int(k), outs_int)
    bb9 = _rate_per_9(int(bb), outs_int)
    return PlayerRecentPitching(
        window_days=window_days,
        games_in_window=int(games),
        starts=int(starts),
        first_date=first_date.isoformat() if first_date else None,
        last_date=last_date.isoformat() if last_date else None,
        outs=outs_int,
        ip_display=_outs_to_ip_display(outs_int),
        bf=int(bf), h=int(h), r=int(r), er=int(er),
        bb=int(bb), k=int(k), hr_allowed=int(hr_allowed),
        era=era, whip=whip, k_per_9=k9, bb_per_9=bb9,
    )


def _has_game_tables(cursor: duckdb.DuckDBPyConnection) -> bool:
    """Check whether the game-grain tables exist (Phase 4b Tier A).

    Returns False on a pre-Tier-A warehouse — caller returns an empty
    response so the player page degrades gracefully.
    """
    row = cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name IN ('f_player_game_batting', 'f_player_game_pitching')"
    ).fetchone()
    return row[0] >= 2


def _player_exists(cursor: duckdb.DuckDBPyConnection, player_id: int) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM players_current WHERE player_id = ? LIMIT 1",
        [player_id],
    ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


def _parse_windows(raw: str) -> list[int]:
    """Parse `?windows=7,15,30` → ``[7, 15, 30]``. Reject non-positive, dedupe."""
    seen: set[int] = set()
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            n = int(token)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid window value: {token!r} (expected positive int)",
            ) from e
        if n <= 0 or n > 365:
            raise HTTPException(
                status_code=400,
                detail=f"Window {n} out of range (must be 1..365)",
            )
        if n not in seen:
            seen.add(n)
            out.append(n)
    if not out:
        raise HTTPException(
            status_code=400,
            detail="At least one window required (default: 7,15,30)",
        )
    return out


@router.get(
    "/players/{player_id}/recent",
    response_model=PlayerRecentResponse,
)
def get_player_recent(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    player_id: int,
    windows: Annotated[
        str,
        Query(description="Comma-separated calendar-day windows, e.g. '7,15,30'"),
    ] = "7,15,30",
) -> PlayerRecentResponse:
    """Rolling-window batting + pitching aggregates for one player.

    Per Phase 4b Tier D: powers the "Last 7 / 15 / 30 days" toggle on
    the player page Stats tab. Source = ``f_player_game_batting`` /
    ``f_player_game_pitching`` (Tier A, regular-season only).
    """
    if not _player_exists(cursor, player_id):
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
    window_list = _parse_windows(windows)

    # Tier A may not yet be built on legacy warehouses — degrade gracefully.
    if not _has_game_tables(cursor):
        return PlayerRecentResponse(player_id=player_id, bat=[], pit=[])

    bat_has_data = cursor.execute(
        "SELECT 1 FROM f_player_game_batting WHERE player_id = ? AND game_type = 0 LIMIT 1",
        [player_id],
    ).fetchone() is not None
    pit_has_data = cursor.execute(
        "SELECT 1 FROM f_player_game_pitching WHERE player_id = ? AND game_type = 0 LIMIT 1",
        [player_id],
    ).fetchone() is not None

    bat_rows: list[PlayerRecentBatting] = []
    pit_rows: list[PlayerRecentPitching] = []
    if bat_has_data:
        bat_rows = [_build_batting_window(cursor, player_id, w) for w in window_list]
    if pit_has_data:
        pit_rows = [_build_pitching_window(cursor, player_id, w) for w in window_list]

    return PlayerRecentResponse(
        player_id=player_id,
        bat=bat_rows,
        pit=pit_rows,
    )
