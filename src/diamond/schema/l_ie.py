"""L_IE — Import/Export display values from OOTP roster exports.

Per D41 (display policy): where L_IE values are present, the API display
layer prefers them over warehouse derivations. The L_IE layer guarantees
bit-for-bit OOTP match for **current-year org-roster players** on every
displayed stat — eliminating the last 1-5% rounding/algorithmic noise
that survives a clean reconcile pass.

What L_IE IS
------------
- 21 ``lie_*`` tables, one per ``<save>/import_export/*_organization_-_roster_*.csv``.
- Each table keyed on player ``ID`` with all values stored as ``VARCHAR``
  (preserves OOTP's display formatting — `.250`, `9.1%`, `$25 000 000`).
- Plus a per-player unified view ``v_lie_player_display`` that surfaces
  parsed numerics for the high-traffic stat fields (slash, counting,
  sabermetric core) ready to ``COALESCE`` against derivations in API CTEs.

What L_IE is NOT
----------------
- Cumulative or historical. IE exports are point-in-time snapshots of
  "this org's current-year roster as it was the last time the user hit
  Reports → Export". L_IE re-ingests destructively on every warehouse
  refresh (DROP + recreate); the prior export is overwritten.
- Cross-save. Each save has its own ``import_export/`` folder, so
  L_IE values are scoped to the active save's org.
- Universal coverage. Only the org's ~270 active players are in IE;
  trading partners, opposing-team stars, retired Lahman/BREF history,
  and prior-year stints are NOT covered. The COALESCE pattern falls
  through to derivations for those.

Org-agnostic file discovery
---------------------------
Files are matched by org-agnostic suffix (e.g. ``_organization_-_roster_batting_stats_1.csv``),
not the org prefix. So ``boston_red_sox_organization_-_*`` files in the
Sox save and ``san_diego_padres_organization_-_*`` files in The Fathers
save both resolve via the same ``LieSpec``. Mirrors ``_resolve_ie_path``
in ``audit/reconcile.py``.

Best-effort + skip-on-missing
-----------------------------
A save without IE exports (newly created, or user hasn't run the
Reports export) gets no ``lie_*`` tables and no unified view — the
``v_lie_player_display`` view is built as empty in that case, so
downstream LEFT JOINs return NULL and COALESCE falls through cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
from rich.console import Console

from diamond.config import SaveConfig
from diamond.schema.build import set_setting

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Catalog — one entry per import_export CSV
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LieSpec:
    """One import_export-CSV → ``lie_*`` table mapping."""

    suffix: str           # org-agnostic filename tail, e.g. "_organization_-_roster_batting_stats_1.csv"
    lie_table: str        # destination table name (must start with ``lie_``)
    note: str             # one-liner for logs


LIE_CATALOG: tuple[LieSpec, ...] = (
    # ── Basic identity ──────────────────────────────────────────────────────
    LieSpec(
        "_organization_-_roster_default.csv",
        "lie_default",
        "Basic player info — POS, Age, NAT, HT, WT, B, T, OVR, POT, SLR",
    ),
    LieSpec(
        "_organization_-_roster_popularity_info.csv",
        "lie_popularity_info",
        "Pop — Nat. Pop, Loc. Pop, OVR, POT, SctAcc",
    ),
    LieSpec(
        "_organization_-_roster_personality___morale.csv",
        "lie_personality___morale",
        "Personality + morale — Mor, LEA, LOY, FIN, WE, INT, Type",
    ),
    LieSpec(
        "_organization_-_roster_financial_info.csv",
        "lie_financial_info",
        "Financials — SLR, YL, CV, TY, ECV, ETY, MLY, OPT, OY, ON40",
    ),
    # ── Batting ─────────────────────────────────────────────────────────────
    LieSpec(
        "_organization_-_roster_batting_stats_1.csv",
        "lie_batting_stats_1",
        "Batting slash + counting + OPS+ + WAR",
    ),
    LieSpec(
        "_organization_-_roster_batting_stats_2.csv",
        "lie_batting_stats_2",
        "Batting rate + sabermetric — BB%, K%, EBH, TB, RC, RC/27, ISO, wOBA, WPA, PI/PA",
    ),
    LieSpec(
        "_organization_-_roster_batting_superstats_1.csv",
        "lie_batting_superstats_1",
        "Statcast + batted-ball — BIP, GB/FB, LD%, GB%, FB%, IFFB, HR/FB, IFH%, BUH%, Pull%, Cent%, Oppo%, Soft%, Avg%, Solid%, EV, mEV, LA, BAR, BAR%, HHi, HHi%, xBA, xSLG, xwOBA",
    ),
    LieSpec(
        "_organization_-_roster_batting_superstats_2.csv",
        "lie_batting_superstats_2",
        "Pitch-discipline — PI, WH%, CH%, Z%, CL%, OS%, ZS%, SW%, OC%, ZC%, CTC%, FF%, BR%, OFF%, RV-*",
    ),
    LieSpec(
        "_organization_-_roster_batting_ratings.csv",
        "lie_batting_ratings",
        "Batting ratings — OVR, CON, BABIP, K's, GAP, POW, EYE, vL/vR splits, BUN, BFH, SPE, STE, DEF",
    ),
    LieSpec(
        "_organization_-_roster_batting_potential.csv",
        "lie_batting_potential",
        "Batting potential — POT, CON P, HT P, K P, GAP P, POW P, EYE P, SPE, STE, RUN, DEF",
    ),
    # ── Pitching ────────────────────────────────────────────────────────────
    LieSpec(
        "_organization_-_roster_pitching_stats_1.csv",
        "lie_pitching_stats_1",
        "Pitching slash + counting + ERA+ + FIP + WAR",
    ),
    LieSpec(
        "_organization_-_roster_pitching_stats_2.csv",
        "lie_pitching_stats_2",
        "Pitching rate + sabermetric — WIN%, SV%, BS, SD, MD, BF, DP, RA, GF, IR, IRS%, pLi, QS, QS%, CG, CG%, SHO, PPG, RSG, GO%, SIERA, SB, CS, WPA",
    ),
    LieSpec(
        "_organization_-_roster_pitching_superstats_1.csv",
        "lie_pitching_superstats_1",
        "Statcast + batted-ball allowed — BIP, GB/FB, LD%, GB%, FB%, IFFB, HR/FB, Soft%, Med%, Solid%, EV, xBA, xSLG, xwOBA, xERA",
    ),
    LieSpec(
        "_organization_-_roster_pitching_superstats_2.csv",
        "lie_pitching_superstats_2",
        "Pitch-discipline allowed — PI, SW, WH, CH, OS%, ZS%, SW%, OC%, ZC%, Z%, WH%, CH%, CL%, RV-*",
    ),
    LieSpec(
        "_organization_-_roster_pitching_ratings.csv",
        "lie_pitching_ratings",
        "Pitching ratings — OVR, STU, MOV, HRA, PBABIP, CON, vL/vR splits, VELO, STM, G/F, HLD",
    ),
    LieSpec(
        "_organization_-_roster_pitching_potential.csv",
        "lie_pitching_potential",
        "Pitching potential — POT, STU P, MOV P, HRA P, PBABIP P, CON P, VELO, STM, G/F, HLD",
    ),
    LieSpec(
        "_organization_-_roster_individual_pitch_ratings.csv",
        "lie_individual_pitch_ratings",
        "Per-pitch ratings — FB, CH, CB, SL, SI, SP, CT, FO, CC, SC, KC, KN, PIT, VELO, Slot, STM",
    ),
    LieSpec(
        "_organization_-_roster_individual_pitch_potential.csv",
        "lie_individual_pitch_potential",
        "Per-pitch potential — FBP, CHP, CBP, SLP, SIP, SPP, CTP, FOP, CCP, SCP, KCP, KNP, PIT, VELO, Slot, STM",
    ),
    # ── Fielding ────────────────────────────────────────────────────────────
    LieSpec(
        "_organization_-_roster_fielding_stats.csv",
        "lie_fielding_stats",
        "Fielding — G, GS, TC, A, PO, E, DP, PCT, RNG, ZR, EFF, SBA, RTO, RTO%, IP, PB, CERA, FRM, ARM",
    ),
    LieSpec(
        "_organization_-_roster_fielding_ratings.csv",
        "lie_fielding_ratings",
        "Fielding ratings — C ABI, C ARM, IF RNG, IF ERR, IF ARM, TDP, OF RNG, OF ERR, OF ARM",
    ),
    LieSpec(
        "_organization_-_roster_position_ratings.csv",
        "lie_position_ratings",
        "Per-position ratings — DEF, P, C, 1B, 2B, 3B, SS, LF, CF, RF",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# File discovery — org-agnostic suffix match
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_lie_path(ie_dir: Path, suffix: str) -> Path | None:
    """Locate the IE file in ``ie_dir`` whose name ends with ``suffix``.

    Mirrors ``_resolve_ie_path`` in ``audit/reconcile.py`` — the same
    org-agnostic glob lets us share specs across saves.
    """
    if not ie_dir.exists():
        return None
    matches = sorted(ie_dir.glob(f"*{suffix}"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        console.print(
            f"  [yellow]ambiguous IE file for suffix {suffix!r}: "
            f"{[m.name for m in matches]}[/yellow]"
        )
        return None
    return None


def _q(path: Path) -> str:
    return f"'{path.as_posix()}'"


# ─────────────────────────────────────────────────────────────────────────────
# Ingester
# ─────────────────────────────────────────────────────────────────────────────


def _ingest_one_lie_table(
    con: duckdb.DuckDBPyConnection,
    spec: LieSpec,
    csv_path: Path,
) -> int:
    """DROP + recreate one ``lie_*`` table from its CSV. Returns row count.

    Loads with ``all_varchar=true`` to preserve OOTP's display formatting
    verbatim — ``.250``, ``9.1%``, ``$25 000 000``, ``170+``, ``-``.
    Downstream parsed views ``TRY_CAST`` the values they need.

    Stamps ``ingest_ts`` and ``source_file`` for provenance.
    """
    table = spec.lie_table
    csv_lit = _q(csv_path)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(
        f"""
        CREATE TABLE {table} AS
        SELECT *,
            NOW()                       AS ingest_ts,
            '{csv_path.name}'           AS source_file
        FROM read_csv_auto(
            {csv_lit},
            sample_size=-1,
            all_varchar=true,
            ignore_errors=true
        )
        """
    )
    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return n


def build_l_ie(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Ingest all 21 import_export CSVs into ``lie_*`` tables + build the
    parsed unified views.

    Best-effort + skip-on-missing — a save without IE exports gets no
    ``lie_*`` tables; ``v_lie_player_display_*`` views are built as empty
    so downstream LEFT JOINs return NULL and COALESCE falls through.

    Stamps ``_diamond_settings.l_ie.*`` with provenance (timestamp,
    table count, per-file row counts, source dir).

    Returns ``{lie_table_name: row_count}``.
    """
    ie_dir = save.import_export_dir
    rows_per_table: dict[str, int] = {}
    missing: list[str] = []
    files: dict[str, dict] = {}

    if not ie_dir.exists():
        if verbose:
            console.print(
                f"  [yellow]import_export dir not found: {ie_dir}[/yellow]"
            )
        _ensure_lie_views(con)
        return rows_per_table

    for spec in LIE_CATALOG:
        path = _resolve_lie_path(ie_dir, spec.suffix)
        if path is None:
            missing.append(spec.suffix)
            if verbose:
                console.print(
                    f"  [yellow]missing IE file (skipping):[/yellow] "
                    f"*{spec.suffix}"
                )
            # Drop any stale prior-ingest table so the unified view is
            # consistent with disk state.
            con.execute(f"DROP TABLE IF EXISTS {spec.lie_table}")
            continue
        n = _ingest_one_lie_table(con, spec, path)
        rows_per_table[spec.lie_table] = n
        files[spec.lie_table] = {"source": path.name, "rows": n}
        if verbose:
            console.print(
                f"  [green]✓[/green] {spec.lie_table:<35} "
                f"[dim]{n:>5,} rows[/dim] [dim]({path.name})[/dim]"
            )

    _ensure_lie_views(con)

    # Provenance stamps
    set_setting(con, "l_ie.last_ingest_ts", datetime.utcnow().isoformat() + "Z")
    set_setting(con, "l_ie.source_dir", str(ie_dir))
    set_setting(con, "l_ie.table_count", str(len(rows_per_table)))
    set_setting(con, "l_ie.files_json", json.dumps(files))
    if missing:
        set_setting(con, "l_ie.missing_json", json.dumps(missing))
    else:
        set_setting(con, "l_ie.missing_json", "[]")

    if verbose and missing:
        console.print(
            f"  [yellow]Note:[/yellow] {len(missing)} IE file(s) missing "
            f"(see above). Routing will fall through to derivations "
            f"for those columns."
        )

    return rows_per_table


