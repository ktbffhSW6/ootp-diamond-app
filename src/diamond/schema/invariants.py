"""D40 invariants watchdog — drift detection across warehouse builds.

Compares **OOTP-cached aggregates** (passed through L2_OOTP from
`team_history_*_stats`) against **Diamond-derived aggregates** (built
by summing the per-player fact tables). Every (team, year, level)
combo produces one row per invariant metric; the delta + status are
stored in `_diamond_invariants` so subsequent ingests can show
"what's drifting".

What this catches
-----------------

These invariants validate **warehouse build integrity** — bugs like:
  - L1/L2 builders dropping rows from cross-dump dedup
  - Cross-stint aggregation missing a player's mid-season trade stint
  - Scope-filter bugs wrongly excluding org-tracked teams
  - L3 formula corrections changing aggregate behavior unexpectedly

The math itself comes from OOTP's own engine on both sides, so the
two should agree bit-for-bit when the warehouse build is correct. A
non-zero delta means **Diamond has lost information**, not that the
math is wrong.

Status convention
-----------------

  green  (|delta| ≤ tolerance)         — within rounding tolerance
  amber  (tolerance < |delta| ≤ 2·t)   — drift starting; investigate
  red    (|delta| > 2·tolerance)       — clear bug, fix before ship

Tolerances default to "OOTP IE display rounding" — 0.001 for rate
stats (3-decimal display), 0.1 for ERA/FIP, 0.5 for integer event
counts (allows 1-row rounding from cross-dump dedup edge cases).

What's NOT in scope here
------------------------

OOTP IE display matching (handled by `audit/reconcile.py` + L_IE
routing). This module is about **internal warehouse self-consistency**
— "did Diamond's aggregation pipeline lose anything between L0 and L3".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
from rich.console import Console

from diamond.schema.build import get_setting, set_setting

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Invariant catalog
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvariantSpec:
    """One invariant comparison.

    Each spec emits one row per (team_id / league_id, year, level_id)
    into `_diamond_invariants`. The pair of SQL expressions runs inside
    a CTE that joins the dump-cache table to the derived-aggregate
    table on the natural key.
    """

    metric: str                 # e.g. 'team_avg'
    scope_type: str             # 'team' | 'league' | 'event_count'
    dump_table: str             # source for cached value
    dump_expr: str              # column or expression for cached value
    derived_table: str          # source for derived value
    derived_expr: str           # column or expression for derived value
    tolerance: float            # |dump - derived| under this → green
    join_keys: tuple[str, ...] = ("team_id", "year", "level_id")
    where_clause: str = ""      # optional extra filter, e.g. split_id=1
    note: str = ""              # human-readable description


# Initial 10 invariants — focused on team-grain rate stats + event-count
# consistency. Each one runs in <100ms on the Padres warehouse.
INVARIANT_CATALOG: tuple[InvariantSpec, ...] = (
    # ── Team batting rate sanity ────────────────────────────────────────────
    InvariantSpec(
        metric="team_avg",
        scope_type="team",
        dump_table="f_team_season_batting_ootp",
        dump_expr="avg",
        derived_table="(SELECT team_id, year, level_id, "
                       "       CAST(SUM(h) AS DOUBLE)/NULLIF(SUM(ab),0) AS v "
                       "FROM f_player_season_batting WHERE split_id=1 "
                       "GROUP BY team_id, year, level_id)",
        derived_expr="v",
        tolerance=0.001,
        note="Team H/AB vs OOTP-cached AVG. Catches roster-aggregation bugs.",
    ),
    InvariantSpec(
        metric="team_obp",
        scope_type="team",
        dump_table="f_team_season_batting_ootp",
        dump_expr="obp",
        derived_table="(SELECT team_id, year, level_id, "
                       "       CAST(SUM(h)+SUM(bb)+SUM(hp) AS DOUBLE)/"
                       "       NULLIF(SUM(ab)+SUM(bb)+SUM(hp)+SUM(sf),0) AS v "
                       "FROM f_player_season_batting WHERE split_id=1 "
                       "GROUP BY team_id, year, level_id)",
        derived_expr="v",
        tolerance=0.001,
        note="Team (H+BB+HBP)/(AB+BB+HBP+SF) vs OOTP-cached OBP.",
    ),
    InvariantSpec(
        metric="team_slg",
        scope_type="team",
        dump_table="f_team_season_batting_ootp",
        dump_expr="slg",
        # f_player_season_batting has h, d, t, hr but no `tb` column.
        # TB = 1B + 2*2B + 3*3B + 4*HR = (h-d-t-hr) + 2*d + 3*t + 4*hr
        #    = h + d + 2*t + 3*hr
        derived_table="(SELECT team_id, year, level_id, "
                       "       CAST(SUM(h)+SUM(d)+2*SUM(t)+3*SUM(hr) AS DOUBLE)/NULLIF(SUM(ab),0) AS v "
                       "FROM f_player_season_batting WHERE split_id=1 "
                       "GROUP BY team_id, year, level_id)",
        derived_expr="v",
        tolerance=0.001,
        note="Team TB/AB vs OOTP-cached SLG (TB = h + d + 2t + 3hr).",
    ),
    # NOTE — `team_history_batting_stats.woba` is 0.0 for every row in
    # this OOTP version (the team-level cache column isn't populated).
    # We can't compare a derived wOBA against an OOTP-cached value that
    # doesn't exist. Team-aggregate wOBA validation moves to the
    # league-rollup invariants below once `f_league_season` is wired.
    # ── Team pitching rate sanity ───────────────────────────────────────────
    # NOTE: f_player_season_pitching exposes `outs` directly (canonical
    # ip*3 + ipf), plus `ha` for hits allowed and `hra` for HR allowed.
    InvariantSpec(
        metric="team_era",
        scope_type="team",
        dump_table="f_team_season_pitching_ootp",
        dump_expr="era",
        derived_table=(
            "(SELECT team_id, year, level_id, "
            "        CAST(SUM(er) AS DOUBLE) * 27.0 / NULLIF(SUM(outs),0) AS v "
            " FROM f_player_season_pitching WHERE split_id=1 "
            " GROUP BY team_id, year, level_id)"
        ),
        derived_expr="v",
        tolerance=0.05,  # ERA is ~3-5; 0.05 = ~1pp
        note="Team ER·27/outs vs OOTP-cached ERA.",
    ),
    InvariantSpec(
        metric="team_whip",
        scope_type="team",
        dump_table="f_team_season_pitching_ootp",
        dump_expr="whip",
        derived_table=(
            "(SELECT team_id, year, level_id, "
            "        CAST(SUM(bb)+SUM(ha) AS DOUBLE) * 3.0 / NULLIF(SUM(outs),0) AS v "
            " FROM f_player_season_pitching WHERE split_id=1 "
            " GROUP BY team_id, year, level_id)"
        ),
        derived_expr="v",
        tolerance=0.02,
        note="Team (BB+H)/IP vs OOTP-cached WHIP.",
    ),
    InvariantSpec(
        metric="team_k9",
        scope_type="team",
        dump_table="f_team_season_pitching_ootp",
        dump_expr="k9",
        derived_table=(
            "(SELECT team_id, year, level_id, "
            "        CAST(SUM(k) AS DOUBLE) * 27.0 / NULLIF(SUM(outs),0) AS v "
            " FROM f_player_season_pitching WHERE split_id=1 "
            " GROUP BY team_id, year, level_id)"
        ),
        derived_expr="v",
        tolerance=0.05,
        note="Team K·27/outs vs OOTP-cached K/9.",
    ),
    InvariantSpec(
        metric="team_bb9",
        scope_type="team",
        dump_table="f_team_season_pitching_ootp",
        dump_expr="bb9",
        derived_table=(
            "(SELECT team_id, year, level_id, "
            "        CAST(SUM(bb) AS DOUBLE) * 27.0 / NULLIF(SUM(outs),0) AS v "
            " FROM f_player_season_pitching WHERE split_id=1 "
            " GROUP BY team_id, year, level_id)"
        ),
        derived_expr="v",
        tolerance=0.05,
        note="Team BB·27/outs vs OOTP-cached BB/9.",
    ),
    # ── Event-count consistency ─────────────────────────────────────────────
    InvariantSpec(
        metric="team_pa_count",
        scope_type="event_count",
        dump_table="f_team_season_batting_ootp",
        dump_expr="pa",
        derived_table="(SELECT team_id, year, level_id, "
                       "       SUM(pa) AS v "
                       "FROM f_player_season_batting WHERE split_id=1 "
                       "GROUP BY team_id, year, level_id)",
        derived_expr="v",
        tolerance=0.5,
        note="Sum of player PA matches OOTP-cached team PA.",
    ),
    InvariantSpec(
        metric="team_hr_count",
        scope_type="event_count",
        dump_table="f_team_season_batting_ootp",
        dump_expr="hr",
        derived_table="(SELECT team_id, year, level_id, "
                       "       SUM(hr) AS v "
                       "FROM f_player_season_batting WHERE split_id=1 "
                       "GROUP BY team_id, year, level_id)",
        derived_expr="v",
        tolerance=0.5,
        note="Sum of player HR matches OOTP-cached team HR.",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────────────────────────────────────


_INVARIANTS_DDL = """
CREATE TABLE IF NOT EXISTS _diamond_invariants (
    dump_date     DATE     NOT NULL,
    scope_type    VARCHAR  NOT NULL,
    scope_id      BIGINT,
    year          INTEGER,
    level_id      INTEGER,
    metric        VARCHAR  NOT NULL,
    dump_value    DOUBLE,
    derived_value DOUBLE,
    delta         DOUBLE,
    tolerance     DOUBLE   NOT NULL,
    status        VARCHAR  NOT NULL,
    note          VARCHAR
);
"""


def ensure_invariants_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create `_diamond_invariants` if it doesn't exist. Idempotent."""
    con.execute(_INVARIANTS_DDL)


