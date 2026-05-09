"""Player endpoint — backs the ``/player/[id]`` page's Stats tab.

Endpoint:
- ``GET /api/players/{player_id}`` — bio + per-stint batting/pitching
  + career totals.

Implementation notes:

- One big response. The Stats tab needs everything in one render pass
  (header bio, season-by-season tables with stint expansion). Local-
  first DuckDB makes the latency cost trivial; one round-trip is
  cleaner than fanning out per section.
- Stints come from `f_player_season_batting` / `_pitching` keyed at
  (year, league_id, level_id, split_id, team_id), filtered to
  `split_id = 1` (the overall — vs LHP / vs RHP would double-count).
- The "TOT" combined row per season is synthesized in Python after
  the SQL. Cheaper than a UNION + GROUP BY, and easier to read.
- Rate stats (AVG/OBP/SLG/OPS, ERA/WHIP/K9/BB9) are computed in this
  module rather than in SQL — keeps the SQL straightforward and lets
  the same arithmetic apply to the synthesized combined rows.
- Position / level codebooks live in `diamond.constants`. Bats/throws
  are spelled out here as a private mapping since they're not used
  outside this module.
"""

from __future__ import annotations

from typing import Annotated, Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from diamond.api.schemas import (
    PlayerAdvancedBattingRow,
    PlayerAdvancedPitchingRow,
    PlayerBattingSeason,
    PlayerBattingStint,
    PlayerBio,
    PlayerCareerBatting,
    PlayerCareerFielding,
    PlayerCareerPitching,
    PlayerFieldingRow,
    PlayerPitchingSeason,
    PlayerPitchingStint,
    PlayerPositionFielding,
    PlayerResponse,
    PlayerRosterStatus,
    PlayerSituationalRow,
    TeamRef,
)
from diamond.api.warehouse import get_cursor
from diamond.constants import LEVEL_NAMES, POSITION_NAMES

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Local codebooks
# ─────────────────────────────────────────────────────────────────────────────

