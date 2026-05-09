"""L_REF — per-save reference data layer (D26 + D27).

Reads from the OOTP install folder
``<docs>/Out of the Park Developments/OOTP Baseball 27/`` into per-save
``lref_*`` tables. Three tiers:

  1. ``misc/`` — analytical lookup tables OOTP itself uses at sim time.
     ``xwoba_table.txt`` / ``xba_table.txt`` / ``xslg_table.txt`` (LA × EV
     grids), ``xiso_table.txt`` (6-zone Statcast LSA classifier),
     ``re288_table.txt`` (RE by outs/bases/count), ``li_table.txt`` (Tango
     leverage index), ``wpa_table.txt`` (win probability), ``pi_table.txt``
     (pitch-type impact). Reading these directly guarantees our calc
     numbers match the in-game UI exactly.
  2. ``database/`` — historical baselines + park factors. ``pt_ballparks``
     (240 modern parks with 7-segment dimensions + LH/RH PFs),
     ``era_ballparks`` (3,105 historical park-seasons 1871-2025),
     ``era_stats`` / ``era_stats_minors`` (82-col league averages per era),
     ``era_modifiers`` / ``era_fielding`` / ``total_modifiers`` (per-year
     talent multipliers + position FLD baselines), ``financials`` (salary
     bracket engine), ``weather``.
  3. ``stats/`` — crosswalks + history. ``Master.csv`` (24,747-row
     OOTP↔Lahman crosswalk; replaces Chadwick), ``MiLBMaster.csv``
     (29MB minor-league master), ``Teams.csv`` / ``MiLBLeagues.csv`` /
     ``MiLBTeams.csv``, ``EOSRosters.csv`` / ``ODRosters.csv``,
     ``UniNumbers.csv``, ``SeriesPost.csv``. Plus ``database/players.csv``
     (231-col seed pool).

Per **D27**, L_REF is **per-save and frozen at first ingest**. ``ensure_lref``
runs once on the first ``diamond ingest`` and stamps the warehouse's
``_diamond_settings.lref.*`` keys with provenance (mtime + SHA1 + ingest
timestamp + source path + OOTP version + per-table row counts). Subsequent
ingests detect the freeze and skip silently. Refresh is opt-in via
``diamond ingest --refresh-lref``, which prints a diff vs the frozen
snapshot before overwriting. This mirrors OOTP's own engine convention
(save reference data is captured at save creation; install-folder
patches don't retroactively rewrite running saves).

Slice 1 (this module): ingest + freeze + provenance. The actual *use*
of these tables (xwoba JOINs into ``f_pa_event``, era_ballparks JOINs
into ``_park_factor_resolved``, Master.csv crosswalk swap, etc.) lands
in subsequent slices — see ``docs/BACKLOG.md`` "L_REF reference layer".

Tier-aware header strategies:
  - ``HeaderStyle.AUTO`` — plain CSV with header row; ``read_csv_auto``.
  - ``HeaderStyle.COMMENT`` — first line is ``//col1,col2,...``; we strip
    the ``//`` prefix and pass the cleaned names via ``column_names=[...]``
    with ``skip=1``. Used by ``re288_table``, ``xiso_table``, ``weather``.
  - ``HeaderStyle.HEADERLESS`` — no header at all; DuckDB names columns
    ``column0``, ``column1``, etc. Slice 2 will rename when it actually
    uses them. Used by ``li_table``, ``wpa_table``, ``pi_table``,
    ``total_modifiers``, ``EOSRosters``, ``ODRosters``.

All tables are loaded with ``all_varchar=true`` for safety — these are
reference grids with mixed-type "blank where insufficient data" cells
that defeat type inference. Slice 2 explicitly casts on JOIN.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb
from rich.console import Console

from diamond.config import OOTP_SAVED_GAMES
from diamond.schema.build import get_setting, init_admin_tables, set_setting

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────────────────────


class HeaderStyle(str, Enum):
    """How to interpret the first line of a reference file."""

    AUTO = "auto"            # plain CSV with header
    COMMENT = "comment"      # //-prefixed header row
    HEADERLESS = "headerless"  # no header; DuckDB names cols positionally


@dataclass(frozen=True)
class LRefSpec:
    """One reference-file → warehouse-table mapping."""

    source_rel: str          # path under the OOTP install root, posix-style
    lref_table: str          # destination table name (must start with ``lref_``)
    header: HeaderStyle
    tier: str                # "misc" | "database" | "stats" — for grouping in logs
    delim: str = ","
    note: str = ""           # one-liner describing what's in the file


# Order matters only for log grouping; ingest is one-shot.
LREF_CATALOG: tuple[LRefSpec, ...] = (
    # ── Tier 1: misc/ analytical lookup tables ─────────────────────────────
    LRefSpec(
        "misc/xwoba_table.txt", "lref_xwoba_table", HeaderStyle.AUTO, "misc",
        note="xwOBA by (launch angle, exit velocity) — wide grid",
    ),
    LRefSpec(
        "misc/xba_table.txt", "lref_xba_table", HeaderStyle.AUTO, "misc",
        note="xBA by (launch angle, exit velocity) — wide grid",
    ),
    LRefSpec(
        "misc/xslg_table.txt", "lref_xslg_table", HeaderStyle.AUTO, "misc",
        note="xSLG by (launch angle, exit velocity) — wide grid",
    ),
    LRefSpec(
        "misc/xiso_table.txt", "lref_xiso_table", HeaderStyle.COMMENT, "misc",
        note="6-zone Statcast classifier (launch_speed_angle × LSA bucket)",
    ),
    LRefSpec(
        "misc/re288_table.txt", "lref_re288_table", HeaderStyle.COMMENT, "misc",
        note="Run expectancy by (outs, bases, count) — 24 rows × 12 counts",
    ),
    LRefSpec(
        "misc/li_table.txt", "lref_li_table", HeaderStyle.HEADERLESS, "misc",
        note="Leverage index — Tango context-dependent grid",
    ),
    LRefSpec(
        "misc/wpa_table.txt", "lref_wpa_table", HeaderStyle.HEADERLESS, "misc",
        note="Win probability — quoted CSV, 432-row context grid",
    ),
    LRefSpec(
        "misc/pi_table.txt", "lref_pi_table", HeaderStyle.HEADERLESS, "misc",
        note="Pitch-type impact — 3 rows (FB/BR/OFF) × 17 cols",
    ),
    # ── Tier 2: database/ baselines + park factors ─────────────────────────
    LRefSpec(
        "database/pt_ballparks.txt", "lref_pt_ballparks", HeaderStyle.AUTO, "database",
        note="240 modern parks with 7-segment dimensions + LH/RH PFs",
    ),
    LRefSpec(
        "database/era_ballparks.txt", "lref_era_ballparks", HeaderStyle.AUTO, "database",
        note="3,105 historical park-seasons 1871-2025 with LH/RH splits",
    ),
    LRefSpec(
        "database/era_stats.txt", "lref_era_stats", HeaderStyle.AUTO, "database",
        note="MLB league averages 1870-2025 (82 columns)",
    ),
    LRefSpec(
        "database/era_stats_minors.txt", "lref_era_stats_minors", HeaderStyle.AUTO, "database",
        note="MiLB league averages by (league, year) — 47 columns",
    ),
    LRefSpec(
        "database/era_modifiers.txt", "lref_era_modifiers", HeaderStyle.AUTO, "database",
        note="Per-year talent multipliers (Contact / Power / Eye / etc.)",
    ),
    LRefSpec(
        "database/era_fielding.txt", "lref_era_fielding", HeaderStyle.AUTO, "database",
        note="Per-year position FLD baselines (PO+A+DP)/G by position",
    ),
    LRefSpec(
        "database/total_modifiers.txt", "lref_total_modifiers", HeaderStyle.HEADERLESS, "database",
        note="Per-year aggregate talent/run-environment multipliers (headerless)",
    ),
    LRefSpec(
        "database/financials.txt", "lref_financials", HeaderStyle.AUTO, "database",
        note="Salary-bracket engine: per-year coefficients + tier prices",
    ),
    LRefSpec(
        "database/weather.txt", "lref_weather", HeaderStyle.COMMENT, "database",
        note="Per-city monthly temp + wind speed climatology",
    ),
    LRefSpec(
        "database/players.csv", "lref_default_players", HeaderStyle.AUTO, "database",
        note="231-col default seed pool (real-history players)",
    ),
    # ── Tier 3: stats/ crosswalks + history ────────────────────────────────
    LRefSpec(
        "stats/Master.csv", "lref_master", HeaderStyle.AUTO, "stats",
        note="24,747-row OOTP↔Lahman crosswalk (replaces Chadwick)",
    ),
    LRefSpec(
        "stats/MiLBMaster.csv", "lref_milb_master", HeaderStyle.AUTO, "stats",
        note="Minor-league master (~29MB)",
    ),
    LRefSpec(
        "stats/Teams.csv", "lref_teams_history", HeaderStyle.AUTO, "stats",
        note="Team-season history (Lahman-shaped)",
    ),
    LRefSpec(
        "stats/MiLBLeagues.csv", "lref_milb_leagues", HeaderStyle.AUTO, "stats",
        note="MiLB league catalog (year, league, level)",
    ),
    LRefSpec(
        "stats/MiLBTeams.csv", "lref_milb_teams", HeaderStyle.AUTO, "stats",
        note="MiLB team-season history",
    ),
    LRefSpec(
        "stats/EOSRosters.csv", "lref_eos_rosters", HeaderStyle.HEADERLESS, "stats",
        note="End-of-season rosters (year, team, name, lahmanID; headerless)",
    ),
    LRefSpec(
        "stats/ODRosters.csv", "lref_od_rosters", HeaderStyle.HEADERLESS, "stats",
        note="Opening-day rosters (year, team, name, lahmanID; headerless)",
    ),
    LRefSpec(
        "stats/UniNumbers.csv", "lref_uni_numbers", HeaderStyle.AUTO, "stats",
        note="Uniform numbers by (LahmanPlayerID, year)",
    ),
    LRefSpec(
        "stats/SeriesPost.csv", "lref_series_post", HeaderStyle.AUTO, "stats",
        note="Postseason series results (Lahman-shaped)",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────────────────────


def ootp_install_root() -> Path:
    """Return the OOTP 27 install folder (parent of the saves root).

    ``OOTP_SAVED_GAMES`` is ``<docs>/.../OOTP Baseball 27/saved_games``;
    ``.parent`` gives us the install root that holds ``misc/``, ``database/``,
    ``stats/``, ``hof/``, ``logos/``, ``colors/``, etc.
    """
    return OOTP_SAVED_GAMES.parent


def ootp_version_from_root(root: Path) -> str:
    """Best-effort OOTP-version string from the install folder name.

    Returns e.g. ``"27"`` for ``OOTP Baseball 27`` (current target),
    or ``"unknown"`` if the folder name doesn't match the pattern.
    """
    name = root.name
    # ``OOTP Baseball 27`` / ``OOTP Baseball 28`` / etc.
    parts = name.split()
    if parts and parts[-1].isdigit():
        return parts[-1]
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Hashing + provenance helpers
# ─────────────────────────────────────────────────────────────────────────────


def _file_sha1(path: Path) -> str:
    """SHA1 of a file's full bytes. Reference files top out around 30MB."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_provenance(path: Path) -> dict[str, Any]:
    """{mtime_iso, sha1, size_bytes} for one source file."""
    stat = path.stat()
    return {
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "sha1": _file_sha1(path),
        "size_bytes": stat.st_size,
    }