# ─────────────────────────────────────────────────────────────────────────────
# Parsed unified views — ready for COALESCE in API CTEs
# ─────────────────────────────────────────────────────────────────────────────


# A few parsing helpers reused across SELECT expressions.
#   _parse_rate(s)    →  ".250"           → 0.250
#   _parse_pct(s)     →  "9.1%"           → 9.1   (whole-percent scale)
#   _parse_int(s)     →  "100" / "1 (auto.)" → 100
#   _parse_float(s)   →  "5.4"            → 5.4
#   _parse_money(s)   →  "$28 800 000"    → 28800000
#   Any "-" / "" / "—" → NULL
def _parse_rate_sql(col: str) -> str:
    """OOTP rate stat (e.g. ``.250``, ``.302``, ``-``) → ``DOUBLE`` or NULL."""
    return (
        f"TRY_CAST(NULLIF(NULLIF(NULLIF(TRIM({col}), '-'), '—'), '') AS DOUBLE)"
    )


def _parse_pct_sql(col: str) -> str:
    """OOTP percentage display (e.g. ``9.1%``, ``50%``, ``-``) → DOUBLE on whole-percent scale or NULL."""
    return (
        f"TRY_CAST(NULLIF(NULLIF(NULLIF(REPLACE(TRIM({col}), '%', ''), '-'), '—'), '') AS DOUBLE)"
    )