# `players.bats` and `.throws` codes — verified by inspection. These
# aren't IntEnums in `constants.py` because they only show up in
# bio-display contexts and the integers carry no semantic flags.
_BATS = {1: "R", 2: "L", 3: "S"}
_THROWS = {1: "R", 2: "L"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — rate-stat computation
# ─────────────────────────────────────────────────────────────────────────────


def _safe_div(num: float, denom: float) -> float | None:
    """Division returning None on zero denominator, rounded to 3 places.

    Three decimals matches Bref / Fangraphs convention for slash-line
    stats. ERA / WHIP get extra precision in their helper.
    """
    if denom == 0:
        return None
    return round(num / denom, 3)


def _slash_line(
    h: int, ab: int, bb: int, hbp: int, sf: int,
    d: int, t: int, hr: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute (AVG, OBP, SLG, OPS) from the counting components.

    Returns (None, None, None, None) when AB is zero — pitcher rows
    that never came to bat fall through the same code path cleanly.
    """
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
    """Compute (ERA, WHIP, K/9, BB/9) from outs + counting components.

    Returns (None, None, None, None) when the pitcher recorded no
    outs — same-shape clean handling for position-player pitching
    rows that never accumulated outs.
    """
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

    NOT decimal IP — `172.1` here means 172⅓, not 172.1. Per the
    project's IP convention (CLAUDE.md / D6 / dictionary IP entry).
    """
    full = outs // 3
    frac = outs % 3
    return round(full + frac * 0.1, 1)


def _fpct(po: int, a: int, e: int) -> float | None:
    """Fielding percentage: (PO+A)/(PO+A+E). None when no chances."""
    chances = po + a + e
    if chances == 0:
        return None
    return round((po + a) / chances, 3)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — bio + team ref
# ─────────────────────────────────────────────────────────────────────────────


def _team_ref(row: dict[str, Any] | None) -> TeamRef | None:
    """Build a TeamRef from a flat row of team/league lookup columns.

    Caller passes a dict with keys: team_id, team_abbr, team_nickname,
    league_id, league_abbr, level_id. Returns None when team_id is
    null (free-agent stints recorded with no team). Single-team
    misses (where the FK doesn't resolve) still return a ref with
    nulls — better to surface the team_id than to drop the row.
    """
    if row is None or row.get("team_id") is None:
        return None
    level_id = row.get("level_id")
    return TeamRef(
        team_id=int(row["team_id"]),
        abbr=row.get("team_abbr"),
        nickname=row.get("team_nickname"),
        league_id=row.get("league_id"),
        league_abbr=row.get("league_abbr"),
        level_id=level_id,
        level_name=LEVEL_NAMES.get(level_id) if level_id is not None else None,
    )


def _full_name(first: str, last: str, nick: str | None) -> str:
    """Display name: prefer nick when present (matches Bref bio header)."""
    if nick:
        return f'{first} "{nick}" {last}'
    return f"{first} {last}"


def _bats_throws_display(bats: int | None, throws: int | None) -> str:
    """L/R-style display, falling back to '?' when codes are missing."""
    b = _BATS.get(bats, "?") if bats is not None else "?"
    t = _THROWS.get(throws, "?") if throws is not None else "?"
    return f"{b}/{t}"


def _build_bio(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> PlayerBio | None:
    """Pull the player's bio row + current team. None if no such player."""
    row = con.execute(
        """
        SELECT
            p.player_id,
            p.historical_id   AS bbref_id,
            p.first_name, p.last_name, p.nick_name,
            p.age, p.date_of_birth,
            p.height, p.weight,
            p.bats, p.throws,
            p.position,
            p.uniform_number,
            p.retired, p.free_agent, p.hall_of_fame,
            -- current team (zero / null means no current org)
            t.team_id          AS team_id,
            t.abbr             AS team_abbr,
            t.nickname         AS team_nickname,
            t.league_id        AS team_league_id,
            l.abbr             AS team_league_abbr,
            t.level            AS team_level_id
        FROM players_current p
        LEFT JOIN teams   t ON t.team_id   = p.team_id   AND p.team_id   <> 0
        LEFT JOIN leagues l ON l.league_id = t.league_id
        WHERE p.player_id = ?
        """,
        [player_id],
    ).fetchone()
    if row is None:
        return None
    cols = [
        "player_id", "bbref_id", "first_name", "last_name", "nick_name",
        "age", "date_of_birth", "height", "weight", "bats", "throws",
        "position", "uniform_number", "retired", "free_agent",
        "hall_of_fame", "team_id", "team_abbr", "team_nickname",
        "team_league_id", "team_league_abbr", "team_level_id",
    ]
    r = dict(zip(cols, row, strict=True))
    current_team = _team_ref({
        "team_id": r["team_id"],
        "team_abbr": r["team_abbr"],
        "team_nickname": r["team_nickname"],
        "league_id": r["team_league_id"],
        "league_abbr": r["team_league_abbr"],
        "level_id": r["team_level_id"],
    })
    return PlayerBio(
        player_id=int(r["player_id"]),
        bbref_id=r["bbref_id"],
        first_name=r["first_name"],
        last_name=r["last_name"],
        nick_name=r["nick_name"],
        full_name=_full_name(r["first_name"], r["last_name"], r["nick_name"]),
        age=int(r["age"]) if r["age"] is not None else None,
        date_of_birth=r["date_of_birth"].isoformat() if r["date_of_birth"] else None,
        height_cm=int(r["height"]) if r["height"] else None,
        weight_kg=int(r["weight"]) if r["weight"] else None,
        bats=int(r["bats"]) if r["bats"] is not None else None,
        throws=int(r["throws"]) if r["throws"] is not None else None,
        bats_throws=_bats_throws_display(r["bats"], r["throws"]),
        position=int(r["position"]) if r["position"] is not None else None,
        position_name=POSITION_NAMES.get(int(r["position"]), "—")
                       if r["position"] is not None else "—",
        uniform_number=int(r["uniform_number"]) if r["uniform_number"] else None,
        retired=bool(r["retired"]),
        free_agent=bool(r["free_agent"]),
        hall_of_fame=bool(r["hall_of_fame"]),
        current_team=current_team,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stints — batting / pitching pulls
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_batting_stints(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[dict[str, Any]]:
    """Return one dict per (year, league, level, team) batting stint.

    Filters to `split_id = 1` (the overall split) per the convention
    used everywhere else in the warehouse — vs-LHP / vs-RHP would
    double-count if folded in.
    """
    rows = con.execute(
        """
        SELECT
            b.year, b.league_id, b.level_id, b.team_id,
            t.abbr            AS team_abbr,
            t.nickname        AS team_nickname,
            l.abbr            AS league_abbr,
            -- player age that season (year minus birth year — close enough
            -- for display; OOTP doesn't carry per-season age in the fact)
            (b.year - EXTRACT(YEAR FROM p.date_of_birth))::INTEGER AS age,
            -- counting cols (CAST HUGEINT → BIGINT for Pydantic int compat)
            CAST(b.g    AS BIGINT) AS g,
            CAST(b.pa   AS BIGINT) AS pa,
            CAST(b.ab   AS BIGINT) AS ab,
            CAST(b.r    AS BIGINT) AS r,
            CAST(b.h    AS BIGINT) AS h,
            CAST(b.d    AS BIGINT) AS d,
            CAST(b.t    AS BIGINT) AS t,
            CAST(b.hr   AS BIGINT) AS hr,
            CAST(b.rbi  AS BIGINT) AS rbi,
            CAST(b.sb   AS BIGINT) AS sb,
            CAST(b.cs   AS BIGINT) AS cs,
            CAST(b.bb   AS BIGINT) AS bb,
            CAST(b.k    AS BIGINT) AS so,
            CAST(b.hp   AS BIGINT) AS hbp,
            CAST(b.sf   AS BIGINT) AS sf
        FROM f_player_season_batting b
        LEFT JOIN teams   t ON t.team_id   = b.team_id
        LEFT JOIN leagues l ON l.league_id = b.league_id
        LEFT JOIN players_current p ON p.player_id = b.player_id
        WHERE b.player_id = ? AND b.split_id = 1
        ORDER BY b.year, b.level_id, t.abbr
        """,
        [player_id],
    ).fetchall()
    cols = [
        "year", "league_id", "level_id", "team_id",
        "team_abbr", "team_nickname", "league_abbr", "age",
        "g", "pa", "ab", "r", "h", "d", "t", "hr",
        "rbi", "sb", "cs", "bb", "so", "hbp", "sf",
    ]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _fetch_fielding_rows(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[dict[str, Any]]:
    """Return one dict per (year, league, level, team, position) fielding row.

    Filters to `split_id = 0` (fielding has no platoon split — the
    overall aggregate is `split_id = 0`, not 1). `inn_outs` is computed
    server-side as `ip*3 + ipf` to keep the API surface in canonical
    units.
    """
    rows = con.execute(
        """
        SELECT
            f.year, f.league_id, f.level_id, f.team_id, f.position,
            t.abbr            AS team_abbr,
            t.nickname        AS team_nickname,
            l.abbr            AS league_abbr,
            (f.year - EXTRACT(YEAR FROM pl.date_of_birth))::INTEGER AS age,
            CAST(f.g    AS BIGINT) AS g,
            CAST(f.gs   AS BIGINT) AS gs,
            CAST(f.ip   AS BIGINT) AS ip,
            CAST(f.ipf  AS BIGINT) AS ipf,
            CAST(f.po   AS BIGINT) AS po,
            CAST(f.a    AS BIGINT) AS a,
            CAST(f.e    AS BIGINT) AS e,
            CAST(f.dp   AS BIGINT) AS dp
        FROM f_player_season_fielding f
        LEFT JOIN teams   t  ON t.team_id   = f.team_id
        LEFT JOIN leagues l  ON l.league_id = f.league_id
        LEFT JOIN players_current pl ON pl.player_id = f.player_id
        WHERE f.player_id = ? AND f.split_id = 0
        ORDER BY f.year, f.position, f.level_id, t.abbr
        """,
        [player_id],
    ).fetchall()
    cols = [
        "year", "league_id", "level_id", "team_id", "position",
        "team_abbr", "team_nickname", "league_abbr", "age",
        "g", "gs", "ip", "ipf", "po", "a", "e", "dp",
    ]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _fetch_advanced_batting(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[PlayerAdvancedBattingRow]:
    """Pull pre-materialized advanced batting rows from the L3 table.

    See `src/diamond/schema/l3_advanced.py` for the grain rationale —
    one row per (player, year, league_id, level_id), with park factor
    and league constants resolved at build time.
    """
    rows = con.execute(
        """
        SELECT
            f.year, f.league_id, f.level_id,
            l.abbr            AS league_abbr,
            (f.year - EXTRACT(YEAR FROM pl.date_of_birth))::INTEGER AS age,
            CAST(f.pa AS BIGINT) AS pa,
            f.woba, f.wraa, f.wrc, f.wrc_plus, f.ops_plus, f.o_war, f.b_war,
            f.park_avg
        FROM f_player_season_advanced_batting f
        LEFT JOIN leagues         l  ON l.league_id  = f.league_id
        LEFT JOIN players_current pl ON pl.player_id = f.player_id
        WHERE f.player_id = ?
        ORDER BY f.year, f.level_id, f.league_id
        """,
        [player_id],
    ).fetchall()
    out: list[PlayerAdvancedBattingRow] = []
    for r in rows:
        (year, league_id, level_id, league_abbr, age, pa,
         woba, wraa, wrc, wrc_plus, ops_plus, o_war, b_war, park_avg) = r
        out.append(PlayerAdvancedBattingRow(
            year=int(year),
            age=int(age) if age is not None else None,
            level_id=int(level_id),
            level_name=LEVEL_NAMES.get(int(level_id), f"L{level_id}"),
            league_id=int(league_id),
            league_abbr=league_abbr,
            pa=int(pa),
            woba=float(woba) if woba is not None else None,
            wraa=float(wraa) if wraa is not None else None,
            wrc=float(wrc) if wrc is not None else None,
            wrc_plus=int(wrc_plus) if wrc_plus is not None else None,
            ops_plus=int(ops_plus) if ops_plus is not None else None,
            o_war=float(o_war) if o_war is not None else None,
            b_war=float(b_war) if b_war is not None else None,
            park_avg=float(park_avg) if park_avg is not None else None,
        ))
    return out


def _fetch_advanced_pitching(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[PlayerAdvancedPitchingRow]:
    """Pull pre-materialized advanced pitching rows.

    Filtered server-side to outs >= 30 (10 IP) by the L3 builder, so
    short-cup-of-coffee pitcher seasons don't surface here.
    """
    rows = con.execute(
        """
        SELECT
            f.year, f.league_id, f.level_id,
            l.abbr            AS league_abbr,
            (f.year - EXTRACT(YEAR FROM pl.date_of_birth))::INTEGER AS age,
            CAST(f.outs AS BIGINT) AS outs,
            f.ip_display, f.fip, f.era_plus, f.pit_war, f.p_war, f.p_ra9_war,
            f.park_avg
        FROM f_player_season_advanced_pitching f
        LEFT JOIN leagues         l  ON l.league_id  = f.league_id
        LEFT JOIN players_current pl ON pl.player_id = f.player_id
        WHERE f.player_id = ?
        ORDER BY f.year, f.level_id, f.league_id
        """,
        [player_id],
    ).fetchall()
    out: list[PlayerAdvancedPitchingRow] = []
    for r in rows:
        (year, league_id, level_id, league_abbr, age, outs,
         ip_display, fip, era_plus, pit_war, p_war, p_ra9_war, park_avg) = r
        out.append(PlayerAdvancedPitchingRow(
            year=int(year),
            age=int(age) if age is not None else None,
            level_id=int(level_id),
            level_name=LEVEL_NAMES.get(int(level_id), f"L{level_id}"),
            league_id=int(league_id),
            league_abbr=league_abbr,
            outs=int(outs),
            ip_display=float(ip_display),
            fip=float(fip) if fip is not None else None,
            era_plus=int(era_plus) if era_plus is not None else None,
            pit_war=float(pit_war) if pit_war is not None else None,
            p_war=float(p_war) if p_war is not None else None,
            p_ra9_war=float(p_ra9_war) if p_ra9_war is not None else None,
            park_avg=float(park_avg) if park_avg is not None else None,
        ))
    return out


def _fetch_pitching_stints(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[dict[str, Any]]:
    """Return one dict per (year, league, level, team) pitching stint."""
    rows = con.execute(
        """
        SELECT
            p.year, p.league_id, p.level_id, p.team_id,
            t.abbr            AS team_abbr,
            t.nickname        AS team_nickname,
            l.abbr            AS league_abbr,
            (p.year - EXTRACT(YEAR FROM pl.date_of_birth))::INTEGER AS age,
            CAST(p.g    AS BIGINT) AS g,
            CAST(p.gs   AS BIGINT) AS gs,
            CAST(p.w    AS BIGINT) AS w,
            CAST(p.l    AS BIGINT) AS l,
            CAST(p.s    AS BIGINT) AS sv,
            CAST(p.outs AS BIGINT) AS outs,
            CAST(p.ha   AS BIGINT) AS h,
            CAST(p.r    AS BIGINT) AS r,
            CAST(p.er   AS BIGINT) AS er,
            CAST(p.hra  AS BIGINT) AS hr,
            CAST(p.bb   AS BIGINT) AS bb,
            CAST(p.k    AS BIGINT) AS so,
            CAST(p.bf   AS BIGINT) AS bf
        FROM f_player_season_pitching p
        LEFT JOIN teams   t  ON t.team_id   = p.team_id
        LEFT JOIN leagues l  ON l.league_id = p.league_id
        LEFT JOIN players_current pl ON pl.player_id = p.player_id
        WHERE p.player_id = ? AND p.split_id = 1
        ORDER BY p.year, p.level_id, t.abbr
        """,
        [player_id],
    ).fetchall()
    cols = [
        "year", "league_id", "level_id", "team_id",
        "team_abbr", "team_nickname", "league_abbr", "age",
        "g", "gs", "w", "l", "sv", "outs",
        "h", "r", "er", "hr", "bb", "so", "bf",
    ]
    return [dict(zip(cols, r, strict=True)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Stint → schema + season grouping
# ─────────────────────────────────────────────────────────────────────────────


def _batting_stint_from_dict(d: dict[str, Any], *, is_combined: bool = False) -> PlayerBattingStint:
    avg, obp, slg, ops = _slash_line(
        d["h"], d["ab"], d["bb"], d["hbp"], d["sf"],
        d["d"], d["t"], d["hr"],
    )
    team = None if is_combined else _team_ref(d)
    return PlayerBattingStint(
        year=int(d["year"]),
        age=int(d["age"]) if d.get("age") is not None else None,
        is_combined=is_combined,
        team=team,
        g=int(d["g"]), pa=int(d["pa"]), ab=int(d["ab"]),
        r=int(d["r"]), h=int(d["h"]),
        d=int(d["d"]), t=int(d["t"]), hr=int(d["hr"]),
        rbi=int(d["rbi"]), sb=int(d["sb"]), cs=int(d["cs"]),
        bb=int(d["bb"]), so=int(d["so"]),
        hbp=int(d["hbp"]), sf=int(d["sf"]),
        avg=avg, obp=obp, slg=slg, ops=ops,
    )


def _pitching_stint_from_dict(d: dict[str, Any], *, is_combined: bool = False) -> PlayerPitchingStint:
    era, whip, k9, bb9 = _pitch_rates(
        d["outs"], d["er"], d["h"], d["bb"], d["so"],
    )
    team = None if is_combined else _team_ref(d)
    return PlayerPitchingStint(
        year=int(d["year"]),
        age=int(d["age"]) if d.get("age") is not None else None,
        is_combined=is_combined,
        team=team,
        g=int(d["g"]), gs=int(d["gs"]),
        w=int(d["w"]), l=int(d["l"]), sv=int(d["sv"]),
        outs=int(d["outs"]),
        ip_display=_ip_display(int(d["outs"])),
        h=int(d["h"]), r=int(d["r"]), er=int(d["er"]),
        hr=int(d["hr"]), bb=int(d["bb"]), so=int(d["so"]),
        bf=int(d["bf"]),
        era=era, whip=whip, k_per_9=k9, bb_per_9=bb9,
    )


_BATTING_SUM_COLS = (
    "g", "pa", "ab", "r", "h", "d", "t", "hr", "rbi",
    "sb", "cs", "bb", "so", "hbp", "sf",
)
_PITCHING_SUM_COLS = (
    "g", "gs", "w", "l", "sv", "outs",
    "h", "r", "er", "hr", "bb", "so", "bf",
)


def _combine_rows(stints: list[dict[str, Any]], sum_cols: tuple[str, ...]) -> dict[str, Any]:
    """Synthesize a TOT row by SUMing counting cols across stints.

    Inherits `year` and `age` from the first stint (all stints in a
    season share both). Drops team/league/level identity — combined
    rows have no team. Rate stats are computed downstream from the
    summed counters.
    """
    if not stints:
        raise ValueError("cannot combine empty stints")
    first = stints[0]
    out: dict[str, Any] = {
        "year": first["year"],
        "age": first.get("age"),
        # combined rows have no team identity
        "team_id": None,
        "team_abbr": None,
        "team_nickname": None,
        "league_id": None,
        "league_abbr": None,
        "level_id": None,
    }
    for col in sum_cols:
        out[col] = sum(int(s[col]) for s in stints)
    return out


def _group_by_season(
    stints: list[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]]]]:
    """Group stint dicts by year, preserving stint order within each year."""
    by_year: dict[int, list[dict[str, Any]]] = {}
    for s in stints:
        by_year.setdefault(int(s["year"]), []).append(s)
    return sorted(by_year.items())


def _build_batting_seasons(stint_dicts: list[dict[str, Any]]) -> list[PlayerBattingSeason]:
    out: list[PlayerBattingSeason] = []
    for year, year_stints in _group_by_season(stint_dicts):
        stints_models = [_batting_stint_from_dict(s) for s in year_stints]
        if len(year_stints) > 1:
            combined_dict = _combine_rows(year_stints, _BATTING_SUM_COLS)
            combined_model = _batting_stint_from_dict(combined_dict, is_combined=True)
        else:
            combined_model = None
        out.append(PlayerBattingSeason(
            year=year,
            age=stints_models[0].age,
            stints=stints_models,
            combined=combined_model,
        ))
    return out


def _build_pitching_seasons(stint_dicts: list[dict[str, Any]]) -> list[PlayerPitchingSeason]:
    out: list[PlayerPitchingSeason] = []
    for year, year_stints in _group_by_season(stint_dicts):
        stints_models = [_pitching_stint_from_dict(s) for s in year_stints]
        if len(year_stints) > 1:
            combined_dict = _combine_rows(year_stints, _PITCHING_SUM_COLS)
            combined_model = _pitching_stint_from_dict(combined_dict, is_combined=True)
        else:
            combined_model = None
        out.append(PlayerPitchingSeason(
            year=year,
            age=stints_models[0].age,
            stints=stints_models,
            combined=combined_model,
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Career totals
# ─────────────────────────────────────────────────────────────────────────────


def _build_batting_career(stints: list[dict[str, Any]]) -> PlayerCareerBatting | None:
    """Sum counting stats across every batting stint, then derive slash line.

    Returns None when the player never accumulated batting stats.
    """
    if not stints:
        return None
    totals = {col: sum(int(s[col]) for s in stints) for col in _BATTING_SUM_COLS}
    avg, obp, slg, ops = _slash_line(
        totals["h"], totals["ab"], totals["bb"], totals["hbp"], totals["sf"],
        totals["d"], totals["t"], totals["hr"],
    )
    return PlayerCareerBatting(
        g=totals["g"], pa=totals["pa"], ab=totals["ab"],
        r=totals["r"], h=totals["h"],
        d=totals["d"], t=totals["t"], hr=totals["hr"],
        rbi=totals["rbi"], sb=totals["sb"], cs=totals["cs"],
        bb=totals["bb"], so=totals["so"],
        hbp=totals["hbp"], sf=totals["sf"],
        avg=avg, obp=obp, slg=slg, ops=ops,
    )


def _build_fielding_rows(rows: list[dict[str, Any]]) -> list[PlayerFieldingRow]:
    """Convert fetched dicts to PlayerFieldingRow models in fetch order.

    Fetch SQL already orders by (year, position, level, team), so the
    output reads top-to-bottom as a Bref-style flat fielding table.
    """
    out: list[PlayerFieldingRow] = []
    for r in rows:
        ip = int(r["ip"])
        ipf = int(r["ipf"])
        inn_outs = ip * 3 + ipf
        po, a, e = int(r["po"]), int(r["a"]), int(r["e"])
        position = int(r["position"])
        out.append(PlayerFieldingRow(
            year=int(r["year"]),
            age=int(r["age"]) if r.get("age") is not None else None,
            team=_team_ref(r),
            position=position,
            position_name=POSITION_NAMES.get(position, f"P{position}"),
            g=int(r["g"]),
            gs=int(r["gs"]),
            inn_outs=inn_outs,
            inn_display=_ip_display(inn_outs),
            po=po,
            a=a,
            e=e,
            dp=int(r["dp"]),
            fpct=_fpct(po, a, e),
        ))
    return out


_FIELDING_SUM_COLS = ("g", "gs", "po", "a", "e", "dp")


def _build_fielding_career(rows: list[dict[str, Any]]) -> list[PlayerCareerFielding]:
    """One career-rollup row per position. Sums G/GS/INN/PO/A/E/DP across years.

    Returns [] when the player has no fielding data. Career rows omit
    cross-position totals deliberately — see PlayerFieldingRow docstring
    for why combining across positions is semantically fraught.
    """
    if not rows:
        return []
    by_position: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_position.setdefault(int(r["position"]), []).append(r)
    out: list[PlayerCareerFielding] = []
    for position in sorted(by_position):
        pos_rows = by_position[position]
        totals = {col: sum(int(r[col]) for r in pos_rows) for col in _FIELDING_SUM_COLS}
        ip_total = sum(int(r["ip"]) for r in pos_rows)
        ipf_total = sum(int(r["ipf"]) for r in pos_rows)
        # ipf can sum past 3 if a player had multiple fractional-out
        # stints; normalize so display IP stays canonical.
        inn_outs = ip_total * 3 + ipf_total
        out.append(PlayerCareerFielding(
            position=position,
            position_name=POSITION_NAMES.get(position, f"P{position}"),
            g=totals["g"], gs=totals["gs"],
            inn_outs=inn_outs, inn_display=_ip_display(inn_outs),
            po=totals["po"], a=totals["a"], e=totals["e"], dp=totals["dp"],
            fpct=_fpct(totals["po"], totals["a"], totals["e"]),
        ))
    return out


def _fetch_position_fielding(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> list[PlayerPositionFielding]:
    """Per-position fielding cube from the latest snapshot.

    Pulls one ``players_fielding_current`` row, then unpivots the nine
    ``fielding_rating_pos1..9`` + ``_pot`` + ``fielding_experience1..9``
    triplets into a list of ``PlayerPositionFielding`` rows. Position
    indexing is 1-based (P/C/1B/2B/3B/SS/LF/CF/RF); the unused
    ``fielding_experience0`` column (DH-bucket / no-position) is
    intentionally not exposed.

    Zero values are normalized to ``None`` — OOTP encodes "never rated"
    / "never played there" as 0, and the UI wants an em-dash for those
    cells. A genuinely-zero rating doesn't exist on the 20-80 scale
    (the floor is 20), so the conversion is lossless.

    Always returns 9 rows, in position order (1..9). Frontends can
    re-sort by experience to surface the "where they actually play"
    view.
    """
    rating_cols = ", ".join(f"fielding_rating_pos{i}" for i in range(1, 10))
    pot_cols = ", ".join(f"fielding_rating_pos{i}_pot" for i in range(1, 10))
    exp_cols = ", ".join(f"fielding_experience{i}" for i in range(1, 10))
    row = con.execute(
        f"""
        SELECT {rating_cols}, {pot_cols}, {exp_cols}
        FROM players_fielding_current
        WHERE player_id = ?
        """,
        [player_id],
    ).fetchone()
    if row is None:
        # Player has no fielding-snapshot row in the latest dump
        # (retired / never on a roster / data gap). Surface as the
        # standard 9-row block with all-null fields so the frontend
        # always has a stable shape.
        return [
            PlayerPositionFielding(
                position=i,
                position_name=POSITION_NAMES.get(i, f"P{i}"),
                rating_current=None,
                rating_potential=None,
                experience=None,
            )
            for i in range(1, 10)
        ]

    out: list[PlayerPositionFielding] = []
    for i in range(1, 10):
        rating = row[i - 1]
        pot = row[9 + (i - 1)]
        exp = row[18 + (i - 1)]
        out.append(PlayerPositionFielding(
            position=i,
            position_name=POSITION_NAMES.get(i, f"P{i}"),
            rating_current=int(rating) if rating else None,
            rating_potential=int(pot) if pot else None,
            experience=int(exp) if exp else None,
        ))
    return out


# MLB credits exactly 172 days of service per full season-year. 6 full
# years (1,032 days) puts a player at free-agent eligibility.
_DAYS_PER_SERVICE_YEAR = 172
_DAYS_TO_FREE_AGENCY = 6 * _DAYS_PER_SERVICE_YEAR  # 1032


def _service_display(years: int, total_days: int) -> str:
    """Format MLB service as Bref-style "Xy Yd" (Y = days into current year).

    Convention matches MLBPA / Baseball-Reference — leftover_days =
    total_days - 172 * years. Examples:
        years=4, days=816  → "4y 128d"   (816 - 4*172 = 128)
        years=0, days=45   → "0y 45d"
        years=9, days=1576 → "9y 28d"    (1576 - 9*172 = 28)
    """
    leftover = total_days - _DAYS_PER_SERVICE_YEAR * years
    # Defensive: occasionally OOTP rounds slightly off — clamp to [0, 171]
    # so the display never reads 4y 173d (= 5y 1d).
    if leftover < 0:
        leftover = 0
    return f"{years}y {leftover}d"


def _service_class(total_days: int) -> tuple[str, str]:
    """Return (class_id, display_label) for the player's service time.

    Pre-arb / arb-eligible Y1-Y3 / FA-eligible. Boundaries at 3.000 and
    6.000 years (3 × 172 = 516 days; 6 × 172 = 1032 days) — Super-Two
    qualifiers (the early-arb edge case for high-service-day pre-arb
    players) are NOT modeled in v1; they're a separate convention OOTP
    handles internally and there's no public flag we surface.
    """
    if total_days < 3 * _DAYS_PER_SERVICE_YEAR:
        return ("pre_arb", "Pre-arb")
    if total_days < _DAYS_TO_FREE_AGENCY:
        # 3 arb-eligible years; 1 = first arb year.
        arb_year = (total_days // _DAYS_PER_SERVICE_YEAR) - 2  # 3y → 1, 4y → 2, 5y → 3
        if arb_year < 1:
            arb_year = 1
        if arb_year > 3:
            arb_year = 3
        return (f"arb_y{arb_year}", f"Arb (Y{arb_year})")
    return ("fa_eligible", "FA-eligible")


def _fetch_roster_status(
    con: duckdb.DuckDBPyConnection, player_id: int,
) -> PlayerRosterStatus | None:
    """Pull the latest roster_status row + format service-time fields.

    Returns None when the player has no row in the current snapshot
    (retired pre-save / never on a roster / data gap). The frontend
    uses the null to skip rendering the Service & Status block.
    """
    row = con.execute(
        """
        SELECT
            mlb_service_years,
            mlb_service_days,
            mlb_service_days_this_year,
            options_used,
            options_used_this_year,
            is_active,
            is_on_secondary,
            is_on_dl,
            is_on_dl60,
            designated_for_assignment,
            is_on_waivers
        FROM roster_status_current
        WHERE player_id = ?
        """,
        [player_id],
    ).fetchone()
    if row is None:
        return None

    (years, days, days_this_year, options, options_this_year,
     active, secondary, dl, dl60, dfa, waivers) = row
    years = int(years or 0)
    days = int(days or 0)
    days_this_year = int(days_this_year or 0)
    options = int(options or 0)

    klass, label = _service_class(days)
    days_to_fa = max(0, _DAYS_TO_FREE_AGENCY - days)
    options_remaining = max(0, 3 - options)

    return PlayerRosterStatus(
        mlb_service_years=years,
        mlb_service_days=days,
        mlb_service_days_this_year=days_this_year,
        service_display=_service_display(years, days),
        service_class=klass,
        service_class_label=label,
        days_to_free_agency=days_to_fa,
        is_free_agent_eligible=days >= _DAYS_TO_FREE_AGENCY,
        options_used=options,
        options_used_this_year=int(options_this_year or 0),
        options_remaining=options_remaining,
        is_active=bool(active),
        is_on_secondary=bool(secondary),
        is_on_dl=bool(dl),
        is_on_dl60=bool(dl60),
        designated_for_assignment=bool(dfa),
        is_on_waivers=bool(waivers),
    )


def _build_pitching_career(stints: list[dict[str, Any]]) -> PlayerCareerPitching | None:
    if not stints:
        return None
    totals = {col: sum(int(s[col]) for s in stints) for col in _PITCHING_SUM_COLS}
    era, whip, k9, bb9 = _pitch_rates(
        totals["outs"], totals["er"], totals["h"], totals["bb"], totals["so"],
    )
    return PlayerCareerPitching(
        g=totals["g"], gs=totals["gs"],
        w=totals["w"], l=totals["l"], sv=totals["sv"],
        outs=totals["outs"], ip_display=_ip_display(totals["outs"]),
        h=totals["h"], r=totals["r"], er=totals["er"],
        hr=totals["hr"], bb=totals["bb"], so=totals["so"],
        bf=totals["bf"],
        era=era, whip=whip, k_per_9=k9, bb_per_9=bb9,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Situational splits — backed by f_pa_event + players_current
# ─────────────────────────────────────────────────────────────────────────────
#
# `f_pa_event` is the multi-year per-PA log; we filter to regular season
# via the carried `game_type` column (=0 per `GameType.REGULAR_SEASON`).
# The split layer is a UNION ALL within the SQL — once per split label —
# so the row-builder gets a flat tabular result.
#
# Splits surfaced (8 total):
#   all          — every regular-season PA (parity row vs season totals).
#   risp         — `risp_flag` (runner on 2nd OR 3rd, outs<3).
#   risp_2out    — `risp_flag` AND `outs >= 2`.
#   late_close   — `late_close_flag` (7th+ inning AND OOTP "Close" flag —
#                  Bref-style "Late & Close" tying-run window).
#   bases_empty  — base1=0 AND base2=0 AND base3=0 (low-leverage baseline).
#   bases_loaded — base1>0 AND base2>0 AND base3>0 (max-leverage RBI chance).
#   vs_left      — opposing pitcher / batter is left-handed.
#                  Batter side: pitcher.throws=L (vs LHP).
#                  Pitcher side: effective batter hand = L (vs LHB), where
#                  switch-hitters (bats=3) bat opposite the pitcher's hand.
#   vs_right     — symmetric (vs RHP / vs RHB).
#
# OOTP's bare `close_flag` is intentionally unused as a split label: it
# fires on ~80% of MLB PAs, far too permissive to mean "clutch." The
# stricter `late_close_flag` is the right Bref analog.
#
# Multi-year coverage: `f_pa_event` is now sourced from L0 with cross-
# dump dedup (l2.py), so historical seasons are queryable. The fetcher
# returns one (year, level, split) row per actual sample; the UI groups
# them year-by-year.

# Display order — Bref-style reading order: leverage cluster
# (risp/2-out/late&close) → bases (empty/loaded) → platoon (vs L/R) →
# counts (first/2-strike/full) → spray (pull/cent/oppo). The "all"
# baseline anchors at the top.
_SITUATIONAL_SPLIT_ORDER: dict[str, int] = {
    "all":          0,
    "risp":         1,
    "risp_2out":    2,
    "late_close":   3,
    "bases_empty":  4,
    "bases_loaded": 5,
    "vs_left":      6,
    "vs_right":     7,
    "first_pitch":  8,
    "two_strike":   9,
    "full_count":  10,
    "pull":        11,
    "center":      12,
    "oppo":        13,
}

# Labels shared by both sides — leverage / bases / counts / spray
# clusters all read the same regardless of audience.
_SITUATIONAL_SPLIT_LABELS_SHARED: dict[str, str] = {
    "all":          "All",
    "risp":         "RISP",
    "risp_2out":    "RISP, 2 out",
    "late_close":   "Late & Close",
    "bases_empty":  "Bases empty",
    "bases_loaded": "Bases loaded",
    "first_pitch":  "First pitch",
    "two_strike":   "Two strikes",
    "full_count":   "Full count",
    "pull":         "Pull",
    "center":       "Center",
    "oppo":         "Opposite",
}

# Splits whose AVG / OBP / SLG denominators don't match the "All" row's
# (BIP-only filtering). The UI skips OPS-vs-baseline color coding for
# these so the user doesn't read meaningless "improvements."
_NEUTRAL_COLOR_SPLITS: frozenset[str] = frozenset({"pull", "center", "oppo"})

# Side-specific labels for the platoon splits — "vs LHP / vs RHP" reads
# naturally on the batter card; "vs LHB / vs RHB" on the pitcher card.
_SITUATIONAL_SPLIT_LABELS_BATTER: dict[str, str] = {
    "vs_left":  "vs LHP",
    "vs_right": "vs RHP",
}
_SITUATIONAL_SPLIT_LABELS_PITCHER: dict[str, str] = {
    "vs_left":  "vs LHB",
    "vs_right": "vs RHB",
}


def _split_label_for(split: str, side: str) -> str:
    """Resolve a split id to its display label, with platoon labels
    side-aware so the batter card says "vs LHP" and the pitcher card
    says "vs LHB"."""
    if split in _SITUATIONAL_SPLIT_LABELS_SHARED:
        return _SITUATIONAL_SPLIT_LABELS_SHARED[split]
    table = (
        _SITUATIONAL_SPLIT_LABELS_BATTER if side == "batter"
        else _SITUATIONAL_SPLIT_LABELS_PITCHER
    )
    return table.get(split, split)


# Counting-stat aggregation — same shape across all splits, so we
# define it once and reuse via a CTE. `result` codes per AtBatResult:
# 1=K, 2=BB, 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR, 10=HBP, 11=CI.
# AB = K + outs + hits, with sacrifices excluded (sac=1).
# SF (sac fly) = sac=1 AND result=5 (fly out flagged sacrifice).
def _situational_query(side: str) -> str:
    """Render the situational SQL for one side of the PA.

    ``side`` is ``"batter"`` or ``"pitcher"``. The two queries are
    identical except for (a) the join column on ``f_pa_event``
    (``batter_id`` vs ``pitcher_id``) and (b) the platoon-split
    filters — for the batter card "vs L/R" reads off the opposing
    pitcher's throwing hand; for the pitcher card it reads off the
    effective batter hand (with switch-hitters resolved against the
    pitcher's throwing hand). Aggregation (PA, AB, H, slash) is
    symmetric — for the pitcher view, the slash line reflects what
    the player allowed.
    """
    if side not in ("batter", "pitcher"):
        raise ValueError(f"side must be 'batter' or 'pitcher', got {side!r}")
    join_col = "batter_id" if side == "batter" else "pitcher_id"
    if side == "batter":
        # vs LHP / vs RHP — opposing pitcher's throwing hand
        vs_left_filter = "pitcher_throw_hand = 'L'"
        vs_right_filter = "pitcher_throw_hand = 'R'"
    else:
        # vs LHB / vs RHB — effective bat hand (switch-resolved)
        vs_left_filter = "effective_bat_hand = 'L'"
        vs_right_filter = "effective_bat_hand = 'R'"
    return _SITUATIONAL_QUERY_TEMPLATE.format(
        join_col=join_col,
        vs_left_filter=vs_left_filter,
        vs_right_filter=vs_right_filter,
    )


# Handedness codes per `players_current`:
#   bats:   1=R, 2=L, 3=S(witch)
#   throws: 1=R, 2=L  (no switch pitchers in this save's data)
#
# `effective_bat_hand`: hand the batter actually used in this PA. For
# non-switch batters, their preferred bats. For switch (bats=3), the
# opposite of the pitcher's throwing hand. NULL when handedness is
# missing in `players_current` (rare — handles edge cases gracefully).
#
# `balls`/`strikes`: count BEFORE the resolving pitch (i.e., 0-0 = PA
# resolved on first pitch; 3-2 = full count when resolved). 4-balls
# walks show as `balls=3`; strike-3 punchouts as `strikes=2`.
#
# `spray_direction` (BIP only, null otherwise): naive bins over
# `hit_xy` per DATA_NOTES "hit_xy spray decode". `hit_xy` is a 16×16
# packed coord, `x = hit_xy / 16`. **Empirically batter-relative**
# (verified 2026-05-12 via MLB-2029 HR distribution: mean hit_xy ≈ 71
# for BOTH LHB and RHB HRs — same pull-side band for both hands; if
# hit_xy were field-absolute the means would diverge). So:
#   x ≤ 5  (hit_xy ≤ 95)  → pull
#   6..9   (96..159)      → center
#   x ≥ 10 (160..255)     → oppo
# applied uniformly regardless of bat hand. Edges (`hit_xy=0`) and
# rows missing handedness fall through to NULL → excluded from spray
# splits. Magnitudes are approximate vs OOTP's IE values (audit
# E-tier), but the direction split is reliable.
_SITUATIONAL_QUERY_TEMPLATE = """
WITH base AS (
    SELECT
        pa.year, pa.level_id,
        pa.result, pa.sac,
        pa.risp_flag, pa.late_close_flag, pa.outs,
        pa.base1, pa.base2, pa.base3,
        pa.balls, pa.strikes,
        pa.bip_flag, pa.hit_xy,
        CASE p_p.throws WHEN 1 THEN 'R' WHEN 2 THEN 'L' END
            AS pitcher_throw_hand,
        CASE
            WHEN p_b.bats = 1 THEN 'R'
            WHEN p_b.bats = 2 THEN 'L'
            WHEN p_b.bats = 3 THEN
                CASE p_p.throws WHEN 1 THEN 'L' WHEN 2 THEN 'R' END
        END AS effective_bat_hand
    FROM f_pa_event pa
    LEFT JOIN players_current p_b ON p_b.player_id = pa.batter_id
    LEFT JOIN players_current p_p ON p_p.player_id = pa.pitcher_id
    WHERE pa.{join_col} = ?
      AND pa.game_type = 0  -- regular season; matches f_player_season_*
),
base_spray AS (
    SELECT *,
        CASE
            WHEN NOT bip_flag OR hit_xy = 0 THEN NULL
            -- hit_xy is batter-relative (verified empirically):
            -- low x = pull regardless of hand, high x = oppo
            -- regardless of hand. So no handedness branching here.
            WHEN hit_xy / 16 <= 5  THEN 'pull'
            WHEN hit_xy / 16 <= 9  THEN 'center'
            ELSE 'oppo'
        END AS spray_direction
    FROM base
),
splits AS (
    SELECT *, 'all' AS split          FROM base_spray
    UNION ALL
    SELECT *, 'risp' AS split         FROM base_spray WHERE risp_flag
    UNION ALL
    SELECT *, 'risp_2out' AS split    FROM base_spray WHERE risp_flag AND outs >= 2
    UNION ALL
    SELECT *, 'late_close' AS split   FROM base_spray WHERE late_close_flag
    UNION ALL
    SELECT *, 'bases_empty' AS split  FROM base_spray
        WHERE base1 = 0 AND base2 = 0 AND base3 = 0
    UNION ALL
    SELECT *, 'bases_loaded' AS split FROM base_spray
        WHERE base1 > 0 AND base2 > 0 AND base3 > 0
    UNION ALL
    SELECT *, 'vs_left' AS split      FROM base_spray WHERE {vs_left_filter}
    UNION ALL
    SELECT *, 'vs_right' AS split     FROM base_spray WHERE {vs_right_filter}
    -- Counts (count BEFORE the resolving pitch — 0-0 = first-pitch
    -- result, 3-2 = full count when resolved).
    UNION ALL
    SELECT *, 'first_pitch' AS split  FROM base_spray
        WHERE balls = 0 AND strikes = 0
    UNION ALL
    SELECT *, 'two_strike' AS split   FROM base_spray
        WHERE strikes = 2
    UNION ALL
    SELECT *, 'full_count' AS split   FROM base_spray
        WHERE balls = 3 AND strikes = 2
    -- Spray (BIP only; null spray_direction excluded by NOT NULL).
    UNION ALL
    SELECT *, 'pull' AS split         FROM base_spray WHERE spray_direction = 'pull'
    UNION ALL
    SELECT *, 'center' AS split       FROM base_spray WHERE spray_direction = 'center'
    UNION ALL
    SELECT *, 'oppo' AS split         FROM base_spray WHERE spray_direction = 'oppo'
)
SELECT
    year, level_id, split,
    COUNT(*)                                                              AS pa,
    SUM(CASE WHEN result IN (1,4,5,6,7,8,9) AND sac=0 THEN 1 ELSE 0 END)  AS ab,
    SUM(CASE WHEN result IN (6,7,8,9) THEN 1 ELSE 0 END)                  AS h,
    SUM(CASE WHEN result = 7 THEN 1 ELSE 0 END)                           AS doubles,
    SUM(CASE WHEN result = 8 THEN 1 ELSE 0 END)                           AS triples,
    SUM(CASE WHEN result = 9 THEN 1 ELSE 0 END)                           AS hr,
    SUM(CASE WHEN result = 2 THEN 1 ELSE 0 END)                           AS bb,
    SUM(CASE WHEN result = 1 THEN 1 ELSE 0 END)                           AS k,
    SUM(CASE WHEN result = 10 THEN 1 ELSE 0 END)                          AS hbp,
    SUM(CASE WHEN sac = 1 AND result = 5 THEN 1 ELSE 0 END)               AS sf
FROM splits
GROUP BY year, level_id, split
HAVING COUNT(*) > 0
ORDER BY year DESC, level_id, split
"""


def _situational_slash(
    ab: int, h: int, doubles: int, triples: int, hr: int,
    bb: int, hbp: int, sf: int,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute (AVG, OBP, SLG, OPS) — None when denominator is zero.

    Bref convention: OBP denom includes SF but NOT SH (sac bunts);
    SLG denom is plain AB. Total bases collapse cleanly to
    H + 2B + 2*3B + 3*HR.
    """
    avg = h / ab if ab > 0 else None
    obp_den = ab + bb + hbp + sf
    obp = (h + bb + hbp) / obp_den if obp_den > 0 else None
    tb = h + doubles + 2 * triples + 3 * hr
    slg = tb / ab if ab > 0 else None
    ops = (obp + slg) if (obp is not None and slg is not None) else None
    return avg, obp, slg, ops


def _fetch_situational(
    con: duckdb.DuckDBPyConnection, player_id: int, side: str,
) -> list[PlayerSituationalRow]:
    """Per-(year, level, split) regular-season situational stats.

    ``side`` selects which dimension of the PA to filter on:

    - ``"batter"`` — keyed on ``f_pa_event.batter_id``. Returns the
      player's hitting splits. Empty for pitchers (no batter PAs)
      and pre-warehouse-history imports (no per-PA log).
    - ``"pitcher"`` — keyed on ``f_pa_event.pitcher_id``. Returns
      the splits for what hitters did against this player. Empty
      for position players who never took the mound.
    """
    rows = con.execute(_situational_query(side), [player_id]).fetchall()
    out: list[PlayerSituationalRow] = []
    for r in rows:
        (year, level_id, split, pa, ab, h, doubles, triples, hr,
         bb, k, hbp, sf) = r
        avg, obp, slg, ops = _situational_slash(
            int(ab), int(h), int(doubles), int(triples), int(hr),
            int(bb), int(hbp), int(sf),
        )
        out.append(
            PlayerSituationalRow(
                year=int(year),
                level_id=int(level_id) if level_id is not None else 0,
                level_name=(
                    LEVEL_NAMES.get(int(level_id))
                    if level_id is not None else None
                ),
                split=str(split),
                split_label=_split_label_for(str(split), side),
                pa=int(pa),
                ab=int(ab),
                h=int(h),
                doubles=int(doubles),
                triples=int(triples),
                hr=int(hr),
                bb=int(bb),
                k=int(k),
                hbp=int(hbp),
                sf=int(sf),
                avg=avg,
                obp=obp,
                slg=slg,
                ops=ops,
            )
        )

    # Re-sort with the canonical split order — the SQL ORDER BY uses
    # alphabetic on `split` which puts late_close → risp → risp_2out
    # which is wrong for display.
    out.sort(
        key=lambda r: (
            -r.year,                     # year DESC
            r.level_id,                  # MLB (1) first
            _SITUATIONAL_SPLIT_ORDER.get(r.split, 99),
        )
    )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Route
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/players/{player_id}", response_model=PlayerResponse)
def get_player(
    player_id: int,
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> PlayerResponse:
    """Full player payload — bio + per-season batting + per-season pitching.

    404 when no player matches `player_id`. Empty season lists when the
    player has no stats of that type — the frontend uses the empty state
    to skip rendering the corresponding subsection.
    """
    bio = _build_bio(con, player_id)
    if bio is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown player_id: {player_id}. "
                   "Try a different id, or check that the warehouse contains this player.",
        )
    bat_stints = _fetch_batting_stints(con, player_id)
    pit_stints = _fetch_pitching_stints(con, player_id)
    fld_rows = _fetch_fielding_rows(con, player_id)
    advanced_bat = _fetch_advanced_batting(con, player_id)
    advanced_pit = _fetch_advanced_pitching(con, player_id)
    position_fielding = _fetch_position_fielding(con, player_id)
    roster_status = _fetch_roster_status(con, player_id)
    situational_batting = _fetch_situational(con, player_id, "batter")
    situational_pitching = _fetch_situational(con, player_id, "pitcher")
    return PlayerResponse(
        bio=bio,
        batting_seasons=_build_batting_seasons(bat_stints),
        pitching_seasons=_build_pitching_seasons(pit_stints),
        fielding_rows=_build_fielding_rows(fld_rows),
        advanced_batting=advanced_bat,
        advanced_pitching=advanced_pit,
        batting_career=_build_batting_career(bat_stints),
        pitching_career=_build_pitching_career(pit_stints),
        fielding_career=_build_fielding_career(fld_rows),
        position_fielding=position_fielding,
        roster_status=roster_status,
        situational_batting=situational_batting,
        situational_pitching=situational_pitching,
    )