# ─────────────────────────────────────────────────────────────────────────────
# Computation
# ─────────────────────────────────────────────────────────────────────────────


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1",
        [table],
    ).fetchone()
    return row is not None


def _latest_dump_date(con: duckdb.DuckDBPyConnection) -> date:
    """Use the warehouse's most-recent dump_date as the watermark."""
    row = con.execute(
        "SELECT MAX(dump_date) FROM _diamond_ingests WHERE status = 'success'"
    ).fetchone()
    if row is None or row[0] is None:
        # Fallback: pull from any L0 table
        row = con.execute(
            "SELECT MAX(dump_date) FROM l0_team_history_batting_stats"
        ).fetchone()
    return row[0]


def _run_invariant(
    con: duckdb.DuckDBPyConnection,
    spec: InvariantSpec,
    dump_date: date,
) -> list[tuple]:
    """Compute one invariant. Returns list of (scope_id, year, level_id,
    dump_value, derived_value, delta, status) tuples."""
    join_on = " AND ".join(f"d.{k} = x.{k}" for k in spec.join_keys)
    where = f"WHERE {spec.where_clause}" if spec.where_clause else ""
    sql = f"""
        WITH dump AS (
            SELECT
                {', '.join(spec.join_keys)},
                CAST({spec.dump_expr} AS DOUBLE) AS dv
            FROM {spec.dump_table}
            {where}
        ),
        derived AS (
            SELECT
                {', '.join(spec.join_keys)},
                CAST({spec.derived_expr} AS DOUBLE) AS xv
            FROM {spec.derived_table}
        )
        SELECT
            d.team_id,
            d.year,
            d.level_id,
            d.dv,
            x.xv,
            d.dv - x.xv AS delta
        FROM dump d
        INNER JOIN derived x ON {join_on}
        WHERE d.dv IS NOT NULL AND x.xv IS NOT NULL
    """
    out: list[tuple] = []
    for r in con.execute(sql).fetchall():
        scope_id, year, level_id, dv, xv, delta = r
        adelta = abs(delta) if delta is not None else None
        if adelta is None:
            status = "amber"
        elif adelta <= spec.tolerance:
            status = "green"
        elif adelta <= 2 * spec.tolerance:
            status = "amber"
        else:
            status = "red"
        out.append((scope_id, year, level_id, dv, xv, delta, status))
    return out


