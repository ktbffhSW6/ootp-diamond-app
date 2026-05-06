"""Roster endpoint — backs the ``/roster`` page.

Endpoint:
- ``GET /api/roster`` — every active player in the user's org tree,
  grouped by current level, with latest-season stats *at that level*
  plus the advanced stack for the basic/advanced toggle.

Implementation notes:

- One big SQL JOIN. The page wants every player in one render pass and
  client-side filters operate on the whole payload — pagination would
  hurt UX (collapsing all the lower levels behind a "more" click is
  worse than scrolling). With ~200 players per org and local-first
  DuckDB, total round-trip is sub-100ms.

- Stats are pulled at the player's CURRENT (team_id, league_id, level_id)
  for the latest season. A player who bounced AAA→MLB this year and is
  currently on the MLB roster shows ONLY their MLB stats here. The
  player page is the place to see cross-level totals.

- Advanced facts are at (player, year, league_id, level_id) — already
  collapsed across stints within a level. We join on level rather than
  team_id since intra-level moves are rare and the advanced collapse
  handles them correctly.

- Sort within each (level, role) bucket: position number then overall
  rating descending then last name. Position number gives the natural
  "C, 1B, 2B, 3B, SS, LF, CF, RF, DH" ordering (1-9, 10=DH for
  position players; pitchers all share position=1 so OVR sort drives
  there).

- Org tree filter: ``COALESCE(NULLIF(parent_team_id, 0), team_id) = ?``
  — same pattern as the movements route. Includes the parent team
  (MLB Boston) plus every affiliate.
"""

from __future__ import annotations

from typing import Annotated, Any

import duckdb
from fastapi import APIRouter, Depends

from diamond.api.schemas import (
    RosterBattingLine,
    RosterLevelGroup,
    RosterPitchingLine,
    RosterPlayer,
    RosterResponse,
    RosterTeamRef,
)
from diamond.api.schemas.roster import RosterRole
from diamond.api.warehouse import get_active_save, get_cursor
from diamond.constants import LEVEL_NAMES, POSITION_NAMES

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Local codebooks — bats / throws display
# ─────────────────────────────────────────────────────────────────────────────

_BATS = {1: "R", 2: "L", 3: "S"}
_THROWS = {1: "R", 2: "L"}


def _bats_display(code: int | None) -> str:
    if code is None:
        return "?"
    return _BATS.get(int(code), "?")


def _throws_display(code: int | None) -> str:
    if code is None:
        return "?"
    return _THROWS.get(int(code), "?")


def _full_name(first: str, last: str, nick: str | None) -> str:
    """Display name: prefer nick when present (matches player-page bio)."""
    if nick:
        return f'{first} "{nick}" {last}'
    return f"{first} {last}"


def _position_display(position: int | None, throws: int | None) -> str:
    """Resolve display position. For pitchers, distinguish RHP/LHP from
    `throws` since the raw position code (1) collapses both."""
    if position is None:
        return "—"
    if int(position) == 1:
        # 1=R, 2=L; anything else falls back to plain "P"
        if throws == 1:
            return "RHP"
        if throws == 2:
            return "LHP"
        return "P"
    return POSITION_NAMES.get(int(position), f"P{position}")


# ─────────────────────────────────────────────────────────────────────────────
# Rate-stat helpers — mirror the player-route conventions exactly
# ─────────────────────────────────────────────────────────────────────────────


def _safe_div(num: float, denom: float) -> float | None:
    if denom == 0:
        return None
    return round(num / denom, 3)


