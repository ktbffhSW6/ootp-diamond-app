"""Inventory every L0 column and classify usage across the codebase.

Phase 4a deliverable #1 (D40 — Audit Closure).

For each `l0_*` table in the active warehouse, this script:

1. Pulls the live column list (so we see what's actually there, not just what
   ``L0_CATALOG`` declares).
2. Word-boundary-greps every non-admin column name across the Python + TS
   source corpus (`src/diamond/{api,schema,advanced,audit,...}` and
   `web/{app,components,lib}` plus `scripts/`).
3. Classifies each column as:
   - **admin**  — `dump_date` / `ingest_ts` / `file_seq` (provenance, every L0)
   - **used**   — at least one source-file reference
   - **orphan** — zero references in source

4. Emits `audit_output/l0_column_coverage.md` with:
   - Summary stats (% referenced)
   - Top-15 tables ranked by orphan count (the Phase 4a wiring candidates)
   - Per-table breakdown with the orphan column list

**Caveats** — referenced-vs-orphan is a heuristic. Word-boundary matching
produces false positives for columns with generic names (`id`, `year`,
`name`, `result`, `type`, ...) — they'll show as "referenced" even if the
specific table.column tuple is never pulled. The intent is to bound the
true-orphan set from above, so we don't miss columns that are genuinely
never used. Manual review of the orphan list is still required.

Usage::

    .venv/Scripts/python.exe scripts/inventory_l0_coverage.py
    .venv/Scripts/python.exe scripts/inventory_l0_coverage.py --save "The Fathers"
    .venv/Scripts/python.exe scripts/inventory_l0_coverage.py -o path/to/report.md

Save-agnostic by construction: passes `--save NAME` through to
``build_save_config`` exactly the same way the CLI commands do.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

# Make `import diamond` work when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diamond.api.warehouse import build_save_config  # noqa: E402
from diamond.config import BUILDING_THE_GREEN_MONSTER  # noqa: E402
from diamond.saves import load_active_save_name  # noqa: E402
from diamond.schema.build import open_warehouse_db  # noqa: E402


ADMIN_COLS = frozenset({"dump_date", "ingest_ts", "file_seq"})

# Source roots to search. Order doesn't matter; relative paths come back
# rooted in ROOT.
SRC_ROOTS = [
    ROOT / "src" / "diamond",
    ROOT / "scripts",
    ROOT / "web" / "app",
    ROOT / "web" / "components",
    ROOT / "web" / "lib",
]

EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".sql")

# Generic column names where word-boundary matching is misleading because
# the same identifier shows up in unrelated source contexts. We still
# classify them as referenced (avoiding false orphan claims), but we tag
# them in the report so reviewers know to verify by hand.
NOISY_NAMES = frozenset({
    "id", "year", "name", "type", "code", "key", "result", "value",
    "date", "level", "league", "team", "player", "position", "status",
    "month", "day", "hour", "minute", "second", "time", "count", "sum",
    "min", "max", "avg", "total", "x", "y", "z", "n",
})


# Table-name → wiring-priority category. Drives the "Phase 4a wiring
# recommendations" section in the report. Patterns are evaluated in
# declaration order; first match wins.
CATEGORY_RULES: list[tuple[str, str, str]] = [
    # (regex, label, recommendation)
    (r".*_financials?$",
     "Finance",
     "Defer — Phase 6+ / future finance dashboard."),
    (r"^l0_(leagues|league_playoffs?)$",
     "League config",
     "Permanent skip — league-rules / playoff-config / award names."),
    (r".*league_playoff.*",
     "Playoff config",
     "Permanent skip — playoff bracket / format metadata."),
    (r"^l0_(cities|continents|states|nations|languages?|language_data)$",
     "Geo / i18n reference",
     "Permanent skip — geo + language reference data."),
    (r"^l0_parks$",
     "Park config",
     "Phase 4b — park / stadium metadata for cosmetic features."),
    (r"^l0_(coaches|human_manager.*)$",
     "Personnel",
     "Phase 4b/5 — coach + manager surface (career arcs, etc.)."),
    (r"^l0_players_value$",
     "Player valuation cache",
     "**Phase 4a #2 wire candidate** — OOTP-cached per-position / "
     "per-side valuations (`overall_sp/rp/c/1b/...`, `*_value_vsl/vsr`)."),
    (r"^l0_players_scouted_ratings$",
     "Scouted ratings",
     "Phase 4a #2 wire candidate — per-side rating splits we don't surface."),
    (r"^l0_team_(batting|pitching|fielding|bullpen_pitching|starting_pitching)_stats(_stats)?$",
     "Team stat cache (current)",
     "**Phase 4a #2 wire candidate** — authoritative OOTP-cached "
     "rate stats (`ws`, `gbfbp`, `kbb`, `cera`, `sbp`, ...). "
     "Feeds D40 invariants watchdog."),
    (r"^l0_team_history_(batting|pitching|fielding|record|bullpen_pitching|starting_pitching)_stats(_stats)?$",
     "Team stat cache (history)",
     "Phase 4a #2 wire candidate — same as current but historical."),
    (r"^l0_team_history$",
     "Team season history",
     "Audit — team-season summary rows; review for gaps."),
    (r"^l0_league_history(_(batting|pitching|fielding)_stats)?$",
     "League stat cache",
     "Phase 4a #2 wire candidate — league-level OOTP-cached aggregates."),
    (r"^l0_players_career_(batting|pitching|fielding)_stats$",
     "Career stat cache",
     "**Phase 4a #2 wire candidate** — career rollups OOTP pre-computes. "
     "Cross-check against our `f_player_career` derivation."),
    (r"^l0_(games|games_score|projected_starting_pitchers)$",
     "Game state",
     "Phase 4b — game-grain facts (`f_player_game_*`)."),
    (r"^l0_trade_history$",
     "Trade events",
     "Audit — partially wired via `f_trade_participant`; review for gaps."),
    (r"^l0_players(_batting|_fielding|_contract.*|_roster_status)?$",
     "Player state snapshot",
     "Audit — primary snapshot tables. Orphans likely fine-grained "
     "rating sub-columns; review case-by-case."),
]


def categorize_table(table: str) -> tuple[str, str]:
    """Return (label, recommendation) for an L0 table name."""
    for pat, label, rec in CATEGORY_RULES:
        if re.match(pat, table):
            return label, rec
    return "Other", "Review by hand."


def build_corpus() -> list[tuple[str, str]]:
    """Read every source file once. Returns [(rel_path, full_text), ...].

    Excludes this auditor script itself — otherwise the column names quoted
    in `CATEGORY_RULES` recommendation strings would self-reference and
    falsely mark themselves as "used."
    """
    self_path = Path(__file__).resolve().relative_to(ROOT).as_posix()
    corpus: list[tuple[str, str]] = []
    for root in SRC_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in EXTS:
                continue
            # Skip generated / vendored / self
            rel = p.relative_to(ROOT).as_posix()
            if rel == self_path:
                continue
            if "/__pycache__/" in rel or "/node_modules/" in rel or "/.next/" in rel:
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            corpus.append((rel, txt))
    return corpus


def find_refs(col: str, corpus: list[tuple[str, str]]) -> list[str]:
    """Return the list of rel-paths that reference `col` (word-bounded)."""
    if len(col) <= 1:
        # 1-char names like 'p', 'x' would match everything — skip.
        return ["__too_short__"]
    pat = re.compile(rf"\b{re.escape(col)}\b")
    return [path for path, txt in corpus if pat.search(txt)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", help="save name (without .lg)")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=ROOT / "audit_output" / "l0_column_coverage.md",
        help="output markdown path (default audit_output/l0_column_coverage.md)",
    )
    args = parser.parse_args()

    save_name = args.save or load_active_save_name() or BUILDING_THE_GREEN_MONSTER.save_name
    cfg = build_save_config(save_name)
    con = open_warehouse_db(cfg)

    tables = [
        r[0] for r in con.execute(
            "SELECT table_name "
            "FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name LIKE 'l0_%' "
            "ORDER BY table_name"
        ).fetchall()
    ]
    if not tables:
        print("No l0_* tables found — has the save been ingested?", file=sys.stderr)
        return 2

    print(f"Building source corpus from {len(SRC_ROOTS)} roots ...")
    corpus = build_corpus()
    print(f"  {len(corpus)} files indexed")
    print(f"Scanning {len(tables)} L0 tables ...")

    per_table: list[dict] = []
    summary = {"tables": 0, "cols_total": 0, "cols_admin": 0,
               "cols_refd": 0, "cols_orphan": 0, "rows_total": 0}
    all_orphans: list[tuple[str, str]] = []   # (table, col)

    for t in tables:
        col_rows = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [t],
        ).fetchall()
        cols = [r[0] for r in col_rows]
        try:
            row_count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            row_count = 0

        used: list[str] = []
        admin: list[str] = []
        orphan: list[str] = []
        noisy: list[str] = []

        for c in cols:
            if c in ADMIN_COLS:
                admin.append(c)
                continue
            refs = find_refs(c, corpus)
            if refs:
                used.append(c)
                if c.lower() in NOISY_NAMES:
                    noisy.append(c)
            else:
                orphan.append(c)
                all_orphans.append((t, c))

        ncols_nonadmin = len(cols) - len(admin)
        summary["tables"] += 1
        summary["rows_total"] += row_count
        summary["cols_total"] += ncols_nonadmin
        summary["cols_admin"] += len(admin)
        summary["cols_refd"] += len(used)
        summary["cols_orphan"] += len(orphan)

        per_table.append({
            "table": t,
            "rows": row_count,
            "cols_total": ncols_nonadmin,
            "used": used,
            "admin": admin,
            "orphan": orphan,
            "noisy": noisy,
        })

    # ── Emit report ──────────────────────────────────────────────────────
    out_path: Path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def pct(part: int, whole: int) -> str:
        if whole == 0:
            return "0%"
        return f"{part * 100 // whole}%"

    now = dt.datetime.now().isoformat(timespec="seconds")
    db_path = cfg.save_dir / "diamond" / "diamond.duckdb"

    lines: list[str] = []
    lines.append("# L0 Column Coverage Audit\n")
    lines.append(f"**Save**: `{save_name}`  ")
    lines.append(f"**Warehouse**: `{db_path}`  ")
    lines.append(f"**Generated**: `{now}`  ")
    lines.append("")
    lines.append("Phase 4a deliverable #1 — enumerates every column in every L0 table "
                 "and classifies it as referenced or orphan across the codebase "
                 "(`src/diamond/**`, `web/{app,components,lib}/**`, `scripts/**`). "
                 "Word-boundary heuristic; generic column names are flagged as "
                 "*noisy* — review by hand for true usage.")
    lines.append("")
    lines.append("## Summary\n")
    lines.append(f"- L0 tables: **{summary['tables']}**")
    lines.append(f"- Total rows in L0: **{summary['rows_total']:,}**")
    lines.append(f"- Non-admin columns: **{summary['cols_total']}**")
    lines.append(f"- Referenced: **{summary['cols_refd']}** "
                 f"({pct(summary['cols_refd'], summary['cols_total'])})")
    lines.append(f"- Orphan: **{summary['cols_orphan']}** "
                 f"({pct(summary['cols_orphan'], summary['cols_total'])})")
    lines.append(f"- Admin (`dump_date`, `ingest_ts`, `file_seq`): "
                 f"**{summary['cols_admin']}** "
                 f"({summary['tables']} tables × 3)")
    lines.append("")

    # Top-orphan-rich tables — the Phase 4a wiring candidates
    lines.append("## Tables with most orphan columns\n")
    lines.append("Sorted by absolute orphan count. **Category** is rule-based — see `CATEGORY_RULES` in `scripts/inventory_l0_coverage.py`.\n")
    lines.append("| # | L0 table | rows | cols | orphan | % | Category |")
    lines.append("|---:|---|---:|---:|---:|---:|---|")
    ranked = sorted(per_table, key=lambda r: (-len(r["orphan"]), r["table"]))
    for i, r in enumerate(ranked[:20], 1):
        label, _ = categorize_table(r["table"])
        lines.append(
            f"| {i} | `{r['table']}` | {r['rows']:,} | "
            f"{r['cols_total']} | {len(r['orphan'])} | "
            f"{pct(len(r['orphan']), r['cols_total'])} | {label} |"
        )
    lines.append("")

    # Phase 4a wiring recommendations — bucketed by category
    lines.append("## Phase 4a wiring recommendations\n")
    lines.append(
        "Orphan tables grouped by category. Sorted within each category by "
        "absolute orphan count.\n"
    )
    by_label: dict[str, list[dict]] = defaultdict(list)
    by_label_rec: dict[str, str] = {}
    for r in per_table:
        if not r["orphan"]:
            continue
        label, rec = categorize_table(r["table"])
        by_label[label].append(r)
        by_label_rec[label] = rec
    # Order categories: Phase 4a wire candidates first, then 4b, then defer/skip
    category_order = [
        "Team stat cache (current)",
        "Team stat cache (history)",
        "League stat cache",
        "Career stat cache",
        "Player valuation cache",
        "Scouted ratings",
        "Player state snapshot",
        "Game state",
        "Team season history",
        "Park config",
        "Personnel",
        "Trade events",
        "Other",
        "Finance",
        "League config",
        "Playoff config",
        "Geo / i18n reference",
    ]
    seen: set[str] = set()
    for cat in category_order + sorted(by_label.keys()):
        if cat in seen or cat not in by_label:
            continue
        seen.add(cat)
        tables_in_cat = sorted(by_label[cat], key=lambda r: -len(r["orphan"]))
        total_orphan = sum(len(r["orphan"]) for r in tables_in_cat)
        lines.append(f"### {cat} ({total_orphan} orphan cols across {len(tables_in_cat)} tables)\n")
        lines.append(f"_{by_label_rec[cat]}_\n")
        lines.append("| L0 table | orphan cols |")
        lines.append("|---|---:|")
        for r in tables_in_cat:
            lines.append(f"| `{r['table']}` | {len(r['orphan'])} |")
        lines.append("")

    # Fully-consumed tables (zero orphans) — these we've already mined
    fully_consumed = [r for r in per_table if not r["orphan"] and r["cols_total"] > 0]
    lines.append(f"## Fully consumed tables ({len(fully_consumed)})\n")
    lines.append("Zero orphan columns — every non-admin field flows somewhere in the codebase.\n")
    if fully_consumed:
        chunk: list[str] = []
        for r in sorted(fully_consumed, key=lambda x: x["table"]):
            chunk.append(f"`{r['table']}`")
            if len(chunk) == 4:
                lines.append("- " + ", ".join(chunk))
                chunk = []
        if chunk:
            lines.append("- " + ", ".join(chunk))
    lines.append("")

    # Per-table detail
    lines.append("## Per-table breakdown\n")
    for r in sorted(per_table, key=lambda x: x["table"]):
        used = r["used"]
        orphan = r["orphan"]
        noisy = r["noisy"]
        lines.append(f"### `{r['table']}` — {r['rows']:,} rows × {r['cols_total']} non-admin cols\n")
        lines.append(
            f"Referenced: **{len(used)} / {r['cols_total']}** "
            f"({pct(len(used), r['cols_total'])})  "
        )
        if orphan:
            lines.append(f"Orphan: **{len(orphan)}**\n")
            lines.append("```")
            row: list[str] = []
            for c in orphan:
                row.append(c)
                if len(row) == 6:
                    lines.append(", ".join(row))
                    row = []
            if row:
                lines.append(", ".join(row))
            lines.append("```")
        else:
            lines.append("Orphan: **0** ✓\n")
        if noisy:
            lines.append("")
            lines.append(
                f"<details><summary>{len(noisy)} noisy column(s) "
                "— review by hand</summary>\n"
            )
            lines.append("`" + "`, `".join(noisy) + "`")
            lines.append("\n</details>")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nWrote {out_path.relative_to(ROOT)}")
    print(
        f"Summary: {summary['cols_refd']}/{summary['cols_total']} cols referenced "
        f"({pct(summary['cols_refd'], summary['cols_total'])}); "
        f"{summary['cols_orphan']} orphans across {summary['tables']} tables."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
