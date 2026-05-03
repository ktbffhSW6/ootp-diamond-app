"""Per-(league_id, year, level_id) constants for sabermetric stats.

Source of truth: OOTP's `league_history_batting_stats.csv` and
`league_history_pitching_stats.csv` — pre-aggregated league totals,
level-aware. Per Decision D11:

  - **No AL/NL split.** When OOTP's league_history file emits separate
    rows for AL and NL sub-leagues, we sum them into the parent league_id.
    Empirically a no-op in this save (single MLB row), but the GROUP BY
    is defensive.
  - **International leagues are separate universes.** Each foreign league
    keeps its own league_id; no cross-league rollup.
  - **No cross-level rollups for rate stats.** A AAA player's OPS+ uses
    AAA league constants, not MLB's. The level_id stays in the key.

Two consumption modes:

  - **SQL (the audit harness)**: call `register_views(con)` after the
    `league_history_*` views are registered. Two DuckDB views are created:

      `lg_constants_bat`  — league_id, year, level_id, lg_pa, lg_ab, lg_h,
                            lg_d, lg_t, lg_hr, lg_bb, lg_hp, lg_sf, lg_sh,
                            lg_k, lg_sb, lg_cs, lg_obp, lg_slg

      `lg_constants_pit`  — league_id, year, level_id, lg_era, lg_ha,
                            lg_hra, lg_bb, lg_hp, lg_k, lg_ab, lg_bf, lg_ip

    Downstream queries `LEFT JOIN lg_constants_bat USING (league_id, year, level_id)`
    (or, where the joining table only knows player→primary_league/level, on
    those keys plus a literal `year`).

  - **Python**: call `lookup(con, league_id, year, level_id)` to get a
    `LeagueConstants` dataclass for use outside DuckDB SQL (e.g. unit
    tests, ad-hoc scripts, future warehouse-builder code).

Both modes read from the same two views, so values are guaranteed
consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeagueConstants:
    """Per-(league_id, year, level_id) constants for one league-season-level."""

    league_id: int
    year: int
    level_id: int

    # Batting totals
    lg_pa: int
    lg_ab: int
    lg_h: int
    lg_d: int
    lg_t: int
    lg_hr: int
    lg_bb: int
    lg_hp: int
    lg_sf: int
    lg_sh: int
    lg_k: int
    lg_sb: int
    lg_cs: int

    # Batting rates (recomputed from totals — never averaged from sub-league rates)
    lg_obp: float
    lg_slg: float

    # Pitching totals
    lg_ha: int
    lg_hra: int
    lg_pit_bb: int
    lg_pit_hp: int
    lg_pit_k: int
    lg_pit_ab: int
    lg_bf: int
    lg_ip: float

    # Pitching rate
    lg_era: float


# ─────────────────────────────────────────────────────────────────────────────
# View definitions
# ─────────────────────────────────────────────────────────────────────────────


# Aggregated batting league constants per (league_id, year, level_id).
# Sums across any AL/NL sub-rows OOTP may emit (D11). Recomputes lg_obp /
# lg_slg from totals rather than averaging the per-row rates — averaging
# would be wrong if sub-leagues had different PA volumes.
_BAT_VIEW_SQL = """
CREATE OR REPLACE VIEW lg_constants_bat AS
SELECT
    league_id,
    year,
    level_id,
    SUM(pa) AS lg_pa,
    SUM(ab) AS lg_ab,
    SUM(h)  AS lg_h,
    SUM(d)  AS lg_d,
    SUM(t)  AS lg_t,
    SUM(hr) AS lg_hr,
    SUM(bb) AS lg_bb,
    SUM(hp) AS lg_hp,
    SUM(sf) AS lg_sf,
    SUM(sh) AS lg_sh,
    SUM(k)  AS lg_k,
    SUM(sb) AS lg_sb,
    SUM(cs) AS lg_cs,
    ROUND(
        (SUM(h) + SUM(bb) + SUM(hp))::DOUBLE
        / NULLIF(SUM(ab) + SUM(bb) + SUM(hp) + SUM(sf), 0),
        4
    ) AS lg_obp,
    ROUND(
        SUM(tb)::DOUBLE / NULLIF(SUM(ab), 0),
        4
    ) AS lg_slg
FROM league_history_batting_stats
GROUP BY league_id, year, level_id
"""


# Aggregated pitching league constants per (league_id, year, level_id).
# IP convention here is fractional (full innings + ipf/3) because that's
# the unit lg_era and FIP cFIP need. Player-side IP convention (`172.1`
# for 517 outs) is a display-only convention handled in reconcile.py.
_PIT_VIEW_SQL = """
CREATE OR REPLACE VIEW lg_constants_pit AS
SELECT
    league_id,
    year,
    level_id,
    ROUND(
        SUM(er)::DOUBLE * 9.0 / NULLIF(SUM(ip) + SUM(ipf) / 3.0, 0),
        3
    ) AS lg_era,
    SUM(ha)  AS lg_ha,
    SUM(hra) AS lg_hra,
    SUM(bb)  AS lg_bb,
    SUM(hp)  AS lg_hp,
    SUM(k)   AS lg_k,
    SUM(ab)  AS lg_ab,
    SUM(bf)  AS lg_bf,
    SUM(ip) + SUM(ipf) / 3.0 AS lg_ip