def _load_files_json(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    """Read the persisted ``lref.files_json`` provenance blob, or {} if unset."""
    raw = get_setting(con, "lref.files_json", None)
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Header parsing
# ─────────────────────────────────────────────────────────────────────────────


def _read_comment_header(path: Path) -> list[str]:
    """Strip the leading ``//`` from the first line and split on commas.

    Used for the COMMENT-style files (``re288_table.txt``, ``xiso_table.txt``,
    ``weather.txt``). Names with spaces are kept verbatim — DuckDB will
    quote them on storage.

    Disambiguates duplicate names by suffixing ``_2``, ``_3``, ... — needed
    for ``weather.txt`` where ``Jan..Dec`` appears twice (temp + wind).
    """
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    cleaned = first_line.lstrip("/").strip()
    raw = [c.strip().strip('"') for c in cleaned.split(",")]
    # Drop trailing empties from accidental trailing commas
    while raw and raw[-1] == "":
        raw.pop()
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in raw:
        base = name if name else "col"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return out


def _sql_str_list(items: list[str]) -> str:
    """Render a Python list of strings as a DuckDB SQL list literal.

    e.g. ``['out', 'bases', '0-0']`` → ``"['out', 'bases', '0-0']"``.
    Embedded single quotes get escaped by doubling.
    """
    parts = []
    for s in items:
        escaped = s.replace("'", "''")
        parts.append(f"'{escaped}'")
    return "[" + ", ".join(parts) + "]"


# ─────────────────────────────────────────────────────────────────────────────
# Per-spec ingest
# ─────────────────────────────────────────────────────────────────────────────


def _q(path: Path) -> str:
    """Quote a path for embedding in a DuckDB SQL literal (forward-slash form)."""
    return f"'{path.as_posix()}'"


def _ingest_one(
    con: duckdb.DuckDBPyConnection,
    spec: LRefSpec,
    install_root: Path,
) -> int:
    """CTAS one reference file into ``lref_<table>``. Returns row count.

    Idempotent: ``CREATE OR REPLACE TABLE``.
    """
    path = install_root / spec.source_rel
    if not path.exists():
        raise FileNotFoundError(
            f"L_REF source file not found: {path} "
            f"(expected for spec {spec.lref_table!r})"
        )

    csv_lit = _q(path)
    delim_lit = repr(spec.delim)  # ',' / '\t' / etc.

    if spec.header == HeaderStyle.AUTO:
        # Plain CSV with header. ``sample_size=-1`` scans the whole file
        # for type inference, but ``all_varchar=true`` is a stronger
        # safety net for the reference grids that mix numbers + blanks.
        select = f"""
            SELECT *
            FROM read_csv_auto(
                {csv_lit},
                header=true,
                delim={delim_lit},
                all_varchar=true,
                ignore_errors=true,
                sample_size=-1
            )
        """
    elif spec.header == HeaderStyle.COMMENT:
        # First line is ``//col1,col2,...`` — strip prefix and re-supply.
        cols = _read_comment_header(path)
        col_lit = _sql_str_list(cols)
        select = f"""
            SELECT *
            FROM read_csv(
                {csv_lit},
                header=false,
                skip=1,
                delim={delim_lit},
                column_names={col_lit},
                all_varchar=true,
                ignore_errors=true
            )
        """
    elif spec.header == HeaderStyle.HEADERLESS:
        # No header at all; DuckDB will name columns ``column0``,
        # ``column1``, etc. Slice 2 will rename when it consumes them.
        select = f"""
            SELECT *
            FROM read_csv(
                {csv_lit},
                header=false,
                delim={delim_lit},
                all_varchar=true,
                ignore_errors=true
            )
        """
    else:
        raise ValueError(f"Unknown header style: {spec.header}")

    con.execute(f"CREATE OR REPLACE TABLE {spec.lref_table} AS {select}")
    n = con.execute(f"SELECT COUNT(*) FROM {spec.lref_table}").fetchone()[0]
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Freeze + diff + ensure
# ─────────────────────────────────────────────────────────────────────────────


def is_lref_frozen(con: duckdb.DuckDBPyConnection) -> bool:
    """Return True when L_REF has been ingested at least once for this save.

    The single source of truth is ``_diamond_settings.lref.frozen_at`` —
    if that's set, we treat the snapshot as authoritative regardless of
    individual ``lref_*`` table presence (a user who manually drops a
    table can still re-trigger a refresh).
    """
    return get_setting(con, "lref.frozen_at", None) is not None


def compute_lref_diff(
    con: duckdb.DuckDBPyConnection,
    install_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Compare the current install-folder files vs the frozen snapshot.

    Returns a list of change records (``{source_rel, lref_table, kind,
    old_sha1, new_sha1, ...}``) where ``kind`` is one of ``"added"``,
    ``"changed"``, ``"removed"``, ``"missing_source"``. Empty list means
    the install folder still matches the frozen vintage exactly.
    """
    if install_root is None:
        install_root = ootp_install_root()
    frozen = _load_files_json(con)
    changes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in LREF_CATALOG:
        path = install_root / spec.source_rel
        seen.add(spec.source_rel)
        if not path.exists():
            changes.append({
                "source_rel": spec.source_rel,
                "lref_table": spec.lref_table,
                "kind": "missing_source",
            })
            continue
        prov = _file_provenance(path)
        old = frozen.get(spec.source_rel)
        if old is None:
            changes.append({
                "source_rel": spec.source_rel,
                "lref_table": spec.lref_table,
                "kind": "added",
                "new_sha1": prov["sha1"],
            })
        elif old.get("sha1") != prov["sha1"]:
            changes.append({
                "source_rel": spec.source_rel,
                "lref_table": spec.lref_table,
                "kind": "changed",
                "old_sha1": old.get("sha1", ""),
                "new_sha1": prov["sha1"],
                "old_mtime": old.get("mtime", ""),
                "new_mtime": prov["mtime"],
            })
    # Files in frozen snapshot that no longer have a catalog entry — rare
    # (only happens if we drop a spec from LREF_CATALOG) but worth flagging.
    for source_rel in frozen.keys() - seen:
        changes.append({
            "source_rel": source_rel,
            "lref_table": "(unknown)",
            "kind": "removed",
        })
    return changes


def _print_diff(changes: list[dict[str, Any]]) -> None:
    """Pretty-print a diff list to the rich console."""
    if not changes:
        console.print("[green]L_REF snapshot matches install folder — no changes.[/green]")
        return
    console.print(f"[bold]L_REF diff: {len(changes)} change(s)[/bold]")
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for c in changes:
        by_kind.setdefault(c["kind"], []).append(c)
    for kind, group in by_kind.items():
        color = {
            "added": "green",
            "changed": "yellow",
            "removed": "red",
            "missing_source": "red",
        }.get(kind, "white")
        console.print(f"  [{color}]{kind}[/{color}]  ({len(group)})")
        for c in group:
            extra = ""
            if kind == "changed":
                extra = (
                    f"  sha1 {c['old_sha1'][:8]}…→{c['new_sha1'][:8]}…  "
                    f"mtime {c['old_mtime']} → {c['new_mtime']}"
                )
            elif kind == "added":
                extra = f"  sha1 {c['new_sha1'][:8]}…"
            console.print(
                f"    [dim]·[/dim] {c['source_rel']:<35}  → {c['lref_table']}{extra}"
            )


def _do_ingest(
    con: duckdb.DuckDBPyConnection,
    install_root: Path,
    *,
    only: set[str] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Internal: walk the catalog and CTAS each spec.

    ``only`` is an optional set of ``source_rel`` strings to filter on —
    used by the refresh path to avoid re-loading unchanged tables.

    Returns a dict with provenance updates suitable for stashing into
    ``_diamond_settings``.
    """
    if not install_root.exists():
        raise FileNotFoundError(
            f"OOTP install root not found: {install_root}\n"
            f"Expected layout: <docs>/Out of the Park Developments/"
            f"OOTP Baseball 27/{{misc,database,stats}}/"
        )

    files_meta: dict[str, dict[str, Any]] = _load_files_json(con) if only else {}
    rows_per_table: dict[str, int] = {}
    last_tier: str | None = None
    skipped = 0

    for spec in LREF_CATALOG:
        if only is not None and spec.source_rel not in only:
            skipped += 1
            continue
        if verbose and spec.tier != last_tier:
            console.rule(f"L_REF · {spec.tier}")
            last_tier = spec.tier

        path = install_root / spec.source_rel
        try:
            n = _ingest_one(con, spec, install_root)
        except FileNotFoundError as e:
            if verbose:
                console.print(f"  [yellow]missing source (skip):[/yellow] {spec.source_rel}")
            continue
        except Exception as e:
            if verbose:
                console.print(
                    f"  [red]✗[/red] {spec.lref_table:<32} [red]{type(e).__name__}: {e}[/red]"
                )
            raise

        rows_per_table[spec.lref_table] = n
        prov = _file_provenance(path)
        prov["rows"] = n
        files_meta[spec.source_rel] = prov

        if verbose:
            console.print(
                f"  [green]✓[/green] {spec.lref_table:<32} "
                f"[dim]{n:>10,} rows  ({prov['size_bytes']:>10,} B  "
                f"sha1 {prov['sha1'][:8]}…)[/dim]"
            )

    return {
        "rows_per_table": rows_per_table,
        "files_meta": files_meta,
        "skipped": skipped,
    }


def ensure_lref(
    con: duckdb.DuckDBPyConnection,
    install_root: Path | None = None,
    *,
    force_refresh: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Idempotently ensure L_REF is present in the warehouse.

    Per **D27**:
      - First call (warehouse has no ``lref.frozen_at`` setting): ingest
        every spec, stamp provenance, freeze.
      - Subsequent calls with ``force_refresh=False``: skip silently.
      - Subsequent calls with ``force_refresh=True``: compute diff,
        re-ingest changed files, update provenance.

    Returns a status dict::

        {"action": "frozen" | "skipped" | "refreshed",
         "rows_per_table": {...},
         "changes": [...],   # only on refresh
         "frozen_at": "2026-05-13T22:14:55"}
    """
    if install_root is None:
        install_root = ootp_install_root()

    init_admin_tables(con)
    frozen = is_lref_frozen(con)

    if frozen and not force_refresh:
        if verbose:
            stamped = get_setting(con, "lref.frozen_at", "?")
            console.print(
                f"[dim]L_REF already frozen at[/dim] {stamped} "
                f"[dim](use --refresh-lref to update)[/dim]"
            )
        return {
            "action": "skipped",
            "frozen_at": get_setting(con, "lref.frozen_at"),
            "rows_per_table": {},
        }

    if frozen and force_refresh:
        # Refresh path: only re-ingest files whose SHA1 changed.
        changes = compute_lref_diff(con, install_root)
        if verbose:
            _print_diff(changes)
        if not changes:
            return {
                "action": "skipped",
                "frozen_at": get_setting(con, "lref.frozen_at"),
                "rows_per_table": {},
                "changes": [],
            }
        targets = {
            c["source_rel"] for c in changes
            if c["kind"] in ("added", "changed")
        }
        if verbose:
            console.print(f"\n[bold]Re-ingesting {len(targets)} changed file(s)…[/bold]\n")
        ing = _do_ingest(con, install_root, only=targets, verbose=verbose)
        # Persist updated provenance
        set_setting(con, "lref.files_json", json.dumps(ing["files_meta"]))
        set_setting(con, "lref.last_refresh_at", datetime.now().isoformat(timespec="seconds"))
        return {
            "action": "refreshed",
            "frozen_at": get_setting(con, "lref.frozen_at"),
            "rows_per_table": ing["rows_per_table"],
            "changes": changes,
        }

    # First-time freeze.
    if verbose:
        console.rule("[bold]L_REF · first-ingest freeze (D27)[/bold]")
        console.print(
            f"[dim]Source:[/dim] {install_root}\n"
            f"[dim]OOTP version:[/dim] {ootp_version_from_root(install_root)}\n"
            f"[dim]Tables to load:[/dim] {len(LREF_CATALOG)}\n"
        )
    ing = _do_ingest(con, install_root, only=None, verbose=verbose)
    now_iso = datetime.now().isoformat(timespec="seconds")
    set_setting(con, "lref.frozen_at", now_iso)
    set_setting(con, "lref.source_root", str(install_root))
    set_setting(con, "lref.ootp_version", ootp_version_from_root(install_root))
    set_setting(con, "lref.files_json", json.dumps(ing["files_meta"]))
    set_setting(con, "lref.table_count", str(len(ing["rows_per_table"])))

    if verbose:
        total_rows = sum(ing["rows_per_table"].values())
        console.print(
            f"\n[bold green]L_REF frozen.[/bold green] "
            f"{len(ing['rows_per_table'])} tables, {total_rows:,} rows. "
            f"frozen_at={now_iso}\n"
        )
    return {
        "action": "frozen",
        "frozen_at": now_iso,
        "rows_per_table": ing["rows_per_table"],
    }


def refresh_lref(
    con: duckdb.DuckDBPyConnection,
    install_root: Path | None = None,
    *,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Show diff vs frozen snapshot; optionally re-ingest changed files.

    With ``dry_run=True``, prints the diff and returns without touching
    the warehouse. With ``dry_run=False``, also re-ingests changed files.
    """
    if install_root is None:
        install_root = ootp_install_root()

    init_admin_tables(con)
    if not is_lref_frozen(con):
        if verbose:
            console.print(
                "[yellow]L_REF has never been frozen on this save.[/yellow] "
                "Running first-ingest freeze instead."
            )
        return ensure_lref(con, install_root, force_refresh=False, verbose=verbose)

    changes = compute_lref_diff(con, install_root)
    if verbose:
        _print_diff(changes)
    if dry_run or not changes:
        return {
            "action": "dry_run" if dry_run else "skipped",
            "frozen_at": get_setting(con, "lref.frozen_at"),
            "changes": changes,
        }
    return ensure_lref(con, install_root, force_refresh=True, verbose=verbose)
