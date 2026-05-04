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
    PlayerBattingSeason,
    PlayerBattingStint,
    PlayerBio,
    PlayerCareerBatting,
    PlayerCareerFielding,
    PlayerCareerPitching,
    PlayerFieldingRow,
    PlayerPitchingSeason,
    PlayerPitchingStint,
    PlayerResponse,
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
    return PlayerResponse(
        bio=bio,
        batting_seasons=_build_batting_seasons(bat_stints),
        pitching_seasons=_build_pitching_seasons(pit_stints),
        fielding_rows=_build_fielding_rows(fld_rows),
        batting_career=_build_batting_career(bat_stints),
        pitching_career=_build_pitching_career(pit_stints),
        fielding_career=_build_fielding_career(fld_rows),
    )
