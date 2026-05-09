"""Streaks endpoint — backs ``/history/streaks``.

Endpoint:
- ``GET /api/streaks?streak_id=&scope=&limit=`` — top-N streak holders
  for one (streak_id × scope) leaderboard. Defaults: streak_id=0
  (HITTING_STREAK), scope=all_time, limit=25.

Implementation notes:

- Source table is ``f_player_streak`` (L3 fact, top-50 per
  (streak_id, scope) — already pre-ranked + capped).
- ``available_streaks`` lists every ``streak_id`` that has at least
  one row, with its ``streak_label`` (denormalized in L3) and the
  scopes available. Used by the frontend picker; we never offer
  streaks that don't have data.
- Picker order — headline streaks (Hitting / Scoreless Innings /
  On-Base / Win) first, then per-skill / per-game streaks, then
  rare codes (17, 18, 11). Order matches the most-likely-to-care-
  about-first reading.
- ``ended`` is stored as a string in L3 because OOTP's date format
  in the dump (``"2028-7-29"``) doesn't always zero-pad single-digit
  months. The route passes it through verbatim; the UI handles
  rendering.
- Forgiving fallbacks: bad ``streak_id`` / ``scope`` → defaults
  rather than 404, matching the records / awards pattern.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import (
    StreakCategoryRef,
    StreakRow,
    StreaksResponse,
)
from diamond.api.warehouse import get_cursor
from diamond.constants import StreakId

router = APIRouter()


_DEFAULT_STREAK_ID = int(StreakId.HITTING_STREAK)  # 0
_DEFAULT_SCOPE = "all_time"
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100

_VALID_SCOPES = {"active", "all_time"}


# Picker order — headline streaks first (Hitting / Scoreless Innings
# / Win / On-Base) so the page lands on the most-watched leaderboards
# without scrolling. Lower priority codes (the ``Rare`` ones) trail.
# Codes missing from the warehouse drop out at filter time.
_STREAK_PICKER_ORDER: list[int] = [
    int(StreakId.HITTING_STREAK),                # 0 — headline batter
    int(StreakId.SCORELESS_INNINGS_STREAK),      # 4 — headline pitcher
    int(StreakId.ON_BASE_STREAK),                # 15
    int(StreakId.WIN_STREAK),                    # 5
    int(StreakId.QS_STREAK),                     # 6
    int(StreakId.MULTI_HIT_GAME_STREAK),         # 1
    int(StreakId.THREE_PLUS_HIT_GAME_STREAK),    # 2
    int(StreakId.HR_GAME_STREAK),                # 3
    int(StreakId.NO_HR_ALLOWED_STREAK),          # 7
    int(StreakId.NO_WALK_ALLOWED_STREAK),        # 8
    int(StreakId.GAMES_PLAYED_STREAK),           # 9
    int(StreakId.EXTRA_BASE_HIT_STREAK),         # 10
    int(StreakId.SAVES_STREAK),                  # 12
    int(StreakId.RBI_STREAK),                    # 13
    int(StreakId.RUN_STREAK),                    # 14
    int(StreakId.LOSS_STREAK),                   # 16
    int(StreakId.K_STREAK),                      # 19
    int(StreakId.APPEARANCE_STREAK),             # 21
    # Rare / low-priority — surfaced last but kept available
    int(StreakId.PITCHER_MIXED_11),              # 11
    int(StreakId.BATTER_RARE_17),                # 17
    int(StreakId.BATTER_RARE_18),                # 18
]


# ─────────────────────────────────────────────────────────────────────────────
# Argument coercion
# ─────────────────────────────────────────────────────────────────────────────


def _coerce_scope(raw: str | None) -> str:
    s = (raw or "").lower()
    if s not in _VALID_SCOPES:
        s = _DEFAULT_SCOPE
    return s


def _coerce_limit(raw: int | None) -> int:
    if raw is None:
        return _DEFAULT_LIMIT
    if raw < 1:
        return _DEFAULT_LIMIT
    if raw > _MAX_LIMIT:
        return _MAX_LIMIT
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_available_streaks(
    con: duckdb.DuckDBPyConnection,
) -> list[StreakCategoryRef]:
    """Every streak_id present in f_player_streak with its label and
    available scopes. Ordered per ``_STREAK_PICKER_ORDER`` with any
    unmapped codes appended at the tail."""
    rows = con.execute(
        """
        SELECT streak_id, ANY_VALUE(streak_label) AS streak_label, scope
        FROM f_player_streak
        GROUP BY streak_id, scope
        """
    ).fetchall()

    by_id: dict[int, dict[str, object]] = {}
    for streak_id, label, scope in rows:
        entry = by_id.setdefault(int(streak_id), {"label": label, "scopes": set()})
        entry["scopes"].add(scope)  # type: ignore[union-attr]

    out: list[StreakCategoryRef] = []
    seen: set[int] = set()
    for sid in _STREAK_PICKER_ORDER:
        if sid not in by_id:
            continue
        entry = by_id[sid]
        scopes_ordered = sorted(
            entry["scopes"],  # type: ignore[arg-type]
            key=lambda s: 0 if s == "all_time" else 1,
        )
        out.append(
            StreakCategoryRef(
                streak_id=sid,
                label=str(entry["label"] or f"Streak {sid}"),
                available_scopes=scopes_ordered,  # type: ignore[arg-type]
            )
        )
        seen.add(sid)

    # Defensive: any streak_id present in data but not in the picker
    # order list shows up at the tail with its raw label.
    for sid, entry in by_id.items():
        if sid in seen:
            continue
        scopes_ordered = sorted(
            entry["scopes"],  # type: ignore[arg-type]
            key=lambda s: 0 if s == "all_time" else 1,
        )
        out.append(
            StreakCategoryRef(
                streak_id=sid,
                label=str(entry["label"] or f"Streak {sid}"),
                available_scopes=scopes_ordered,  # type: ignore[arg-type]
            )
        )
    return out


def _fetch_streak_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    streak_id: int,
    scope: str,
    limit: int,
) -> tuple[list[StreakRow], int, str]:
    """Top-N rows + (count, label).

    L3 already top-50'd at build time, so the limit is just a cap on
    the rendered list. ``total_in_scope`` is min(50, actual rows) —
    matches the storage shape; we don't claim to surface streaks
    beyond rank 50.
    """
    total = int(
        con.execute(
            "SELECT COUNT(*) FROM f_player_streak WHERE streak_id = ? AND scope = ?",
            [streak_id, scope],
        ).fetchone()[0]
    )

    rows = con.execute(
        """
        SELECT
            rank_in_scope, player_id, display_name, value,
            has_ended, started, ended, league_id, team_abbr,
            streak_label
        FROM f_player_streak
        WHERE streak_id = ? AND scope = ?
        ORDER BY rank_in_scope ASC
        LIMIT ?
        """,
        [streak_id, scope, limit],
    ).fetchall()

    label = ""
    out: list[StreakRow] = []
    for r in rows:
        (rank_in_scope, player_id, display_name, value,
         has_ended, started, ended, league_id, team_abbr,
         streak_label) = r
        if not label and streak_label:
            label = streak_label
        out.append(
            StreakRow(
                rank=int(rank_in_scope),
                player_id=int(player_id) if player_id is not None else None,
                display_name=display_name,
                value=int(value) if value is not None else 0,
                has_ended=bool(has_ended) if has_ended is not None else True,
                started=started if isinstance(started, date) else None,
                ended=ended if ended and ended != "NULL" else None,
                league_id=int(league_id) if league_id is not None else None,
                team_abbr=team_abbr,
            )
        )
    return out, total, label


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/streaks", response_model=StreaksResponse)
def get_streaks(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    streak_id: Annotated[
        int | None,
        Query(
            description=(
                "StreakId enum value. Defaults to HITTING_STREAK (0). "
                "See diamond.constants.StreakId for the full enumeration."
            ),
        ),
    ] = None,
    scope: Annotated[
        str | None,
        Query(description="active | all_time"),
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=_MAX_LIMIT, description=f"Top-N rows. Defaults to {_DEFAULT_LIMIT}."),
    ] = None,
) -> StreaksResponse:
    """One streak's leaderboard, top-N holders."""
    resolved_scope = _coerce_scope(scope)
    resolved_limit = _coerce_limit(limit)

    available_streaks = _fetch_available_streaks(con)
    if not available_streaks:
        return StreaksResponse(
            streak_id=_DEFAULT_STREAK_ID,
            streak_label="",
            scope=resolved_scope,  # type: ignore[arg-type]
            available_streaks=[],
            rows=[],
            total_in_scope=0,
        )

    available_ids = {s.streak_id for s in available_streaks}
    resolved_streak_id = (
        streak_id if streak_id is not None else _DEFAULT_STREAK_ID
    )
    if resolved_streak_id not in available_ids:
        # Fall back to default (hitting) if available, else first.
        resolved_streak_id = (
            _DEFAULT_STREAK_ID
            if _DEFAULT_STREAK_ID in available_ids
            else available_streaks[0].streak_id
        )

    streak_meta = next(
        s for s in available_streaks if s.streak_id == resolved_streak_id
    )
    if resolved_scope not in streak_meta.available_scopes:
        # Defensive — every streak should have both scopes in our build,
        # but if a future warehouse build loses one, fall back to the
        # other instead of returning empty.
        resolved_scope = streak_meta.available_scopes[0]

    rows, total, label = _fetch_streak_rows(
        con,
        streak_id=resolved_streak_id,
        scope=resolved_scope,
        limit=resolved_limit,
    )

    return StreaksResponse(
        streak_id=resolved_streak_id,
        streak_label=label or streak_meta.label,
        scope=resolved_scope,  # type: ignore[arg-type]
        available_streaks=available_streaks,
        rows=rows,
        total_in_scope=total,
    )