def _parse_int_sql(col: str) -> str:
    """OOTP integer display (e.g. ``100``, ``-``, ``1 (auto.)``) → BIGINT or NULL.

    For ``1 (auto.)`` (option counts) we take the leading integer.
    """
    return (
        f"TRY_CAST(NULLIF(NULLIF(NULLIF(SPLIT_PART(TRIM({col}), ' ', 1), '-'), '—'), '') AS BIGINT)"
    )


def _parse_float_sql(col: str) -> str:
    """OOTP float display (e.g. ``5.4``, ``172.1``, ``-``) → DOUBLE or NULL."""
    return (
        f"TRY_CAST(NULLIF(NULLIF(NULLIF(TRIM({col}), '-'), '—'), '') AS DOUBLE)"
    )


def _parse_money_sql(col: str) -> str:
    """OOTP money display (e.g. ``$28 800 000``, ``-``) → BIGINT (dollars) or NULL.

    OOTP uses space-separated thousands and ``$`` prefix.
    """
    return (
        f"TRY_CAST(NULLIF(NULLIF(NULLIF(REPLACE(REPLACE(REPLACE(TRIM({col}), '$', ''), ' ', ''), ',', ''), '-'), '—'), '') AS BIGINT)"
    )


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1",
        [table],
    ).fetchone()
    return row is not None