def _slash_line(
    h: int, ab: int, bb: int, hbp: int, sf: int,
    d: int, t: int, hr: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    avg = _safe_div(h, ab)
    obp_denom = ab + bb + hbp + sf
    obp = _safe_div(h + bb + hbp, obp_denom)
    singles = h - d - t - hr
    tb = singles + 2 * d + 3 * t + 4 * hr
    slg = _safe_div(tb, ab)
    ops = (obp + slg) if (obp is not None and slg is not None) else None
    if ops is not None:
        ops = round(ops, 3)
    return avg, obp, slg, ops


def _pitch_rates(
    outs: int, er: int, h: int, bb: int, so: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    if outs == 0:
        return None, None, None, None
    ip = outs / 3.0
    era = round(9 * er / ip, 2)
    whip = round((h + bb) / ip, 2)
    k9 = round(9 * so / ip, 2)
    bb9 = round(9 * bb / ip, 2)
    return era, whip, k9, bb9


def _ip_display(outs: int) -> float:
    """Convert outs to Bref-style display IP: 517 outs → 172.1.

    NOT decimal IP — `172.1` here means 172⅓, not 172.1.
    """
    full = outs // 3
    frac = outs % 3
    return round(full + frac * 0.1, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Main query — one round-trip pulls every roster row
# ─────────────────────────────────────────────────────────────────────────────


_ROSTER_QUERY = """
WITH org_team_filter AS (
    SELECT team_id FROM teams
    WHERE COALESCE(NULLIF(parent_team_id, 0), team_id) = ?
),
latest_year AS (
    SELECT MAX(year) AS year FROM f_player_season_batting
)
SELECT
    p.player_id,
    p.first_name, p.last_name, p.nick_name,
    p.age, p.bats, p.throws, p.position,
    pr.overall_rating,
    -- current team identity
    t.team_id      AS team_id,
    t.abbr         AS team_abbr,
    t.nickname     AS team_nickname,
    t.league_id    AS league_id,
    l.abbr         AS league_abbr,
    t.level        AS level_id,
    -- batting (latest year, current level + team, overall split)
    CAST(b.g    AS BIGINT) AS b_g,
    CAST(b.pa   AS BIGINT) AS b_pa,
    CAST(b.ab   AS BIGINT) AS b_ab,
    CAST(b.h    AS BIGINT) AS b_h,
    CAST(b.d    AS BIGINT) AS b_d,
    CAST(b.t    AS BIGINT) AS b_t,
    CAST(b.hr   AS BIGINT) AS b_hr,
    CAST(b.rbi  AS BIGINT) AS b_rbi,
    CAST(b.sb   AS BIGINT) AS b_sb,
    CAST(b.bb   AS BIGINT) AS b_bb,
    CAST(b.k    AS BIGINT) AS b_so,
    CAST(b.hp   AS BIGINT) AS b_hbp,
    CAST(b.sf   AS BIGINT) AS b_sf,
    -- pitching (latest year, current level + team, overall split)
    CAST(pi.g    AS BIGINT) AS p_g,
    CAST(pi.gs   AS BIGINT) AS p_gs,
    CAST(pi.w    AS BIGINT) AS p_w,
    CAST(pi.l    AS BIGINT) AS p_l,
    CAST(pi.s    AS BIGINT) AS p_sv,
    CAST(pi.outs AS BIGINT) AS p_outs,
    CAST(pi.ha   AS BIGINT) AS p_h,
    CAST(pi.er   AS BIGINT) AS p_er,
    CAST(pi.bb   AS BIGINT) AS p_bb,
    CAST(pi.k    AS BIGINT) AS p_so,
    -- advanced batting at current (year, league, level)
    ab.woba, ab.wraa, ab.wrc, ab.wrc_plus, ab.ops_plus, ab.o_war,
    ab.park_avg AS bat_park_avg,
    -- advanced pitching at current (year, league, level)
    ap.fip, ap.siera, ap.era_plus, ap.pit_war,
    ap.park_avg AS pit_park_avg,
    -- Statcast cohort — generated as hitter
    sb.bip            AS sb_bip,
    sb.max_ev         AS sb_max_ev,
    sb.avg_ev         AS sb_avg_ev,
    sb.hard_hit_pct   AS sb_hard_hit_pct,
    sb.barrel_pct     AS sb_barrel_pct,
    sb.sweet_spot_pct AS sb_sweet_spot_pct,
    -- Statcast cohort — allowed as pitcher
    sp.bip            AS sp_bip,
    sp.max_ev         AS sp_max_ev,
    sp.avg_ev         AS sp_avg_ev,
    sp.hard_hit_pct   AS sp_hard_hit_pct,
    sp.barrel_pct     AS sp_barrel_pct,
    sp.sweet_spot_pct AS sp_sweet_spot_pct
FROM players_current p
JOIN teams              t ON t.team_id = p.team_id
JOIN org_team_filter    f ON f.team_id = t.team_id
LEFT JOIN leagues       l ON l.league_id = t.league_id
LEFT JOIN players_ratings_current pr ON pr.player_id = p.player_id
CROSS JOIN latest_year ly
LEFT JOIN f_player_season_batting b
       ON b.player_id = p.player_id
      AND b.year      = ly.year
      AND b.league_id = t.league_id
      AND b.level_id  = t.level
      AND b.team_id   = t.team_id
      AND b.split_id  = 1
LEFT JOIN f_player_season_pitching pi
       ON pi.player_id = p.player_id
      AND pi.year      = ly.year
      AND pi.league_id = t.league_id
      AND pi.level_id  = t.level
      AND pi.team_id   = t.team_id
      AND pi.split_id  = 1
LEFT JOIN f_player_season_advanced_batting ab
       ON ab.player_id = p.player_id
      AND ab.year      = ly.year
      AND ab.league_id = t.league_id
      AND ab.level_id  = t.level
LEFT JOIN f_player_season_advanced_pitching ap
       ON ap.player_id = p.player_id
      AND ap.year      = ly.year
      AND ap.league_id = t.league_id
      AND ap.level_id  = t.level
LEFT JOIN f_player_season_statcast_batting sb
       ON sb.player_id = p.player_id
      AND sb.year      = ly.year
      AND sb.league_id = t.league_id
      AND sb.level_id  = t.level
LEFT JOIN f_player_season_statcast_pitching sp
       ON sp.player_id = p.player_id
      AND sp.year      = ly.year
      AND sp.league_id = t.league_id
      AND sp.level_id  = t.level
WHERE p.retired = false
  AND p.team_id <> 0
ORDER BY t.level, p.position,
         COALESCE(pr.overall_rating, 0) DESC,
         p.last_name, p.first_name
"""


_COLUMNS: tuple[str, ...] = (
    "player_id", "first_name", "last_name", "nick_name",
    "age", "bats", "throws", "position", "overall_rating",
    "team_id", "team_abbr", "team_nickname", "league_id", "league_abbr",
    "level_id",
    "b_g", "b_pa", "b_ab", "b_h", "b_d", "b_t", "b_hr", "b_rbi",
    "b_sb", "b_bb", "b_so", "b_hbp", "b_sf",
    "p_g", "p_gs", "p_w", "p_l", "p_sv", "p_outs",
    "p_h", "p_er", "p_bb", "p_so",
    "woba", "wraa", "wrc", "wrc_plus", "ops_plus", "o_war", "bat_park_avg",
    "fip", "siera", "era_plus", "pit_war", "pit_park_avg",
    "sb_bip", "sb_max_ev", "sb_avg_ev",
    "sb_hard_hit_pct", "sb_barrel_pct", "sb_sweet_spot_pct",
    "sp_bip", "sp_max_ev", "sp_avg_ev",
    "sp_hard_hit_pct", "sp_barrel_pct", "sp_sweet_spot_pct",
)


# ─────────────────────────────────────────────────────────────────────────────
# Row construction
# ─────────────────────────────────────────────────────────────────────────────


def _team_ref(d: dict[str, Any]) -> RosterTeamRef | None:
    """Build a RosterTeamRef from the row's team columns. None if no team."""
    team_id = d.get("team_id")
    if team_id is None:
        return None
    level_id = d.get("level_id")
    return RosterTeamRef(
        team_id=int(team_id),
        abbr=d.get("team_abbr"),
        nickname=d.get("team_nickname"),
        league_id=d.get("league_id"),
        league_abbr=d.get("league_abbr"),
        level_id=int(level_id) if level_id is not None else None,
        level_name=LEVEL_NAMES.get(int(level_id)) if level_id is not None else None,
    )


def _batting_line(d: dict[str, Any]) -> RosterBattingLine | None:
    """Build a batting line, or None when the player has zero G this year
    at this level. A player on the roster who hasn't accumulated any
    stats yet (just called up, just signed, mid-debut etc.) gets None
    here and the table renders an em-dash row."""
    g = d.get("b_g")
    if g is None or int(g) == 0:
        return None
    h = int(d["b_h"])
    ab = int(d["b_ab"])
    bb = int(d["b_bb"])
    hbp = int(d["b_hbp"])
    sf = int(d["b_sf"])
    dd = int(d["b_d"])
    tt = int(d["b_t"])
    hr = int(d["b_hr"])
    avg, obp, slg, ops = _slash_line(h, ab, bb, hbp, sf, dd, tt, hr)
    return RosterBattingLine(
        g=int(g), pa=int(d["b_pa"]), ab=ab,
        h=h, hr=hr, rbi=int(d["b_rbi"]),
        sb=int(d["b_sb"]), bb=bb, so=int(d["b_so"]),
        avg=avg, obp=obp, slg=slg, ops=ops,
        woba=float(d["woba"]) if d.get("woba") is not None else None,
        wraa=float(d["wraa"]) if d.get("wraa") is not None else None,
        wrc=float(d["wrc"]) if d.get("wrc") is not None else None,
        wrc_plus=int(d["wrc_plus"]) if d.get("wrc_plus") is not None else None,
        ops_plus=int(d["ops_plus"]) if d.get("ops_plus") is not None else None,
        o_war=float(d["o_war"]) if d.get("o_war") is not None else None,
        park_avg=(
            float(d["bat_park_avg"]) if d.get("bat_park_avg") is not None else None
        ),
        statcast_bip=int(d["sb_bip"]) if d.get("sb_bip") is not None else None,
        statcast_max_ev=(
            float(d["sb_max_ev"]) if d.get("sb_max_ev") is not None else None
        ),
        statcast_avg_ev=(
            float(d["sb_avg_ev"]) if d.get("sb_avg_ev") is not None else None
        ),
        statcast_hard_hit_pct=(
            float(d["sb_hard_hit_pct"]) if d.get("sb_hard_hit_pct") is not None else None
        ),
        statcast_barrel_pct=(
            float(d["sb_barrel_pct"]) if d.get("sb_barrel_pct") is not None else None
        ),
        statcast_sweet_spot_pct=(
            float(d["sb_sweet_spot_pct"]) if d.get("sb_sweet_spot_pct") is not None else None
        ),
    )


def _pitching_line(d: dict[str, Any]) -> RosterPitchingLine | None:
    """Build a pitching line, or None when the player has zero G or zero
    outs this year at this level."""
    g = d.get("p_g")
    outs = d.get("p_outs")
    if g is None or int(g) == 0 or outs is None:
        return None
    outs_i = int(outs)
    era, whip, k9, bb9 = _pitch_rates(
        outs_i, int(d["p_er"]), int(d["p_h"]),
        int(d["p_bb"]), int(d["p_so"]),
    )
    return RosterPitchingLine(
        g=int(g), gs=int(d["p_gs"]),
        w=int(d["p_w"]), l=int(d["p_l"]), sv=int(d["p_sv"]),
        outs=outs_i, ip_display=_ip_display(outs_i),
        era=era, whip=whip, k_per_9=k9, bb_per_9=bb9,
        fip=float(d["fip"]) if d.get("fip") is not None else None,
        siera=float(d["siera"]) if d.get("siera") is not None else None,
        era_plus=int(d["era_plus"]) if d.get("era_plus") is not None else None,
        pit_war=float(d["pit_war"]) if d.get("pit_war") is not None else None,
        park_avg=(
            float(d["pit_park_avg"]) if d.get("pit_park_avg") is not None else None
        ),
        statcast_bip=int(d["sp_bip"]) if d.get("sp_bip") is not None else None,
        statcast_max_ev=(
            float(d["sp_max_ev"]) if d.get("sp_max_ev") is not None else None
        ),
        statcast_avg_ev=(
            float(d["sp_avg_ev"]) if d.get("sp_avg_ev") is not None else None
        ),
        statcast_hard_hit_pct=(
            float(d["sp_hard_hit_pct"]) if d.get("sp_hard_hit_pct") is not None else None
        ),
        statcast_barrel_pct=(
            float(d["sp_barrel_pct"]) if d.get("sp_barrel_pct") is not None else None
        ),
        statcast_sweet_spot_pct=(
            float(d["sp_sweet_spot_pct"]) if d.get("sp_sweet_spot_pct") is not None else None
        ),
    )


def _player_from_row(d: dict[str, Any]) -> RosterPlayer:
    """Map one query row to a RosterPlayer. Role = pitcher when position=1,
    else batter — matches the movement-ledger convention (two-way players
    are filed by primary position for v1)."""
    position = d.get("position")
    role: RosterRole = (
        "pitcher" if position is not None and int(position) == 1
        else "batter"
    )
    is_pitcher = role == "pitcher"
    return RosterPlayer(
        player_id=int(d["player_id"]),
        full_name=_full_name(d["first_name"], d["last_name"], d["nick_name"]),
        primary_position=_position_display(position, d.get("throws")),
        role=role,
        age=int(d["age"]) if d.get("age") is not None else None,
        bats=_bats_display(d.get("bats")),
        throws=_throws_display(d.get("throws")),
        overall_rating=(
            int(d["overall_rating"]) if d.get("overall_rating") is not None else None
        ),
        team=_team_ref(d),
        # Pitchers occasionally have a token PA (NL pre-DH cameo) that
        # triggers a batting line; we drop it to keep the pitcher table
        # focused on pitching. Same logic in reverse for batters.
        batting=None if is_pitcher else _batting_line(d),
        pitching=_pitching_line(d) if is_pitcher else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/roster", response_model=RosterResponse)
def get_roster(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> RosterResponse:
    """Active roster across the user's org tree, grouped by level.

    Single round-trip: one big SQL pulls every (player + current team +
    season stats + advanced) tuple, then Python folds them into level
    groups. Filters / sort / basic-vs-advanced toggle are all client-
    side over this payload.
    """
    save = get_active_save()
    org_team_id = save.audit_team_id

    # Org headline metadata for the page header (mirrors movements route).
    org_meta = con.execute(
        "SELECT abbr, nickname FROM teams WHERE team_id = ?",
        [org_team_id],
    ).fetchone()
    org_abbr, org_nickname = (org_meta or (None, None))

    # Latest year — for the header and as a sentinel when the warehouse
    # has no stats yet (fresh ingest before first season completes).
    latest_year_row = con.execute(
        "SELECT MAX(year) FROM f_player_season_batting"
    ).fetchone()
    latest_year = (
        int(latest_year_row[0])
        if latest_year_row and latest_year_row[0] is not None
        else 0
    )

    rows = con.execute(_ROSTER_QUERY, [org_team_id]).fetchall()
    dicts = [dict(zip(_COLUMNS, r, strict=True)) for r in rows]

    # Group by level_id; within a level split by role. SQL pre-orders
    # by (level, position, OVR DESC, last name) so the bucket lists are
    # already in display order — no further sort needed in Python.
    by_level: dict[int, dict[str, list[RosterPlayer]]] = {}
    for d in dicts:
        level_id = d.get("level_id")
        if level_id is None:
            continue
        level_id = int(level_id)
        bucket = by_level.setdefault(
            level_id, {"position_players": [], "pitchers": []}
        )
        player = _player_from_row(d)
        if player.role == "pitcher":
            bucket["pitchers"].append(player)
        else:
            bucket["position_players"].append(player)

    groups = [
        RosterLevelGroup(
            level_id=level_id,
            level_name=LEVEL_NAMES.get(level_id, f"L{level_id}"),
            position_players=by_level[level_id]["position_players"],
            pitchers=by_level[level_id]["pitchers"],
        )
        for level_id in sorted(by_level)   # 1=MLB first, then 2=AAA, ...
    ]

    return RosterResponse(
        season=latest_year,
        org_team_id=org_team_id,
        org_team_abbr=org_abbr,
        org_team_nickname=org_nickname,
        groups=groups,
    )
