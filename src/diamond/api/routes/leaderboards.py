"""Custom leaderboards endpoint — backs `/explore/leaderboards`.

Endpoints:
- ``GET /api/leaderboards/options`` — list of supported stats
  for the picker dropdown. Grouped client-side by `discipline`.
- ``GET /api/leaderboards?stat=&year=&league_id=&level_id=&pa_min=&limit=&order=``
  — single-stat ranked list. Defaults are MLB-level + latest year +
  PA/IP/BIP minimum from the stat spec.

Design notes:

- Stat catalog is a static dict of ``StatSpec`` records. Each maps a
  glossary id (``HR`` / ``OPS_plus`` / ``ERA`` / ...) to a source
  table + value expression + qualifier expression + default minimum.
  The picker UI never offers a stat that isn't in this catalog, so
  the route can assume ``stat`` is always valid (returns 400 otherwise).
- Per-(player, year, level) aggregation always happens in a CTE — even
  for the advanced tables (which are already pre-aggregated to that
  grain). Keeps the SQL shape uniform across counting / advanced /
  Statcast stats.
- Dominant-team resolution: for counting stats we GROUP BY across
  stints and pick the team with the most PA / outs as the displayed
  team_abbr. Single-stint players get their lone team. Advanced
  tables are already at the (player, year, league, level) grain so
  we re-use the dominant-team subquery approach for the team_abbr.
- ``order`` (asc/desc) is fixed by the stat spec — we don't allow
  flipping ERA to descending, since that would surface garbage data
  (the worst pitcher's ERA, weighted by minimum-IP qualifier).
- League filter: omitted = include all leagues at this level. We do
  NOT default to a single MLB league (203) because the user might
  reasonably want "all of AAA" or "all minors". The `level_id` filter
  is the primary scoping knob; `league_id` is optional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from diamond.api.schemas import (
    LeaderboardOption,
    LeaderboardOptionsResponse,
    LeaderboardResponse,
    LeaderboardRow,
    LeaderboardStatSpec,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Stat catalog
#
# Each entry maps a glossary id to its SQL plumbing. `value_expr` is the
# aggregate expression — "SUM(hr)" for counting, "AVG(woba)" for already-
# aggregated advanced tables (woba is already weighted), or a derived
# rate like "SUM(h)::DOUBLE / NULLIF(SUM(ab), 0)". `qualifier_expr` is
# the gating volume metric — PA for batting, outs for pitching, BIP for
# Statcast.
# ─────────────────────────────────────────────────────────────────────────────


_QualifierLabel = Literal["PA", "IP", "BIP"]


@dataclass(frozen=True)
class StatSpec:
    """SQL plumbing for one leaderboard stat."""

    id: str
    label: str
    discipline: str  # "batting" | "pitching" | "statcast_b" | "statcast_p"
    table: str
    value_expr: str
    qualifier_expr: str
    qualifier_label: _QualifierLabel
    default_min: int
    direction: Literal["desc", "asc"]
    decimals: int


_BAT = "f_player_season_batting"
_PIT = "f_player_season_pitching"
_ABAT = "f_player_season_advanced_batting"
_APIT = "f_player_season_advanced_pitching"
_SBAT = "f_player_season_statcast_batting"
_SPIT = "f_player_season_statcast_pitching"
# 2026-05-14: _XPIT re-introduced for pitching xBA + xSLG re-enable
# (96/97% IE-match; over D41 bar). _XBAT stays dropped — batting xstats
# are 89-92% match, still under threshold; awaiting per-player
# calibration in Phase 4b.
_XPIT = "f_player_season_xstats_pitching"
_LBAT = "f_player_season_leverage_batting"
_LPIT = "f_player_season_leverage_pitching"


# Whitelist — only stats listed here are leaderboardable. Adding a new
# stat = add a row here + (optionally) a glossary entry.
LEADERBOARD_STATS: dict[str, StatSpec] = {
    # ── Batting counting ────────────────────────────────────────────
    "HR":    StatSpec("HR",    "HR",    "batting", _BAT, "SUM(hr)",  "SUM(pa)", "PA", 100, "desc", 0),
    "RBI":   StatSpec("RBI",   "RBI",   "batting", _BAT, "SUM(rbi)", "SUM(pa)", "PA", 100, "desc", 0),
    "R":     StatSpec("R",     "R",     "batting", _BAT, "SUM(r)",   "SUM(pa)", "PA", 100, "desc", 0),
    "H":     StatSpec("H",     "H",     "batting", _BAT, "SUM(h)",   "SUM(pa)", "PA", 100, "desc", 0),
    "SB":    StatSpec("SB",    "SB",    "batting", _BAT, "SUM(sb)",  "SUM(pa)", "PA", 100, "desc", 0),
    "BB":    StatSpec("BB",    "BB",    "batting", _BAT, "SUM(bb)",  "SUM(pa)", "PA", 100, "desc", 0),
    # ── Batting rate (derived) ──────────────────────────────────────
    "AVG":   StatSpec(
        "AVG", "AVG", "batting", _BAT,
        "ROUND(SUM(h)::DOUBLE / NULLIF(SUM(ab), 0), 3)",
        "SUM(pa)", "PA", 300, "desc", 3,
    ),
    "OBP":   StatSpec(
        "OBP", "OBP", "batting", _BAT,
        "ROUND((SUM(h)+SUM(bb)+SUM(hp))::DOUBLE "
        "/ NULLIF(SUM(ab)+SUM(bb)+SUM(hp)+SUM(sf), 0), 3)",
        "SUM(pa)", "PA", 300, "desc", 3,
    ),
    "SLG":   StatSpec(
        "SLG", "SLG", "batting", _BAT,
        "ROUND((SUM(h)+SUM(d)+2*SUM(t)+3*SUM(hr))::DOUBLE / NULLIF(SUM(ab), 0), 3)",
        "SUM(pa)", "PA", 300, "desc", 3,
    ),
    "OPS":   StatSpec(
        "OPS", "OPS", "batting", _BAT,
        "ROUND("
        "  (SUM(h)+SUM(bb)+SUM(hp))::DOUBLE "
        "    / NULLIF(SUM(ab)+SUM(bb)+SUM(hp)+SUM(sf), 0)"
        "  + (SUM(h)+SUM(d)+2*SUM(t)+3*SUM(hr))::DOUBLE / NULLIF(SUM(ab), 0)"
        ", 3)",
        "SUM(pa)", "PA", 300, "desc", 3,
    ),
    # ── Batting advanced ────────────────────────────────────────────
    # Advanced table is already at (player, year, league, level) grain
    # — there's exactly one row per player, so SUM() / MAX() collapse to
    # the same scalar. We use MAX() to express "this is the row's value".
    "wOBA":     StatSpec("wOBA",     "wOBA",   "batting", _ABAT, "MAX(woba)",     "MAX(pa)", "PA", 300, "desc", 3),
    "wRC_plus": StatSpec("wRC_plus", "wRC+",   "batting", _ABAT, "MAX(wrc_plus)", "MAX(pa)", "PA", 300, "desc", 0),
    "OPS_plus": StatSpec("OPS_plus", "OPS+",   "batting", _ABAT, "MAX(ops_plus)", "MAX(pa)", "PA", 300, "desc", 0),
    "wRAA":     StatSpec("wRAA",     "wRAA",   "batting", _ABAT, "MAX(wraa)",     "MAX(pa)", "PA", 100, "desc", 1),
    "bWAR":     StatSpec("bWAR",     "bWAR",   "batting", _ABAT, "MAX(b_war)",    "MAX(pa)", "PA", 100, "desc", 1),
    "oWAR":     StatSpec("oWAR",     "oWAR",   "batting", _ABAT, "MAX(o_war)",    "MAX(pa)", "PA", 100, "desc", 1),
    # ── Pitching counting / rate ────────────────────────────────────
    "K_pitcher": StatSpec(
        "K_pitcher", "K", "pitching", _PIT, "SUM(k)", "SUM(outs)", "IP", 300, "desc", 0,
    ),
    "W": StatSpec("W", "W", "pitching", _PIT, "SUM(w)", "SUM(outs)", "IP", 300, "desc", 0),
    "SV": StatSpec("SV", "SV", "pitching", _PIT, "SUM(sv)", "SUM(outs)", "IP", 90, "desc", 0),
    "ERA": StatSpec(
        "ERA", "ERA", "pitching", _PIT,
        "ROUND(9.0 * SUM(er)::DOUBLE / NULLIF(SUM(outs)/3.0, 0), 2)",
        "SUM(outs)", "IP", 300, "asc", 2,
    ),
    "WHIP": StatSpec(
        "WHIP", "WHIP", "pitching", _PIT,
        "ROUND((SUM(ha)+SUM(bb))::DOUBLE / NULLIF(SUM(outs)/3.0, 0), 3)",
        "SUM(outs)", "IP", 300, "asc", 3,
    ),
    # ── Pitching advanced ───────────────────────────────────────────
    "FIP":      StatSpec("FIP",      "FIP",    "pitching", _APIT, "MAX(fip)",      "MAX(outs)", "IP", 300, "asc",  2),
    "SIERA":    StatSpec("SIERA",    "SIERA",  "pitching", _APIT, "MAX(siera)",    "MAX(outs)", "IP", 300, "asc",  2),
    "ERA_plus": StatSpec("ERA_plus", "ERA+",   "pitching", _APIT, "MAX(era_plus)", "MAX(outs)", "IP", 300, "desc", 0),
    "pWAR":     StatSpec("pWAR",     "pWAR",   "pitching", _APIT, "MAX(p_war)",    "MAX(outs)", "IP", 100, "desc", 1),
    "RA9_WAR":  StatSpec("RA9_WAR",  "RA9-WAR","pitching", _APIT, "MAX(p_ra9_war)","MAX(outs)", "IP", 100, "desc", 1),
    "pit_WAR":  StatSpec("pit_WAR",  "pit_WAR","pitching", _APIT, "MAX(pit_war)",  "MAX(outs)", "IP", 100, "desc", 1),
    # ── Pitching x-stats (Phase 4a-ext-1 calibration; 2026-05-14 re-enable) ──
    # xBA + xSLG restored: 96% / 97% IE match (over D41's 95% bar). Sourced
    # from `f_player_season_xstats_pitching` (scaled SUM/AB values). On the
    # player page these route through L_IE for bit-for-bit OOTP match on
    # the org roster; here in the leaderboards we expose the L3 derivation
    # at 96-97% rounding-grade match. xwOBA (82%) + xERA (87%) stay deferred
    # until per-player calibration (Phase 4b) clears the bar.
    "xBA_pit":  StatSpec("xBA_pit",  "xBA",    "pitching", _XPIT, "MAX(xba)",  "MAX(bip_xstat)", "BIP", 30, "asc", 3),
    "xSLG_pit": StatSpec("xSLG_pit", "xSLG",   "pitching", _XPIT, "MAX(xslg)", "MAX(bip_xstat)", "BIP", 30, "asc", 3),
    # ── Statcast ────────────────────────────────────────────────────
    # Phase 4a-extended-3 (2026-05-10) dropped AVG_EV (83-87% IE match),
    # BARREL_PCT (74% batting), SWEET_SPOT_PCT (no IE counterpart),
    # xwOBA/xBA/xSLG (per-BIP averages don't match IE display). Max_EV
    # (97%) + HARD_HIT_PCT (94-95%) survive as rounding-grade matches.
    "MAX_EV":         StatSpec("MAX_EV",         "Max EV",  "statcast_b", _SBAT, "MAX(max_ev)",         "MAX(bip)", "BIP", 30, "desc", 1),
    "HARD_HIT_PCT":   StatSpec("HARD_HIT_PCT",   "HardHit%","statcast_b", _SBAT, "MAX(hard_hit_pct)",   "MAX(bip)", "BIP", 30, "desc", 1),
    # ── Leverage (Slice A — WPA from L0, RE24 from lref_re288_table) ──
    # Batter side: WPA + RE24. Pitcher side: WPA + LI + RE24-against + Clutch.
    # Leverage tables are at (player, year, league, level) grain; one row
    # per player → MAX(...) collapses to the scalar value just like advanced.
    "WPA":       StatSpec("WPA",       "WPA",       "batting",  _LBAT, "MAX(wpa)",    "MAX(pa)", "PA", 100, "desc", 2),
    "RE24":      StatSpec("RE24",      "RE24",      "batting",  _LBAT, "MAX(re24)",   "MAX(pa)", "PA", 100, "desc", 1),
    "WPA_pit":   StatSpec("WPA_pit",   "WPA",       "pitching", _LPIT, "MAX(wpa)",    "MAX(bf)", "PA", 200, "desc", 2),
    "LI":        StatSpec("LI",        "LI",        "pitching", _LPIT, "MAX(li)",     "MAX(bf)", "PA", 100, "desc", 3),
    "Clutch":    StatSpec("Clutch",    "Clutch",    "pitching", _LPIT, "MAX(clutch)", "MAX(bf)", "PA", 200, "desc", 2),
    "RE24_pit":  StatSpec("RE24_pit",  "RE24-vs",   "pitching", _LPIT, "MAX(re24)",   "MAX(bf)", "PA", 200, "desc", 1),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _latest_year_with_data(con: duckdb.DuckDBPyConnection, level_id: int) -> int:
    """The most recent year with at least one batting row at this level.

    Used to resolve ``year=None`` requests. We pick batting because every
    level has batting rows; pitching exists in fewer minor leagues.
    """
    row = con.execute(
        f"""
        SELECT MAX(year) FROM {_BAT}
        WHERE level_id = ? AND split_id = 1
        """,
        [level_id],
    ).fetchone()
    if row is None or row[0] is None:
        # Defensive — shouldn't happen on a healthy save.
        return 2026
    return int(row[0])


def _build_query(
    spec: StatSpec,
    *,
    year: int,
    level_id: int,
    league_id: int | None,
    qualifier_min: int,
    limit: int,
) -> tuple[str, list[object]]:
    """Build the leaderboard SQL + parameter list for `spec`.

    Aggregates across stints at the (player, year, league, level)
    grain, joins to dominant-team-by-PA/outs for the team_abbr, and
    ranks by `spec.value_expr` in the configured direction.
    """
    league_filter = "AND league_id = ?" if league_id is not None else ""
    league_args: list[object] = [league_id] if league_id is not None else []

    # `split_id` only exists on the counting tables (f_player_season_batting /
    # _pitching). The advanced + Statcast tables are already filtered to
    # split_id=1 at L3 build time, and don't carry the column. Gate the
    # filter on the source table.
    base_split_filter = (
        "AND split_id = 1" if spec.table in (_BAT, _PIT) else ""
    )

    # Dominant team — most-PA (batting) or most-outs (pitching) at this level.
    # Always sourced from the counting tables (which DO have split_id), so
    # team_abbr stays consistent with the player's actual stints regardless
    # of which advanced/Statcast table provided the headline value.
    dominant_source = _PIT if spec.discipline.startswith("pitching") else _BAT
    dominant_qualifier = "outs" if spec.discipline.startswith("pitching") else "pa"

    sql = f"""
    WITH base AS (
        SELECT
            player_id, year, league_id, level_id,
            {spec.value_expr}     AS value,
            {spec.qualifier_expr} AS qualifier_value
        FROM {spec.table}
        WHERE year = ? AND level_id = ?
              {base_split_filter}
              {league_filter}
        GROUP BY player_id, year, league_id, level_id
        HAVING {spec.qualifier_expr} >= ?
    ),
    dominant_team AS (
        SELECT player_id, year, league_id, level_id, team_id
        FROM (
            SELECT player_id, year, league_id, level_id, team_id, {dominant_qualifier},
                   ROW_NUMBER() OVER (
                       PARTITION BY player_id, year, league_id, level_id
                       ORDER BY {dominant_qualifier} DESC, team_id ASC
                   ) AS rn
            FROM {dominant_source}
            WHERE year = ? AND level_id = ? AND split_id = 1 {league_filter}
        ) WHERE rn = 1
    ),
    ranked AS (
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY value {"DESC" if spec.direction == "desc" else "ASC"} NULLS LAST,
                         qualifier_value DESC,
                         player_id ASC
            ) AS rank,
            b.player_id, b.year, b.league_id, b.level_id, b.value, b.qualifier_value,
            dt.team_id
        FROM base b
        LEFT JOIN dominant_team dt USING (player_id, year, league_id, level_id)
    )
    SELECT
        r.rank, r.player_id, r.year, r.league_id, r.level_id,
        p.first_name || ' ' || p.last_name AS player_name,
        r.team_id, t.abbr AS team_abbr,
        r.value, r.qualifier_value
    FROM ranked r
    LEFT JOIN players_current p ON p.player_id = r.player_id
    LEFT JOIN teams t           ON t.team_id  = r.team_id
    ORDER BY r.rank
    LIMIT ?
    """

    args: list[object] = [year, level_id, *league_args, qualifier_min]  # base
    args += [year, level_id, *league_args]                              # dominant_team
    args += [limit]
    return sql, args


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/leaderboards/options", response_model=LeaderboardOptionsResponse)
def get_leaderboard_options() -> LeaderboardOptionsResponse:
    """List of supported leaderboard stats — used to build the picker."""
    return LeaderboardOptionsResponse(
        options=[
            LeaderboardOption(
                id=spec.id,
                label=spec.label,
                discipline=spec.discipline,
                direction=spec.direction,
                decimals=spec.decimals,
                default_min=spec.default_min,
                qualifier_label=spec.qualifier_label,
            )
            for spec in LEADERBOARD_STATS.values()
        ]
    )


@router.get("/leaderboards", response_model=LeaderboardResponse)
def get_leaderboard(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    stat: Annotated[str, Query(description="Stat id (one of LEADERBOARD_STATS keys)")],
    year: Annotated[int | None, Query(description="Single year; latest if omitted")] = None,
    level_id: Annotated[int, Query(description="Level (1 = MLB)")] = 1,
    league_id: Annotated[int | None, Query(description="Optional league filter")] = None,
    pa_min: Annotated[
        int | None, Query(description="Qualifier minimum override (PA / IP-outs / BIP)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LeaderboardResponse:
    """One ranked leaderboard for a single stat + year + level.

    Returns the top ``limit`` rows by the stat's natural direction.
    The frontend can client-side re-sort via TanStack Table without a
    refetch — the row set is fixed but column order is fluid.
    """
    spec = LEADERBOARD_STATS.get(stat)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown stat id '{stat}'. "
                f"Supported: {', '.join(sorted(LEADERBOARD_STATS))}"
            ),
        )

    resolved_year = year if year is not None else _latest_year_with_data(cursor, level_id)
    qualifier_min = pa_min if pa_min is not None else spec.default_min

    sql, args = _build_query(
        spec,
        year=resolved_year,
        level_id=level_id,
        league_id=league_id,
        qualifier_min=qualifier_min,
        limit=limit,
    )
    raw = cursor.execute(sql, args).fetchall()

    rows: list[LeaderboardRow] = []
    for r in raw:
        (rank, player_id, row_year, row_league_id, row_level_id,
         player_name, team_id, team_abbr, value, qualifier_value) = r
        rows.append(
            LeaderboardRow(
                rank=int(rank),
                player_id=int(player_id),
                player_name=player_name or f"#{player_id}",
                team_id=int(team_id) if team_id is not None else None,
                team_abbr=team_abbr,
                league_id=int(row_league_id) if row_league_id is not None else None,
                level_id=int(row_level_id) if row_level_id is not None else None,
                year=int(row_year) if row_year is not None else None,
                value=float(value) if value is not None else None,
                qualifier_value=int(qualifier_value or 0),
            )
        )

    return LeaderboardResponse(
        stat=LeaderboardStatSpec(
            id=spec.id,
            label=spec.label,
            discipline=spec.discipline,
            direction=spec.direction,
            decimals=spec.decimals,
        ),
        year=resolved_year,
        level_id=level_id,
        league_id=league_id,
        pa_min=qualifier_min,
        qualifier_label=spec.qualifier_label,
        rows=rows,
    )