def run_invariants(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, dict]:
    """Compute every invariant and persist to `_diamond_invariants`.

    Returns ``{metric: {green: n, amber: n, red: n, total: n}}``.

    Replaces all rows for the current `dump_date` — re-running on the
    same watermark is idempotent.
    """
    ensure_invariants_table(con)

    # Skip silently if prerequisite tables missing (warehouse predates
    # Phase 4a #2 wiring, or first-build state). Caller handles fallback.
    if not _table_exists(con, "f_team_season_batting_ootp"):
        if verbose:
            console.print(
                "  [yellow]skipping invariants:[/yellow] "
                "f_team_season_batting_ootp missing (run `diamond ingest`)"
            )
        return {}

    dump_date = _latest_dump_date(con)
    # Clear prior rows at this dump_date — idempotent within a single dump.
    con.execute(
        "DELETE FROM _diamond_invariants WHERE dump_date = ?", [dump_date]
    )

    summary: dict[str, dict] = {}
    for spec in INVARIANT_CATALOG:
        rows = _run_invariant(con, spec, dump_date)
        green = sum(1 for r in rows if r[6] == "green")
        amber = sum(1 for r in rows if r[6] == "amber")
        red = sum(1 for r in rows if r[6] == "red")
        summary[spec.metric] = {
            "green": green,
            "amber": amber,
            "red": red,
            "total": len(rows),
            "scope_type": spec.scope_type,
            "tolerance": spec.tolerance,
        }
        # Persist (insert one row per (team, year, level))
        if rows:
            con.executemany(
                """
                INSERT INTO _diamond_invariants
                  (dump_date, scope_type, scope_id, year, level_id,
                   metric, dump_value, derived_value, delta, tolerance,
                   status, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        dump_date,
                        spec.scope_type,
                        scope_id,
                        year,
                        level_id,
                        spec.metric,
                        dv,
                        xv,
                        delta,
                        spec.tolerance,
                        status,
                        spec.note,
                    )
                    for (scope_id, year, level_id, dv, xv, delta, status) in rows
                ],
            )
        if verbose:
            color = (
                "green" if red == 0 and amber == 0
                else ("yellow" if red == 0 else "red")
            )
            status_chip = f"[{color}]{red} red / {amber} amber / {green} green[/{color}]"
            console.print(
                f"  [bold]{spec.metric:<18}[/bold] {status_chip}  "
                f"[dim]({len(rows)} rows, tol={spec.tolerance})[/dim]"
            )

    # Stamp the last-run timestamp for the cockpit pill.
    set_setting(con, "invariants.last_run_dump_date", dump_date.isoformat())
    set_setting(
        con,
        "invariants.last_run_summary_json",
        _summary_to_json(summary),
    )

    return summary


def _summary_to_json(summary: dict[str, dict]) -> str:
    """Compact JSON for cockpit pill consumption."""
    import json

    return json.dumps(
        {
            "metrics": {
                k: {"green": v["green"], "amber": v["amber"], "red": v["red"],
                    "total": v["total"]}
                for k, v in summary.items()
            },
            "overall": {
                "green": sum(v["green"] for v in summary.values()),
                "amber": sum(v["amber"] for v in summary.values()),
                "red":   sum(v["red"]   for v in summary.values()),
                "total": sum(v["total"] for v in summary.values()),
            },
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reporting helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_latest_invariants_summary(
    con: duckdb.DuckDBPyConnection,
) -> dict | None:
    """Return the cached last-run summary as a dict, or None if never run."""
    import json

    raw = get_setting(con, "invariants.last_run_summary_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    data["last_run_dump_date"] = get_setting(con, "invariants.last_run_dump_date")
    return data


def get_invariant_failures(
    con: duckdb.DuckDBPyConnection,
    *,
    status: str = "red",
    limit: int = 20,
) -> list[dict]:
    """Pull recent invariant failures for the admin / debugging UI.

    `status='red'` returns clear bugs; `'amber'` adds drifting cases.
    Sorted by absolute delta, descending.
    """
    if not _table_exists(con, "_diamond_invariants"):
        return []
    statuses = ("red",) if status == "red" else ("red", "amber")
    placeholders = ",".join("?" for _ in statuses)
    rows = con.execute(
        f"""
        SELECT dump_date, scope_type, scope_id, year, level_id,
               metric, dump_value, derived_value, delta, tolerance,
               status, note
        FROM _diamond_invariants
        WHERE status IN ({placeholders})
        ORDER BY ABS(delta) DESC NULLS LAST
        LIMIT ?
        """,
        list(statuses) + [limit],
    ).fetchall()
    return [
        {
            "dump_date": r[0].isoformat() if r[0] else None,
            "scope_type": r[1],
            "scope_id": r[2],
            "year": r[3],
            "level_id": r[4],
            "metric": r[5],
            "dump_value": r[6],
            "derived_value": r[7],
            "delta": r[8],
            "tolerance": r[9],
            "status": r[10],
            "note": r[11],
        }
        for r in rows
    ]