def _ensure_lie_views(con: duckdb.DuckDBPyConnection) -> None:
    """Build per-discipline unified views over the parsed L_IE stats.

    Each view is one-row-per-player with parsed-numeric columns suitable
    for ``COALESCE(ie_value, derived_value)`` in API CTEs.

    If the underlying ``lie_*`` table doesn't exist (no IE export), the
    view is created with the same column shape but empty — keeps
    downstream LEFT JOIN code path-stable.
    """
    # ── Batting display: combines stats_1 + stats_2 + superstats_1 ─────────
    bs1 = _table_exists(con, "lie_batting_stats_1")
    bs2 = _table_exists(con, "lie_batting_stats_2")
    bss1 = _table_exists(con, "lie_batting_superstats_1")

    if bs1 or bs2 or bss1:
        # Build a UNION'd CTE selecting (player_id, fields...) per source.
        # We construct the view per-source-exists to avoid SELECTing from
        # a non-existent table.
        selects = []
        if bs1:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    {_parse_rate_sql('"AVG"')}                  AS avg_ie,
                    {_parse_rate_sql('"OBP"')}                  AS obp_ie,
                    {_parse_rate_sql('"SLG"')}                  AS slg_ie,
                    {_parse_rate_sql('"ISO"')}                  AS iso_ie,
                    {_parse_rate_sql('"OPS"')}                  AS ops_ie,
                    {_parse_int_sql('"OPS+"')}                  AS ops_plus_ie,
                    {_parse_rate_sql('"BABIP"')}                AS babip_ie,
                    {_parse_float_sql('"WAR"')}                 AS war_ie,
                    NULL::DOUBLE                                AS woba_ie,
                    NULL::DOUBLE                                AS wpa_ie,
                    NULL::DOUBLE                                AS bb_pct_ie,
                    NULL::DOUBLE                                AS k_pct_ie,
                    NULL::DOUBLE                                AS rc_ie,
                    NULL::DOUBLE                                AS rc27_ie,
                    NULL::DOUBLE                                AS pi_per_pa_ie,
                    NULL::DOUBLE                                AS bip_ie,
                    NULL::DOUBLE                                AS gb_fb_ie,
                    NULL::DOUBLE                                AS ld_pct_ie,
                    NULL::DOUBLE                                AS gb_pct_ie,
                    NULL::DOUBLE                                AS fb_pct_ie,
                    NULL::BIGINT                                AS iffb_ie,
                    NULL::DOUBLE                                AS hr_fb_ie,
                    NULL::DOUBLE                                AS ifh_pct_ie,
                    NULL::DOUBLE                                AS buh_pct_ie,
                    NULL::DOUBLE                                AS pull_pct_ie,
                    NULL::DOUBLE                                AS cent_pct_ie,
                    NULL::DOUBLE                                AS oppo_pct_ie,
                    NULL::DOUBLE                                AS soft_pct_ie,
                    NULL::DOUBLE                                AS avg_pct_ie,
                    NULL::DOUBLE                                AS solid_pct_ie,
                    NULL::DOUBLE                                AS ev_ie,
                    NULL::DOUBLE                                AS mev_ie,
                    NULL::DOUBLE                                AS la_ie,
                    NULL::BIGINT                                AS bar_ie,
                    NULL::DOUBLE                                AS bar_pct_ie,
                    NULL::BIGINT                                AS hhi_ie,
                    NULL::DOUBLE                                AS hhi_pct_ie,
                    NULL::DOUBLE                                AS xba_ie,
                    NULL::DOUBLE                                AS xslg_ie,
                    NULL::DOUBLE                                AS xwoba_ie
                FROM lie_batting_stats_1
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )
        if bs2:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    NULL::DOUBLE                                AS avg_ie,
                    NULL::DOUBLE                                AS obp_ie,
                    NULL::DOUBLE                                AS slg_ie,
                    {_parse_rate_sql('"ISO"')}                  AS iso_ie,
                    NULL::DOUBLE                                AS ops_ie,
                    NULL::BIGINT                                AS ops_plus_ie,
                    NULL::DOUBLE                                AS babip_ie,
                    NULL::DOUBLE                                AS war_ie,
                    {_parse_rate_sql('"wOBA"')}                 AS woba_ie,
                    {_parse_float_sql('"WPA"')}                 AS wpa_ie,
                    {_parse_pct_sql('"BB%"')}                   AS bb_pct_ie,
                    {_parse_pct_sql('"K%"')}                    AS k_pct_ie,
                    {_parse_float_sql('"RC"')}                  AS rc_ie,
                    {_parse_float_sql('"RC/27"')}               AS rc27_ie,
                    {_parse_float_sql('"PI/PA"')}               AS pi_per_pa_ie,
                    NULL::DOUBLE                                AS bip_ie,
                    NULL::DOUBLE                                AS gb_fb_ie,
                    NULL::DOUBLE                                AS ld_pct_ie,
                    NULL::DOUBLE                                AS gb_pct_ie,
                    NULL::DOUBLE                                AS fb_pct_ie,
                    NULL::BIGINT                                AS iffb_ie,
                    NULL::DOUBLE                                AS hr_fb_ie,
                    NULL::DOUBLE                                AS ifh_pct_ie,
                    NULL::DOUBLE                                AS buh_pct_ie,
                    NULL::DOUBLE                                AS pull_pct_ie,
                    NULL::DOUBLE                                AS cent_pct_ie,
                    NULL::DOUBLE                                AS oppo_pct_ie,
                    NULL::DOUBLE                                AS soft_pct_ie,
                    NULL::DOUBLE                                AS avg_pct_ie,
                    NULL::DOUBLE                                AS solid_pct_ie,
                    NULL::DOUBLE                                AS ev_ie,
                    NULL::DOUBLE                                AS mev_ie,
                    NULL::DOUBLE                                AS la_ie,
                    NULL::BIGINT                                AS bar_ie,
                    NULL::DOUBLE                                AS bar_pct_ie,
                    NULL::BIGINT                                AS hhi_ie,
                    NULL::DOUBLE                                AS hhi_pct_ie,
                    NULL::DOUBLE                                AS xba_ie,
                    NULL::DOUBLE                                AS xslg_ie,
                    NULL::DOUBLE                                AS xwoba_ie
                FROM lie_batting_stats_2
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )
        if bss1:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    NULL::DOUBLE                                AS avg_ie,
                    NULL::DOUBLE                                AS obp_ie,
                    NULL::DOUBLE                                AS slg_ie,
                    NULL::DOUBLE                                AS iso_ie,
                    NULL::DOUBLE                                AS ops_ie,
                    NULL::BIGINT                                AS ops_plus_ie,
                    NULL::DOUBLE                                AS babip_ie,
                    NULL::DOUBLE                                AS war_ie,
                    NULL::DOUBLE                                AS woba_ie,
                    NULL::DOUBLE                                AS wpa_ie,
                    NULL::DOUBLE                                AS bb_pct_ie,
                    NULL::DOUBLE                                AS k_pct_ie,
                    NULL::DOUBLE                                AS rc_ie,
                    NULL::DOUBLE                                AS rc27_ie,
                    NULL::DOUBLE                                AS pi_per_pa_ie,
                    {_parse_int_sql('"BIP"')}::DOUBLE           AS bip_ie,
                    {_parse_float_sql('"GB/FB"')}               AS gb_fb_ie,
                    {_parse_pct_sql('"LD%"')}                   AS ld_pct_ie,
                    {_parse_pct_sql('"GB%"')}                   AS gb_pct_ie,
                    {_parse_pct_sql('"FB%"')}                   AS fb_pct_ie,
                    {_parse_int_sql('"IFFB"')}                  AS iffb_ie,
                    {_parse_pct_sql('"HR/FB"')}                 AS hr_fb_ie,
                    {_parse_pct_sql('"IFH%"')}                  AS ifh_pct_ie,
                    {_parse_pct_sql('"BUH%"')}                  AS buh_pct_ie,
                    {_parse_pct_sql('"Pull%"')}                 AS pull_pct_ie,
                    {_parse_pct_sql('"Cent%"')}                 AS cent_pct_ie,
                    {_parse_pct_sql('"Oppo%"')}                 AS oppo_pct_ie,
                    {_parse_pct_sql('"Soft%"')}                 AS soft_pct_ie,
                    {_parse_pct_sql('"Avg%"')}                  AS avg_pct_ie,
                    {_parse_pct_sql('"Solid%"')}                AS solid_pct_ie,
                    {_parse_float_sql('"EV"')}                  AS ev_ie,
                    {_parse_float_sql('"mEV"')}                 AS mev_ie,
                    {_parse_float_sql('"LA"')}                  AS la_ie,
                    {_parse_int_sql('"BAR"')}                   AS bar_ie,
                    {_parse_pct_sql('"BAR%"')}                  AS bar_pct_ie,
                    {_parse_int_sql('"HHi"')}                   AS hhi_ie,
                    {_parse_pct_sql('"HHi%"')}                  AS hhi_pct_ie,
                    {_parse_rate_sql('"xBA"')}                  AS xba_ie,
                    {_parse_rate_sql('"xSLG"')}                 AS xslg_ie,
                    {_parse_rate_sql('"xwOBA"')}                AS xwoba_ie
                FROM lie_batting_superstats_1
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )

        union_sql = " UNION ALL ".join(selects)
        # Collapse via MAX (one source-only value wins; multiple sources for the
        # same field — e.g. ISO appears in both stats_1 and stats_2 — agree
        # bit-for-bit because they come from the same OOTP export).
        con.execute(
            f"""
            CREATE OR REPLACE VIEW v_lie_player_batting_display AS
            SELECT
                player_id,
                MAX(avg_ie)        AS avg_ie,
                MAX(obp_ie)        AS obp_ie,
                MAX(slg_ie)        AS slg_ie,
                MAX(iso_ie)        AS iso_ie,
                MAX(ops_ie)        AS ops_ie,
                MAX(ops_plus_ie)   AS ops_plus_ie,
                MAX(babip_ie)      AS babip_ie,
                MAX(war_ie)        AS war_ie,
                MAX(woba_ie)       AS woba_ie,
                MAX(wpa_ie)        AS wpa_ie,
                MAX(bb_pct_ie)     AS bb_pct_ie,
                MAX(k_pct_ie)      AS k_pct_ie,
                MAX(rc_ie)         AS rc_ie,
                MAX(rc27_ie)       AS rc27_ie,
                MAX(pi_per_pa_ie)  AS pi_per_pa_ie,
                MAX(bip_ie)        AS bip_ie,
                MAX(gb_fb_ie)      AS gb_fb_ie,
                MAX(ld_pct_ie)     AS ld_pct_ie,
                MAX(gb_pct_ie)     AS gb_pct_ie,
                MAX(fb_pct_ie)     AS fb_pct_ie,
                MAX(iffb_ie)       AS iffb_ie,
                MAX(hr_fb_ie)      AS hr_fb_ie,
                MAX(ifh_pct_ie)    AS ifh_pct_ie,
                MAX(buh_pct_ie)    AS buh_pct_ie,
                MAX(pull_pct_ie)   AS pull_pct_ie,
                MAX(cent_pct_ie)   AS cent_pct_ie,
                MAX(oppo_pct_ie)   AS oppo_pct_ie,
                MAX(soft_pct_ie)   AS soft_pct_ie,
                MAX(avg_pct_ie)    AS avg_pct_ie,
                MAX(solid_pct_ie)  AS solid_pct_ie,
                MAX(ev_ie)         AS ev_ie,
                MAX(mev_ie)        AS mev_ie,
                MAX(la_ie)         AS la_ie,
                MAX(bar_ie)        AS bar_ie,
                MAX(bar_pct_ie)    AS bar_pct_ie,
                MAX(hhi_ie)        AS hhi_ie,
                MAX(hhi_pct_ie)    AS hhi_pct_ie,
                MAX(xba_ie)        AS xba_ie,
                MAX(xslg_ie)       AS xslg_ie,
                MAX(xwoba_ie)      AS xwoba_ie
            FROM ({union_sql})
            GROUP BY player_id
            """
        )
    else:
        # Empty stub view — same shape, zero rows.
        con.execute(
            """
            CREATE OR REPLACE VIEW v_lie_player_batting_display AS
            SELECT
                NULL::BIGINT AS player_id,
                NULL::DOUBLE AS avg_ie, NULL::DOUBLE AS obp_ie, NULL::DOUBLE AS slg_ie,
                NULL::DOUBLE AS iso_ie, NULL::DOUBLE AS ops_ie, NULL::BIGINT AS ops_plus_ie,
                NULL::DOUBLE AS babip_ie, NULL::DOUBLE AS war_ie, NULL::DOUBLE AS woba_ie,
                NULL::DOUBLE AS wpa_ie, NULL::DOUBLE AS bb_pct_ie, NULL::DOUBLE AS k_pct_ie,
                NULL::DOUBLE AS rc_ie, NULL::DOUBLE AS rc27_ie, NULL::DOUBLE AS pi_per_pa_ie,
                NULL::DOUBLE AS bip_ie, NULL::DOUBLE AS gb_fb_ie, NULL::DOUBLE AS ld_pct_ie,
                NULL::DOUBLE AS gb_pct_ie, NULL::DOUBLE AS fb_pct_ie, NULL::BIGINT AS iffb_ie,
                NULL::DOUBLE AS hr_fb_ie, NULL::DOUBLE AS ifh_pct_ie, NULL::DOUBLE AS buh_pct_ie,
                NULL::DOUBLE AS pull_pct_ie, NULL::DOUBLE AS cent_pct_ie, NULL::DOUBLE AS oppo_pct_ie,
                NULL::DOUBLE AS soft_pct_ie, NULL::DOUBLE AS avg_pct_ie, NULL::DOUBLE AS solid_pct_ie,
                NULL::DOUBLE AS ev_ie, NULL::DOUBLE AS mev_ie, NULL::DOUBLE AS la_ie,
                NULL::BIGINT AS bar_ie, NULL::DOUBLE AS bar_pct_ie, NULL::BIGINT AS hhi_ie,
                NULL::DOUBLE AS hhi_pct_ie, NULL::DOUBLE AS xba_ie, NULL::DOUBLE AS xslg_ie,
                NULL::DOUBLE AS xwoba_ie
            WHERE FALSE
            """
        )

    # ── Pitching display: combines stats_1 + stats_2 + superstats_1 ────────
    ps1 = _table_exists(con, "lie_pitching_stats_1")
    ps2 = _table_exists(con, "lie_pitching_stats_2")
    pss1 = _table_exists(con, "lie_pitching_superstats_1")

    if ps1 or ps2 or pss1:
        selects = []
        if ps1:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    {_parse_float_sql('"ERA"')}                 AS era_ie,
                    {_parse_rate_sql('"AVG"')}                  AS avg_against_ie,
                    {_parse_rate_sql('"BABIP"')}                AS babip_ie,
                    {_parse_float_sql('"WHIP"')}                AS whip_ie,
                    {_parse_float_sql('"HR/9"')}                AS hr9_ie,
                    {_parse_float_sql('"BB/9"')}                AS bb9_ie,
                    {_parse_float_sql('"K/9"')}                 AS k9_ie,
                    {_parse_float_sql('"K/BB"')}                AS k_bb_ie,
                    {_parse_int_sql('"ERA+"')}                  AS era_plus_ie,
                    {_parse_float_sql('"FIP"')}                 AS fip_ie,
                    {_parse_float_sql('"WAR"')}                 AS war_ie,
                    NULL::DOUBLE                                AS siera_ie,
                    NULL::DOUBLE                                AS wpa_ie,
                    NULL::DOUBLE                                AS bip_ie,
                    NULL::DOUBLE                                AS xera_ie,
                    NULL::DOUBLE                                AS xwoba_ie,
                    NULL::DOUBLE                                AS xba_ie,
                    NULL::DOUBLE                                AS xslg_ie,
                    NULL::DOUBLE                                AS gb_pct_ie,
                    NULL::DOUBLE                                AS fb_pct_ie,
                    NULL::DOUBLE                                AS ld_pct_ie,
                    NULL::DOUBLE                                AS hr_fb_ie,
                    NULL::DOUBLE                                AS soft_pct_ie,
                    NULL::DOUBLE                                AS med_pct_ie,
                    NULL::DOUBLE                                AS solid_pct_ie,
                    NULL::DOUBLE                                AS ev_ie
                FROM lie_pitching_stats_1
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )
        if ps2:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    NULL::DOUBLE                                AS era_ie,
                    NULL::DOUBLE                                AS avg_against_ie,
                    NULL::DOUBLE                                AS babip_ie,
                    NULL::DOUBLE                                AS whip_ie,
                    NULL::DOUBLE                                AS hr9_ie,
                    NULL::DOUBLE                                AS bb9_ie,
                    NULL::DOUBLE                                AS k9_ie,
                    NULL::DOUBLE                                AS k_bb_ie,
                    NULL::BIGINT                                AS era_plus_ie,
                    NULL::DOUBLE                                AS fip_ie,
                    NULL::DOUBLE                                AS war_ie,
                    {_parse_float_sql('"SIERA"')}               AS siera_ie,
                    {_parse_float_sql('"WPA"')}                 AS wpa_ie,
                    NULL::DOUBLE                                AS bip_ie,
                    NULL::DOUBLE                                AS xera_ie,
                    NULL::DOUBLE                                AS xwoba_ie,
                    NULL::DOUBLE                                AS xba_ie,
                    NULL::DOUBLE                                AS xslg_ie,
                    NULL::DOUBLE                                AS gb_pct_ie,
                    NULL::DOUBLE                                AS fb_pct_ie,
                    NULL::DOUBLE                                AS ld_pct_ie,
                    NULL::DOUBLE                                AS hr_fb_ie,
                    NULL::DOUBLE                                AS soft_pct_ie,
                    NULL::DOUBLE                                AS med_pct_ie,
                    NULL::DOUBLE                                AS solid_pct_ie,
                    NULL::DOUBLE                                AS ev_ie
                FROM lie_pitching_stats_2
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )
        if pss1:
            selects.append(
                f"""
                SELECT
                    TRY_CAST("ID" AS BIGINT)                    AS player_id,
                    NULL::DOUBLE                                AS era_ie,
                    NULL::DOUBLE                                AS avg_against_ie,
                    NULL::DOUBLE                                AS babip_ie,
                    NULL::DOUBLE                                AS whip_ie,
                    NULL::DOUBLE                                AS hr9_ie,
                    NULL::DOUBLE                                AS bb9_ie,
                    NULL::DOUBLE                                AS k9_ie,
                    NULL::DOUBLE                                AS k_bb_ie,
                    NULL::BIGINT                                AS era_plus_ie,
                    NULL::DOUBLE                                AS fip_ie,
                    NULL::DOUBLE                                AS war_ie,
                    NULL::DOUBLE                                AS siera_ie,
                    NULL::DOUBLE                                AS wpa_ie,
                    {_parse_int_sql('"BIP"')}::DOUBLE           AS bip_ie,
                    {_parse_float_sql('"xERA"')}                AS xera_ie,
                    {_parse_rate_sql('"xwOBA"')}                AS xwoba_ie,
                    {_parse_rate_sql('"xBA"')}                  AS xba_ie,
                    {_parse_rate_sql('"xSLG"')}                 AS xslg_ie,
                    {_parse_pct_sql('"GB%"')}                   AS gb_pct_ie,
                    {_parse_pct_sql('"FB%"')}                   AS fb_pct_ie,
                    {_parse_pct_sql('"LD%"')}                   AS ld_pct_ie,
                    {_parse_pct_sql('"HR/FB"')}                 AS hr_fb_ie,
                    {_parse_pct_sql('"Soft%"')}                 AS soft_pct_ie,
                    {_parse_pct_sql('"Med%"')}                  AS med_pct_ie,
                    {_parse_pct_sql('"Solid%"')}                AS solid_pct_ie,
                    {_parse_float_sql('"EV"')}                  AS ev_ie
                FROM lie_pitching_superstats_1
                WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
                """
            )

        union_sql = " UNION ALL ".join(selects)
        con.execute(
            f"""
            CREATE OR REPLACE VIEW v_lie_player_pitching_display AS
            SELECT
                player_id,
                MAX(era_ie)         AS era_ie,
                MAX(avg_against_ie) AS avg_against_ie,
                MAX(babip_ie)       AS babip_ie,
                MAX(whip_ie)        AS whip_ie,
                MAX(hr9_ie)         AS hr9_ie,
                MAX(bb9_ie)         AS bb9_ie,
                MAX(k9_ie)          AS k9_ie,
                MAX(k_bb_ie)        AS k_bb_ie,
                MAX(era_plus_ie)    AS era_plus_ie,
                MAX(fip_ie)         AS fip_ie,
                MAX(war_ie)         AS war_ie,
                MAX(siera_ie)       AS siera_ie,
                MAX(wpa_ie)         AS wpa_ie,
                MAX(bip_ie)         AS bip_ie,
                MAX(xera_ie)        AS xera_ie,
                MAX(xwoba_ie)       AS xwoba_ie,
                MAX(xba_ie)         AS xba_ie,
                MAX(xslg_ie)        AS xslg_ie,
                MAX(gb_pct_ie)      AS gb_pct_ie,
                MAX(fb_pct_ie)      AS fb_pct_ie,
                MAX(ld_pct_ie)      AS ld_pct_ie,
                MAX(hr_fb_ie)       AS hr_fb_ie,
                MAX(soft_pct_ie)    AS soft_pct_ie,
                MAX(med_pct_ie)     AS med_pct_ie,
                MAX(solid_pct_ie)   AS solid_pct_ie,
                MAX(ev_ie)          AS ev_ie
            FROM ({union_sql})
            GROUP BY player_id
            """
        )
    else:
        con.execute(
            """
            CREATE OR REPLACE VIEW v_lie_player_pitching_display AS
            SELECT
                NULL::BIGINT AS player_id,
                NULL::DOUBLE AS era_ie, NULL::DOUBLE AS avg_against_ie, NULL::DOUBLE AS babip_ie,
                NULL::DOUBLE AS whip_ie, NULL::DOUBLE AS hr9_ie, NULL::DOUBLE AS bb9_ie,
                NULL::DOUBLE AS k9_ie, NULL::DOUBLE AS k_bb_ie, NULL::BIGINT AS era_plus_ie,
                NULL::DOUBLE AS fip_ie, NULL::DOUBLE AS war_ie, NULL::DOUBLE AS siera_ie,
                NULL::DOUBLE AS wpa_ie, NULL::DOUBLE AS bip_ie, NULL::DOUBLE AS xera_ie,
                NULL::DOUBLE AS xwoba_ie, NULL::DOUBLE AS xba_ie, NULL::DOUBLE AS xslg_ie,
                NULL::DOUBLE AS gb_pct_ie, NULL::DOUBLE AS fb_pct_ie, NULL::DOUBLE AS ld_pct_ie,
                NULL::DOUBLE AS hr_fb_ie, NULL::DOUBLE AS soft_pct_ie, NULL::DOUBLE AS med_pct_ie,
                NULL::DOUBLE AS solid_pct_ie, NULL::DOUBLE AS ev_ie
            WHERE FALSE
            """
        )

    # ── Fielding display ────────────────────────────────────────────────────
    if _table_exists(con, "lie_fielding_stats"):
        con.execute(
            f"""
            CREATE OR REPLACE VIEW v_lie_player_fielding_display AS
            SELECT
                TRY_CAST("ID" AS BIGINT)                    AS player_id,
                {_parse_int_sql('"G"')}                     AS g_ie,
                {_parse_int_sql('"GS"')}                    AS gs_ie,
                {_parse_int_sql('"TC"')}                    AS tc_ie,
                {_parse_int_sql('"A"')}                     AS a_ie,
                {_parse_int_sql('"PO"')}                    AS po_ie,
                {_parse_int_sql('"E"')}                     AS e_ie,
                {_parse_int_sql('"DP"')}                    AS dp_ie,
                {_parse_rate_sql('"PCT"')}                  AS pct_ie,
                {_parse_float_sql('"RNG"')}                 AS rng_ie,
                {_parse_float_sql('"ZR"')}                  AS zr_ie,
                {_parse_pct_sql('"EFF"')}                   AS eff_ie,
                {_parse_int_sql('"SBA"')}                   AS sba_ie,
                {_parse_int_sql('"RTO"')}                   AS rto_ie,
                {_parse_pct_sql('"RTO%"')}                  AS rto_pct_ie,
                {_parse_float_sql('"IP"')}                  AS ip_ie,
                {_parse_int_sql('"PB"')}                    AS pb_ie,
                {_parse_float_sql('"CERA"')}                AS cera_ie,
                {_parse_int_sql('"FRM"')}                   AS frm_ie,
                {_parse_int_sql('"ARM"')}                   AS arm_ie
            FROM lie_fielding_stats
            WHERE TRY_CAST("ID" AS BIGINT) IS NOT NULL
            """
        )
    else:
        con.execute(
            """
            CREATE OR REPLACE VIEW v_lie_player_fielding_display AS
            SELECT
                NULL::BIGINT AS player_id,
                NULL::BIGINT AS g_ie, NULL::BIGINT AS gs_ie, NULL::BIGINT AS tc_ie,
                NULL::BIGINT AS a_ie, NULL::BIGINT AS po_ie, NULL::BIGINT AS e_ie,
                NULL::BIGINT AS dp_ie, NULL::DOUBLE AS pct_ie, NULL::DOUBLE AS rng_ie,
                NULL::DOUBLE AS zr_ie, NULL::DOUBLE AS eff_ie, NULL::BIGINT AS sba_ie,
                NULL::BIGINT AS rto_ie, NULL::DOUBLE AS rto_pct_ie, NULL::DOUBLE AS ip_ie,
                NULL::BIGINT AS pb_ie, NULL::DOUBLE AS cera_ie, NULL::BIGINT AS frm_ie,
                NULL::BIGINT AS arm_ie
            WHERE FALSE
            """
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provenance helper
# ─────────────────────────────────────────────────────────────────────────────


def get_lie_provenance(con: duckdb.DuckDBPyConnection) -> dict:
    """Return a dict describing the L_IE ingest state.

    Used by ``/api/admin`` introspection and by smoke tests.
    """
    from diamond.schema.build import get_setting

    return {
        "last_ingest_ts": get_setting(con, "l_ie.last_ingest_ts"),
        "source_dir": get_setting(con, "l_ie.source_dir"),
        "table_count": int(get_setting(con, "l_ie.table_count", "0") or 0),
        "files": json.loads(get_setting(con, "l_ie.files_json", "{}") or "{}"),
        "missing": json.loads(get_setting(con, "l_ie.missing_json", "[]") or "[]"),
    }