FROM league_history_pitching_stats
GROUP BY league_id, year, level_id
"""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def register_views(con: duckdb.DuckDBPyConnection) -> None:
    """Create `lg_constants_bat` and `lg_constants_pit` views on `con`.

    Requires `league_history_batting_stats` and `league_history_pitching_stats`
    views/tables to already be registered. Idempotent (uses CREATE OR REPLACE).
    """
    con.execute(_BAT_VIEW_SQL)
    con.execute(_PIT_VIEW_SQL)


def lookup(
    con: duckdb.DuckDBPyConnection,
    league_id: int,
    year: int,
    level_id: int,
) -> LeagueConstants | None:
    """Return one `LeagueConstants` row, or `None` if no such key exists.

    Assumes `register_views(con)` was already called. The returned object is
    purely Python — useful for unit tests, ad-hoc scripts, or any code that
    needs the constants outside a DuckDB query.
    """
    bat = con.execute(
        """
        SELECT
            lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
            lg_bb, lg_hp, lg_sf, lg_sh, lg_k, lg_sb, lg_cs,
            lg_obp, lg_slg
        FROM lg_constants_bat
        WHERE league_id = ? AND year = ? AND level_id = ?
        """,
        [league_id, year, level_id],
    ).fetchone()
    if bat is None:
        return None

    pit = con.execute(
        """
        SELECT
            lg_era, lg_ha, lg_hra, lg_bb, lg_hp, lg_k,
            lg_ab, lg_bf, lg_ip
        FROM lg_constants_pit
        WHERE league_id = ? AND year = ? AND level_id = ?
        """,
        [league_id, year, level_id],
    ).fetchone()
    # Pitching row is expected to exist for any league-year-level that has a
    # batting row, but be defensive: a league with zero IP would still yield
    # a None here, in which case fall back to NaN-flavoured zeros.
    if pit is None:
        pit = (0.0, 0, 0, 0, 0, 0, 0, 0, 0.0)

    (lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
     lg_bb, lg_hp, lg_sf, lg_sh, lg_k, lg_sb, lg_cs,
     lg_obp, lg_slg) = bat
    (lg_era, lg_ha, lg_hra, lg_pit_bb, lg_pit_hp, lg_pit_k,
     lg_pit_ab, lg_bf, lg_ip) = pit

    return LeagueConstants(
        league_id=league_id, year=year, level_id=level_id,
        lg_pa=lg_pa, lg_ab=lg_ab, lg_h=lg_h, lg_d=lg_d, lg_t=lg_t, lg_hr=lg_hr,
        lg_bb=lg_bb, lg_hp=lg_hp, lg_sf=lg_sf, lg_sh=lg_sh,
        lg_k=lg_k, lg_sb=lg_sb, lg_cs=lg_cs,
        lg_obp=lg_obp, lg_slg=lg_slg,
        lg_ha=lg_ha, lg_hra=lg_hra,
        lg_pit_bb=lg_pit_bb, lg_pit_hp=lg_pit_hp, lg_pit_k=lg_pit_k,
        lg_pit_ab=lg_pit_ab, lg_bf=lg_bf, lg_ip=lg_ip,
        lg_era=lg_era,
    )


def compute_all(
    con: duckdb.DuckDBPyConnection,
) -> dict[tuple[int, int, int], LeagueConstants]:
    """Return every `(league_id, year, level_id)` -> `LeagueConstants`.

    Bulk variant of `lookup`. Useful for warehouse builds where every
    league-year-level needs to be materialized. Assumes `register_views`.
    """
    rows = con.execute(
        """
        SELECT
            b.league_id, b.year, b.level_id,
            b.lg_pa, b.lg_ab, b.lg_h, b.lg_d, b.lg_t, b.lg_hr,
            b.lg_bb, b.lg_hp, b.lg_sf, b.lg_sh, b.lg_k, b.lg_sb, b.lg_cs,
            b.lg_obp, b.lg_slg,
            COALESCE(p.lg_era, 0.0)  AS lg_era,
            COALESCE(p.lg_ha,  0)    AS lg_ha,
            COALESCE(p.lg_hra, 0)    AS lg_hra,
            COALESCE(p.lg_bb,  0)    AS lg_pit_bb,
            COALESCE(p.lg_hp,  0)    AS lg_pit_hp,
            COALESCE(p.lg_k,   0)    AS lg_pit_k,
            COALESCE(p.lg_ab,  0)    AS lg_pit_ab,
            COALESCE(p.lg_bf,  0)    AS lg_bf,
            COALESCE(p.lg_ip,  0.0)  AS lg_ip
        FROM lg_constants_bat b
        LEFT JOIN lg_constants_pit p
          ON p.league_id = b.league_id
         AND p.year      = b.year
         AND p.level_id  = b.level_id
        """
    ).fetchall()
    out: dict[tuple[int, int, int], LeagueConstants] = {}
    for row in rows:
        (league_id, year, level_id,
         lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
         lg_bb, lg_hp, lg_sf, lg_sh, lg_k, lg_sb, lg_cs,
         lg_obp, lg_slg,
         lg_era, lg_ha, lg_hra, lg_pit_bb, lg_pit_hp, lg_pit_k,
         lg_pit_ab, lg_bf, lg_ip) = row
        out[(league_id, year, level_id)] = LeagueConstants(
            league_id=league_id, year=year, level_id=level_id,
            lg_pa=lg_pa, lg_ab=lg_ab, lg_h=lg_h, lg_d=lg_d, lg_t=lg_t, lg_hr=lg_hr,
            lg_bb=lg_bb, lg_hp=lg_hp, lg_sf=lg_sf, lg_sh=lg_sh,
            lg_k=lg_k, lg_sb=lg_sb, lg_cs=lg_cs,
            lg_obp=lg_obp, lg_slg=lg_slg,
            lg_ha=lg_ha, lg_hra=lg_hra,
            lg_pit_bb=lg_pit_bb, lg_pit_hp=lg_pit_hp, lg_pit_k=lg_pit_k,
            lg_pit_ab=lg_pit_ab, lg_bf=lg_bf, lg_ip=lg_ip,
            lg_era=lg_era,
        )
    return out
