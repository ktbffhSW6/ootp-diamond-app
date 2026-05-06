"""Movement-ledger endpoint — backs the ``/movements`` page.

Endpoint:
- ``GET /api/movements?year=YYYY`` — every intra-org promotion +
  demotion within the active save's user-team org for the given
  season, with before/after performance and a verdict glyph.

Defaults: ``year`` = latest year with any movement data. The user's
org is derived from the active ``SaveConfig.audit_team_id`` (4 = Boston
Red Sox in BUILDING_THE_GREEN_MONSTER).

Implementation notes:

- Org rollup uses the same ``COALESCE(NULLIF(parent_team_id, 0), team_id)``
  pattern as the L3 builder. Both from_team and to_team must roll up to
  the user's org, which is automatically the case for ``promotion`` /
  ``demotion`` rows since the L3 classifier requires ``from_org_id =
  to_org_id`` for those types.

- Before/after advanced stats are pulled from the L3 facts via a single
  LEFT JOIN per side (4 LEFT JOINs total). The join key includes
  ``league_id`` because the same level can host multiple leagues
  (AAA = IL/PCL etc.); we resolve each side's league_id from the
  team it was on.

- Verdict logic is in Python rather than SQL — easier to read and
  unit-testable later when we add eval harness coverage.

- The per-process DuckDB connection comes from ``warehouse.get_cursor``
  via FastAPI's dependency-injection (cursor-per-request, root-per-
  process — see ``warehouse.py`` for the rationale).
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Query

from diamond.api.schemas import (
    MovementBattingStats,
    MovementPitchingStats,
    MovementRow,
    MovementsResponse,
    MovementTeamRef,
)
from diamond.api.schemas.movements import (
    MovementDirection,
    MovementRole,
    MovementType,
    MovementVerdict,
)
from diamond.api.warehouse import get_active_save, get_cursor
from diamond.constants import LEVEL_NAMES, POSITION_NAMES

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Verdict thresholds
# ─────────────────────────────────────────────────────────────────────────────
#
# All numeric thresholds are in OPS+/ERA+/wRC+ space (100 = league
# average). The same thresholds apply to both batting and pitching
# since both metrics are normalized to that scale (and ERA+ already
# inverts so higher = better).
#
# Level-aware: MLB has a stricter "earned the spot" bar than the
# minor-league levels — the GM cares whether a call-up actually
# performed at MLB, not just survived. Below MLB, the existing
# 70/90/130 shape (matches audit-harness quality tiers) gives more
# room for prospect upside.
#
# - MLB (level=1):  ≥120 thriving, ≥100 working, ≥85 reconsider, <85 struggling
# - Below MLB:      ≥130 thriving, ≥90  working, ≥70 reconsider, <70 struggling

_THRESHOLDS_MLB = (120, 100, 85)        # great / good / ok
_THRESHOLDS_NON_MLB = (130, 90, 70)     # great / good / ok

_MIN_PA_AT_NEW_LEVEL = 30
_MIN_OUTS_AT_NEW_LEVEL = 30   # 10 IP


def _thresholds_for_level(level_id: int | None) -> tuple[int, int, int]:
    """Return (great, good, ok) thresholds for the destination level."""
    if level_id == 1:
        return _THRESHOLDS_MLB
    return _THRESHOLDS_NON_MLB


# ─────────────────────────────────────────────────────────────────────────────
# Verdict logic
# ─────────────────────────────────────────────────────────────────────────────


def _verdict_at_new_level(
    metric: int | None, sample: int, sample_min: int, sample_unit: str,
    to_level_id: int | None, kind: str,
) -> tuple[MovementVerdict, str]:
    """Verdict for promotions and acquisitions — both ask the same question:
    is the player performing at the new level?

    Level-aware: MLB uses a stricter (120/100/85) threshold; lower
    levels keep the (130/90/70) shape that gives prospects more
    runway. The ``kind`` arg only changes the "since X" wording in
    the too-small note ("call-up" vs "joining the org").
    """
    if sample < sample_min:
        return "too_small", f"only {sample} {sample_unit} since {kind}"
    if metric is None:
        return "too_small", "no league baselines for this level/year"
    great, good, ok = _thresholds_for_level(to_level_id)
    if metric >= great:
        return "working", f"thriving — {metric} at the new level"
    if metric >= good:
        return "working", f"holding their own — {metric}"
    if metric >= ok:
        return "reconsider", f"treading water — {metric}"
    return "struggling", f"drowning — {metric}"


def _verdict_for_demotion(
    metric: int | None, sample: int, sample_min: int, sample_unit: str,
) -> tuple[MovementVerdict, str]:
    """Demotion verdict: did the send-down do its job?

    A demotion's success criterion is inverted from a promotion: a
    player crushing the lower level after a send-down is *good news*
    (they're rebuilding, ready to come back) but it also means the
    GM should be asking "should they be back up?" — that's the
    "reconsider" cue. A player still scuffling at the lower level is
    bad news: their issues are deeper than the prior level's
    competition. Demotions don't go to MLB, so non-MLB thresholds
    (130/90) apply uniformly.
    """
    if sample < sample_min:
        return "too_small", f"only {sample} {sample_unit} since send-down"
    if metric is None:
        return "too_small", "no league baselines for this level/year"
    great, good, _ok = _THRESHOLDS_NON_MLB
    if metric >= great:
        return "reconsider", f"mashing the lower level ({metric}) — bring back?"
    if metric >= good:
        return "working", f"settling in at the lower level — {metric}"
    return "struggling", f"still not right — {metric}"


def _verdict_for_departure(
    metric: int | None, sample: int, sample_min: int, sample_unit: str,
    to_level_id: int | None,
) -> tuple[MovementVerdict, str]:
    """Departure verdict: did letting this player go work out for us?

    Inverts the promotion logic — verdict labels stay GM-perspective
    (working = good for us), but a *thriving* player elsewhere now
    means *bad call* for the org:

    - Player mashing elsewhere → ``struggling`` — we let someone good go.
    - Player struggling elsewhere → ``working`` — fair call, no regret.
    - Middle zone → ``reconsider``.

    Uses the same level-aware thresholds as promotions (post-move
    performance is at the destination level), and the same sample-size
    minimums.
    """
    if sample < sample_min:
        return "too_small", f"only {sample} {sample_unit} elsewhere since departure"
    if metric is None:
        return "too_small", "no league baselines for this level/year"
    great, good, ok = _thresholds_for_level(to_level_id)
    if metric >= great:
        return "struggling", f"mashing elsewhere ({metric}) — we let someone go"
    if metric >= good:
        return "reconsider", f"performing well elsewhere ({metric})"
    if metric >= ok:
        return "working", f"meh elsewhere ({metric}) — fair call"
    return "working", f"struggling elsewhere ({metric}) — good call"


def _verdict(
    movement_type: MovementType,
    direction: MovementDirection,
    role: MovementRole,
    to_level_id: int | None,
    after_batting: MovementBattingStats | None,
    after_pitching: MovementPitchingStats | None,
) -> tuple[MovementVerdict, str]:
    """Dispatch to the right verdict helper. Direction discriminates
    incoming vs outgoing trades/waivers since the same movement_type
    surfaces in both buckets."""
    if role == "batter":
        if after_batting is None:
            note = (
                "no recorded PA elsewhere yet" if direction == "outgoing"
                else "no recorded PA at the new level yet"
            )
            return "too_small", note
        metric = after_batting.ops_plus
        sample = after_batting.pa
        sample_min = _MIN_PA_AT_NEW_LEVEL
        sample_unit = "PA"
    else:
        if after_pitching is None:
            note = (
                "no recorded outs elsewhere yet" if direction == "outgoing"
                else "no recorded outs at the new level yet"
            )
            return "too_small", note
        metric = after_pitching.era_plus
        sample = after_pitching.outs
        sample_min = _MIN_OUTS_AT_NEW_LEVEL
        sample_unit = "outs"

    if direction == "outgoing":
        return _verdict_for_departure(
            metric, sample, sample_min, sample_unit, to_level_id,
        )
    if movement_type == "promotion":
        return _verdict_at_new_level(
            metric, sample, sample_min, sample_unit, to_level_id, "call-up",
        )
    if movement_type == "demotion":
        return _verdict_for_demotion(metric, sample, sample_min, sample_unit)
    # incoming trade / signed / waiver_or_other — same shape as
    # promotion (did the acquired player perform at the new level).
    return _verdict_at_new_level(
        metric, sample, sample_min, sample_unit, to_level_id, "joining the org",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Row-shape helpers
# ─────────────────────────────────────────────────────────────────────────────


def _team_ref(
    team_id: int | None,
    abbr: str | None,
    nickname: str | None,
    level_id: int | None,
) -> MovementTeamRef:
    """Wrap a (team_id, abbr, nickname, level_id) tuple in a MovementTeamRef.

    Returns a placeholder ref when team_id is null/0 (free agent /
    pre-snapshot state). The page treats those rows as edge cases —
    there shouldn't be any in promotion/demotion since both sides
    require a real team, but keeping the helper resilient avoids
    surprise null derefs."""
    if team_id is None or team_id == 0:
        return MovementTeamRef(
            team_id=0, abbr=None, nickname=None,
            level_id=None, level_name=None,
        )
    level_name = (
        LEVEL_NAMES.get(int(level_id)) if level_id is not None else None
    )
    return MovementTeamRef(
        team_id=int(team_id),
        abbr=abbr,
        nickname=nickname,
        level_id=int(level_id) if level_id is not None else None,
        level_name=level_name,
    )


def _batting(
    pa: int | None,
    ops_plus: int | None,
    wrc_plus: int | None,
    woba: float | None,
    o_war: float | None,
) -> MovementBattingStats | None:
    """Build a batting stat block, or None if the player has no
    recorded PA at this (year, league, level)."""
    if pa is None or pa <= 0:
        return None
    return MovementBattingStats(
        pa=int(pa),
        ops_plus=int(ops_plus) if ops_plus is not None else None,
        wrc_plus=int(wrc_plus) if wrc_plus is not None else None,
        woba=float(woba) if woba is not None else None,
        o_war=float(o_war) if o_war is not None else None,
    )


def _pitching(
    outs: int | None,
    ip_display: float | None,
    era_plus: int | None,
    fip: float | None,
    pit_war: float | None,
) -> MovementPitchingStats | None:
    """Build a pitching stat block, or None if no recorded outs at this
    (year, league, level)."""
    if outs is None or outs <= 0:
        return None
    return MovementPitchingStats(
        outs=int(outs),
        ip_display=float(ip_display) if ip_display is not None else None,
        era_plus=int(era_plus) if era_plus is not None else None,
        fip=float(fip) if fip is not None else None,
        pit_war=float(pit_war) if pit_war is not None else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────


# Number of columns each ledger row carries. The unified query and the
# row-builder are coupled to this width — when columns are added the
# unpacking in `_build_row` must match.
_LEDGER_QUERY = """
WITH org_team_filter AS (
    SELECT team_id FROM teams
    WHERE COALESCE(NULLIF(parent_team_id, 0), team_id) = ?
),
-- "Where did the released player accumulate the most reps this year?"
-- Per (player) we pick the max-PA / max-outs row across all (league,
-- level). For released moves (to_team_id=0, no destination) this is the
-- best signal we have for "did this player land somewhere and play."
-- For trade-out / waiver-out we use the to_team's league+level instead
-- (that's the actual destination), so these CTEs only matter when
-- to_team is missing/zero.
dest_bat AS (
    SELECT player_id,
           arg_max(league_id, pa)    AS dest_league_id,
           arg_max(level_id,  pa)    AS dest_level_id
    FROM f_player_season_advanced_batting
    WHERE year = ?
    GROUP BY player_id
),
dest_pit AS (
    SELECT player_id,
           arg_max(league_id, outs)  AS dest_league_id,
           arg_max(level_id,  outs)  AS dest_level_id
    FROM f_player_season_advanced_pitching
    WHERE year = ?
    GROUP BY player_id
)
SELECT
    m.movement_id,
    m.player_id,
    m.dump_date_observed,
    m.movement_type,
    -- direction discriminant — the page buckets each row by this
    CASE
        WHEN m.from_team_id IN (SELECT team_id FROM org_team_filter)
         AND m.to_team_id   IN (SELECT team_id FROM org_team_filter)
            THEN 'internal'
        WHEN m.to_team_id IN (SELECT team_id FROM org_team_filter)
            THEN 'incoming'
        ELSE 'outgoing'
    END AS direction,
    m.from_team_id, m.from_level_id,
    m.to_team_id,   m.to_level_id,
    tf.abbr      AS from_abbr,
    tf.nickname  AS from_nickname,
    tt.abbr      AS to_abbr,
    tt.nickname  AS to_nickname,
    pl.first_name, pl.last_name, pl.position,
    -- Resolved destination level for the "to" side. For released the
    -- to_team is empty, so we fall back to the dest_* CTE — best post-
    -- season-aggregation guess for where they ended up.
    COALESCE(m.to_level_id, db.dest_level_id, dp.dest_level_id)
        AS resolved_to_level_id,
    -- Before stats at the from-level
    bb_b.pa       AS bef_pa,
    bb_b.ops_plus AS bef_ops_plus,
    bb_b.wrc_plus AS bef_wrc_plus,
    bb_b.woba     AS bef_woba,
    bb_b.o_war    AS bef_o_war,
    bp_b.outs     AS bef_outs,
    bp_b.ip_display AS bef_ip_display,
    bp_b.era_plus AS bef_era_plus,
    bp_b.fip      AS bef_fip,
    bp_b.pit_war  AS bef_pit_war,
    -- After stats at the resolved destination
    ab_a.pa       AS aft_pa,
    ab_a.ops_plus AS aft_ops_plus,
    ab_a.wrc_plus AS aft_wrc_plus,
    ab_a.woba     AS aft_woba,
    ab_a.o_war    AS aft_o_war,
    ap_a.outs     AS aft_outs,
    ap_a.ip_display AS aft_ip_display,
    ap_a.era_plus AS aft_era_plus,
    ap_a.fip      AS aft_fip,
    ap_a.pit_war  AS aft_pit_war
FROM player_movements m
JOIN players_current pl ON pl.player_id = m.player_id
-- Both team joins are LEFT JOINs: for 'signed' from_team_id=0 (FA),
-- and for 'released' to_team_id=0 (FA pool).
LEFT JOIN teams tf ON tf.team_id = m.from_team_id
LEFT JOIN teams tt ON tt.team_id = m.to_team_id
LEFT JOIN dest_bat db ON db.player_id = m.player_id
LEFT JOIN dest_pit dp ON dp.player_id = m.player_id
LEFT JOIN f_player_season_advanced_batting bb_b
       ON bb_b.player_id = m.player_id
      AND bb_b.year      = EXTRACT(YEAR FROM m.dump_date_observed)
      AND bb_b.league_id = tf.league_id
      AND bb_b.level_id  = m.from_level_id
LEFT JOIN f_player_season_advanced_pitching bp_b
       ON bp_b.player_id = m.player_id
      AND bp_b.year      = EXTRACT(YEAR FROM m.dump_date_observed)
      AND bp_b.league_id = tf.league_id
      AND bp_b.level_id  = m.from_level_id
-- After-side: COALESCE the destination league/level, falling back to
-- dest_bat/dest_pit when the to-team is missing (released).
LEFT JOIN f_player_season_advanced_batting ab_a
       ON ab_a.player_id = m.player_id
      AND ab_a.year      = EXTRACT(YEAR FROM m.dump_date_observed)
      AND ab_a.league_id = COALESCE(tt.league_id, db.dest_league_id)
      AND ab_a.level_id  = COALESCE(m.to_level_id, db.dest_level_id)
LEFT JOIN f_player_season_advanced_pitching ap_a
       ON ap_a.player_id = m.player_id
      AND ap_a.year      = EXTRACT(YEAR FROM m.dump_date_observed)
      AND ap_a.league_id = COALESCE(tt.league_id, dp.dest_league_id)
      AND ap_a.level_id  = COALESCE(m.to_level_id, dp.dest_level_id)
WHERE EXTRACT(YEAR FROM m.dump_date_observed) = ?
  AND (
        -- internal: promotion/demotion (both ends in org by L3
        -- construction, but assert it explicitly)
        (m.movement_type IN ('promotion','demotion')
            AND m.from_team_id IN (SELECT team_id FROM org_team_filter)
            AND m.to_team_id   IN (SELECT team_id FROM org_team_filter))
        -- incoming: trade pickup, FA signing, waiver claim
        OR (m.movement_type IN ('trade','signed','waiver_or_other')
            AND m.to_team_id IN (SELECT team_id FROM org_team_filter))
        -- outgoing: trade away, waiver out, release
        OR (m.movement_type IN ('trade','waiver_or_other','released')
            AND m.from_team_id IN (SELECT team_id FROM org_team_filter))
      )
ORDER BY m.dump_date_observed DESC, m.movement_id DESC
"""


def _build_row(r: tuple) -> MovementRow:
    """Map one tuple from `_LEDGER_QUERY` to a `MovementRow`."""
    (movement_id, player_id, dump_date_observed, movement_type, direction,
     from_team_id, from_level_id, to_team_id, to_level_id,
     from_abbr, from_nickname,
     to_abbr, to_nickname,
     first_name, last_name, position,
     resolved_to_level_id,
     bef_pa, bef_ops_plus, bef_wrc_plus, bef_woba, bef_o_war,
     bef_outs, bef_ip_display, bef_era_plus, bef_fip, bef_pit_war,
     aft_pa, aft_ops_plus, aft_wrc_plus, aft_woba, aft_o_war,
     aft_outs, aft_ip_display, aft_era_plus, aft_fip, aft_pit_war,
     ) = r

    role: MovementRole = "pitcher" if int(position) == 1 else "batter"
    before_batting = _batting(
        bef_pa, bef_ops_plus, bef_wrc_plus, bef_woba, bef_o_war,
    )
    after_batting = _batting(
        aft_pa, aft_ops_plus, aft_wrc_plus, aft_woba, aft_o_war,
    )
    before_pitching = _pitching(
        bef_outs, bef_ip_display, bef_era_plus, bef_fip, bef_pit_war,
    )
    after_pitching = _pitching(
        aft_outs, aft_ip_display, aft_era_plus, aft_fip, aft_pit_war,
    )

    verdict, verdict_note = _verdict(
        movement_type=movement_type,
        direction=direction,
        role=role,
        to_level_id=(
            int(resolved_to_level_id) if resolved_to_level_id is not None
            else None
        ),
        after_batting=after_batting,
        after_pitching=after_pitching,
    )

    return MovementRow(
        movement_id=int(movement_id),
        player_id=int(player_id),
        player_name=f"{first_name} {last_name}",
        primary_position=POSITION_NAMES.get(int(position), f"P{position}"),
        role=role,
        movement_type=movement_type,
        direction=direction,
        dump_date_observed=dump_date_observed,
        from_team=_team_ref(from_team_id, from_abbr, from_nickname, from_level_id),
        to_team=_team_ref(to_team_id, to_abbr, to_nickname, to_level_id),
        before_batting=before_batting,
        after_batting=after_batting,
        before_pitching=before_pitching,
        after_pitching=after_pitching,
        verdict=verdict,
        verdict_note=verdict_note,
    )


@router.get("/movements", response_model=MovementsResponse)
def get_movements(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    year: Annotated[
        int | None,
        Query(description="Season year. Defaults to latest year with movements."),
    ] = None,
) -> MovementsResponse:
    """Movement ledger for the active save's user team for one season."""
    save = get_active_save()
    org_team_id = save.audit_team_id

    # Resolve the org's headline team metadata for the page header.
    org_meta = con.execute(
        "SELECT abbr, nickname FROM teams WHERE team_id = ?",
        [org_team_id],
    ).fetchone()
    org_abbr, org_nickname = (org_meta or (None, None))

    # Discover available seasons. Filter on either side of the move
    # touching the org so the picker covers every season with anything
    # in the ledger (internal, incoming, or outgoing).
    available_seasons = [
        int(r[0]) for r in con.execute(
            """
            WITH org_team_filter AS (
                SELECT team_id FROM teams
                WHERE COALESCE(NULLIF(parent_team_id, 0), team_id) = ?
            )
            SELECT DISTINCT EXTRACT(YEAR FROM dump_date_observed)::INTEGER AS yr
            FROM player_movements m
            WHERE m.movement_type IN
                  ('promotion','demotion','trade','signed','waiver_or_other','released')
              AND (m.from_team_id IN (SELECT team_id FROM org_team_filter)
                OR m.to_team_id   IN (SELECT team_id FROM org_team_filter))
            ORDER BY yr DESC
            """,
            [org_team_id],
        ).fetchall()
    ]
    if not available_seasons:
        return MovementsResponse(
            season=year or 0,
            available_seasons=[],
            org_team_id=org_team_id,
            org_team_abbr=org_abbr,
            org_team_nickname=org_nickname,
            rows=[],
        )

    season = year if year is not None else available_seasons[0]
    if year is not None and year not in available_seasons:
        # Caller asked for a season we don't have data for; return empty
        # rather than 404 so the page can render the picker + a "no
        # movements yet" empty state.
        return MovementsResponse(
            season=year,
            available_seasons=available_seasons,
            org_team_id=org_team_id,
            org_team_abbr=org_abbr,
            org_team_nickname=org_nickname,
            rows=[],
        )

    rows = con.execute(
        _LEDGER_QUERY, [org_team_id, season, season, season],
    ).fetchall()
    out = [_build_row(r) for r in rows]

    return MovementsResponse(
        season=season,
        available_seasons=available_seasons,
        org_team_id=org_team_id,
        org_team_abbr=org_abbr,
        org_team_nickname=org_nickname,
        rows=out,
    )
