"""Diamond CLI — entry point for audit, ingest, and analysis commands."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

# Force UTF-8 stdout/stderr on Windows so Rich can render box characters etc.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from diamond.audit import advanced as advanced_mod
from diamond.audit import coverage as coverage_mod
from diamond.audit import decode as decode_mod
from diamond.audit import decode_codes as decode_codes_mod
from diamond.audit import reconcile as reconcile_mod
from diamond.config import BUILDING_THE_GREEN_MONSTER
from diamond import awards as awards_mod
from diamond import draft as draft_mod
from diamond import glossary as glossary_mod
from diamond import history as history_mod
from diamond import hof as hof_mod
from diamond import records as records_mod
from diamond import streaks as streaks_mod
from diamond.schema import build_warehouse, open_warehouse_db, rebuild_l1_l2
from rich.console import Console

app = typer.Typer(help="OOTP 27 monthly-dump warehouse and analysis app", no_args_is_help=True)
_console = Console()


@app.callback()
def _root() -> None:
    """Diamond CLI."""


@app.command()
def decode(
    year: int | None = typer.Option(
        None,
        help="Season year to audit. Defaults to MAX(year) from the dump's career_bat.",
    ),
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/decoder_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Discover OOTP integer-code meanings (game_type, split_id, at-bat result)."""
    decode_mod.run(year=year, dump=dump, output_path=output)


@app.command()
def reconcile(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/reconciliation_report.md"),
        help="Markdown report output path",
    ),
    source: str = typer.Option(
        "csv",
        help=(
            "'csv' reads dump CSVs directly (audit-phase mode). 'warehouse' "
            "reads from <save>/diamond/diamond.duckdb — the post-ingest "
            "regression check per Decision D8."
        ),
    ),
) -> None:
    """Reconcile import_export files against derivations from monthly dump CSVs."""
    reconcile_mod.run(dump=dump, output_path=output, source=source)


@app.command()
def coverage(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    year: int | None = typer.Option(
        None,
        help="Season year for year-scoped probes. Defaults to MAX(year) from career_bat.",
    ),
    output: Path = typer.Option(
        Path("audit_output/coverage_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Profile dump CSVs that support feature views (standings, leaders, awards, etc.)."""
    coverage_mod.run(dump=dump, year=year, output_path=output)


@app.command("decode-codes")
def decode_codes(
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/codes_decoder_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Decode the four pending codebooks (award_id, leader.category, streak_id, body_part)."""
    decode_codes_mod.run(dump=dump, output_path=output)


@app.command()
def ingest(
    dump: str | None = typer.Argument(
        None,
        help="Dump folder name (e.g., 'dump_2029_11'). Omit with --all or --rebuild-only.",
    ),
    all_dumps: bool = typer.Option(
        False, "--all", help="Ingest every dump in <save>/dump/ in chronological order."
    ),
    rebuild_only: bool = typer.Option(
        False,
        "--rebuild-only",
        help="Skip L0 ingest entirely; only rebuild L1+L2 from existing L0 data.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-ingest dumps already marked 'success' in _diamond_ingests.",
    ),
    no_rebuild: bool = typer.Option(
        False,
        "--no-rebuild",
        help="Stop after L0 ingest; skip the L1+L2 rebuild.",
    ),
    reference_scope: bool = typer.Option(
        None,
        "--reference-scope/--no-reference-scope",
        help="Per Decision D13: enable/disable the reference-tier "
        "expansion of `_scoped_players` (adds players with ≥1 MLB "
        "appearance — HoFers, current-era stars on other orgs, "
        "historical legends). Persists in `_diamond_settings`. "
        "Omit to use the previously-persisted value (defaults False).",
    ),
    save: str = typer.Option(
        None,
        "--save",
        help=(
            "Save folder name (with the '.lg' suffix, e.g. 'The Fathers.lg'). "
            "Defaults to the persisted active save from "
            "~/.diamond/active_save.toml, or 'Building the Green Monster.lg' "
            "if none is set. Per-save scope (audit_team_id + league_ids) "
            "loads from ~/.diamond/save_configs.toml when present."
        ),
    ),
) -> None:
    """Ingest OOTP dumps into the warehouse and rebuild L1+L2.

    Writes to <save>/diamond/diamond.duckdb (per Decision D2). The warehouse
    is layered:
      L0   raw landing — one dump's CSVs become 69 l0_* tables
      L1   conformed   — 12 reference + 35 event + 21 snapshot + 6 _current views
      L2   facts       — 8 analytical-grain tables (see docs/SCHEMA.md)

    Examples:
        diamond ingest dump_2029_11               # ingest one dump + rebuild L1+L2
        diamond ingest --all                      # walk every dump folder in order
        diamond ingest --rebuild-only             # rebuild L1+L2 from current L0
        diamond ingest --rebuild-only --reference-scope   # turn D13 on, rebuild
        diamond ingest --all --save "The Fathers.lg"      # build a different save
    """
    from dataclasses import replace
    from diamond.schema.build import (
        get_reference_scope_enabled, set_reference_scope_enabled,
    )
    from diamond.saves import list_saves, load_active_save_name
    from diamond.api.warehouse import build_save_config

    # Resolve which save to operate on. Precedence: --save flag >
    # ~/.diamond/active_save.toml > BUILDING_THE_GREEN_MONSTER.
    requested_save_name = save or load_active_save_name()
    if requested_save_name is None:
        save_config = BUILDING_THE_GREEN_MONSTER
    else:
        # Validate the save exists under the OOTP saves root before we
        # try to open a warehouse against a typo'd path.
        if not requested_save_name.endswith(".lg"):
            requested_save_name = requested_save_name + ".lg"
        available = {s.name for s in list_saves()}
        if requested_save_name not in available:
            _console.print(
                f"[red]Save '{requested_save_name}' not found.[/red] "
                f"Available: {sorted(available)}"
            )
            raise typer.Exit(2)
        save_config = build_save_config(requested_save_name)

    save = save_config  # alias for the rest of the function which expects `save`

    # Argument validation: exactly one of {dump, --all, --rebuild-only}
    modes = sum([dump is not None, all_dumps, rebuild_only])
    if modes != 1:
        _console.print(
            "[red]Specify exactly one of:[/red] a dump name, --all, or --rebuild-only."
        )
        raise typer.Exit(1)

    con = open_warehouse_db(save)
    db_path = save.save_dir / "diamond" / "diamond.duckdb"
    _console.print(f"[bold]Warehouse:[/bold] {db_path}\n")

    try:
        # Resolve reference-scope flag: explicit CLI flag overrides + persists;
        # absent flag reads the previously-persisted value.
        if reference_scope is not None:
            set_reference_scope_enabled(con, reference_scope)
            effective_ref = reference_scope
        else:
            effective_ref = get_reference_scope_enabled(con)
        save = replace(save, reference_scope_enabled=effective_ref)
        if effective_ref:
            _console.print(
                "[cyan]Reference scope enabled[/cyan] — `_scoped_players` "
                "includes ≥1-MLB-appearance players (D13).\n"
            )

        if rebuild_only:
            rebuild_l1_l2(con, save, verbose=True)
        else:
            dumps_arg = None if all_dumps else [dump]
            result = build_warehouse(
                con,
                save,
                dumps=dumps_arg,
                force=force,
                rebuild=not no_rebuild,
                verbose=True,
                quiet_per_dump=all_dumps,  # cleaner output for --all
            )
            _console.print(
                f"\n[bold]Summary:[/bold] {len(result['ingested'])} ingested, "
                f"{len(result['skipped'])} skipped."
            )
    finally:
        con.close()


@app.command()
def draft(
    year: int = typer.Argument(..., help="Draft year to analyze (e.g., 2026)."),
    team: int | None = typer.Option(
        None,
        help="Optional team_id to scope the report to a single org's class (e.g., 4 for Boston).",
    ),
    output: Path = typer.Option(
        None,
        help="Markdown report output path. Defaults to audit_output/draft_<year>.md.",
    ),
) -> None:
    """Show a draft class — pick by pick, with current status + MLB WAR.

    Reads from the L3 `f_draft_class` table (built by `diamond ingest`).
    Each player is bucketed into one of: mlb_star / mlb_regular /
    mlb_callup / in_draft_org / traded_away / released / retired.

    Examples:
        diamond draft 2026                # full class
        diamond draft 2026 --team 4       # Sox 2026 class only
    """
    draft_mod.run(year=year, team_id=team, output_path=output)


@app.command("fetch-history")
def fetch_history(
    skip_lahman: bool = typer.Option(False, "--skip-lahman", help="Skip Lahman pull."),
    skip_statcast: bool = typer.Option(False, "--skip-statcast", help="Skip Statcast pull."),
    skip_bref: bool = typer.Option(False, "--skip-bref", help="Skip Baseball-Reference pull."),
    skip_chadwick: bool = typer.Option(False, "--skip-chadwick", help="Skip Chadwick Register pull."),
    skip_mlbapi: bool = typer.Option(False, "--skip-mlbapi", help="Skip MLB Stats API gap-fill (awards/HOF 2018+)."),
    force: bool = typer.Option(
        False, "--force", help="Re-download Lahman zip even if cached."
    ),
    first_year: int = typer.Option(
        2015, help="First Statcast year to pull (Statcast era starts 2015)."
    ),
    cap_year: int | None = typer.Option(
        None,
        "--cap-year",
        help="Last historical year to keep. Defaults to save_start_year - 1 "
        "so the OOTP universe owns save_start_year onward.",
    ),
) -> None:
    """One-time backfill — Lahman + Statcast through save_start_year - 1.

    Diamond's job is to track your OOTP universe. Real-life MLB history
    (Lahman + Statcast) is loaded ONCE so there are real records to
    break (Bonds 73, McGwire 70, Stanton 122mph EV). From save start
    onward, OOTP's simulation is canonical — we don't re-pull real
    2026/2027/etc. stats.

    Runs idempotently if you do re-run, but the canonical workflow is
    once-and-done. After this lands, run
    `diamond ingest --rebuild-only` so L3 leaderboards pick up the
    new rows.
    """
    history_mod.run(
        skip_lahman=skip_lahman,
        skip_statcast=skip_statcast,
        skip_bref=skip_bref,
        skip_chadwick=skip_chadwick,
        skip_mlbapi=skip_mlbapi,
        force_download=force,
        statcast_first_year=first_year,
        statcast_last_year=cap_year,
        bref_last_year=cap_year,
        history_cap_year=cap_year,
    )


@app.command()
def records(
    scope: str = typer.Option(
        "career",
        help="'career' or 'season'.",
    ),
    discipline: str = typer.Option(
        "batting",
        help="'batting' or 'pitching'.",
    ),
    category: str | None = typer.Option(
        None,
        help="A single category to render (e.g., 'HR', 'WAR', 'IP'). "
        "Default: render every category for the scope+discipline.",
    ),
    era: str = typer.Option(
        "all",
        help="'all' (default — unified), 'save' (OOTP only), 'lahman' "
        "(1871-2019 classic stats), 'bref' (2020-2025 fill), 'statcast' "
        "(EV/barrel/hard-hit, 2015-2025), or 'merged' (career rollup of "
        "lahman+bref+statcast for non-save players). Run `diamond "
        "fetch-history` to populate the non-save sides.",
    ),
    limit: int = typer.Option(10, help="Top-N per category (max 50)."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/records_<era>_<scope>_<discipline>.md",
    ),
) -> None:
    """MLB leaderboards (single-season + career) — counting stats + Statcast.

    Reads from the L3 `f_record_player` table. Five sources are unioned:
    `save` (your OOTP save), `lahman` (1871-2019), `bref` (2020-2025),
    `statcast` (2015-2025 EV/barrel), and `merged` (career career-row
    rollup of the three real-history sources for non-save players).

    Examples:
        diamond records                                  # career batting, all eras
        diamond records --scope season --category HR     # season HR, all eras
        diamond records --era save --category HR         # your sim only
        diamond records --era merged --scope career      # real-life all-time
    """
    records_mod.run(
        scope=scope, discipline=discipline,
        category=category, era=era, limit=limit, output_path=output,
    )


@app.command()
def awards(
    award: int | None = typer.Option(
        None,
        help="Award id to render (see diamond.constants.AwardId). "
        "5=MVP, 4=CY, 6=ROY, 7=GG, 11=SS, 9=ASG, 14=WS roster.",
    ),
    player: int | None = typer.Option(
        None,
        help="OOTP player_id — shows their full career awards.",
    ),
    bbref_id: str | None = typer.Option(
        None,
        "--bbref-id",
        help="bbref playerID (e.g., 'bondsba01') — shows real-life player career.",
    ),
    team: int | None = typer.Option(
        None,
        help="Team id to render franchise totals (org-rolled-up via parent_team_id).",
    ),
    league: int = typer.Option(203, help="League id (default MLB=203)."),
    era: str = typer.Option(
        "all",
        help="'all' (default), 'save' (OOTP only), 'merged' (real-life history "
        "Lahman+MLBAPI dedup'd). Affects leaderboard + catalog modes.",
    ),
    limit: int = typer.Option(15, help="Top-N players per award."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/awards.md",
    ),
) -> None:
    """Awards leaderboards — career totals per player, per franchise.

    Modes (priority order):
      diamond awards --player <id>          # OOTP player's full résumé
      diamond awards --bbref-id <playerID>  # real-life player (Bonds, etc.)
      diamond awards --team <id>            # franchise totals
      diamond awards --award <id>           # top-N for that award (era-filtered)
      diamond awards                        # catalog: every award
    """
    awards_mod.run(
        award_id=award,
        player_id=player,
        bbref_id=bbref_id,
        team_id=team,
        league_id=league,
        era=era,
        limit=limit,
        output_path=output,
    )


@app.command()
def hof(
    candidates: bool = typer.Option(
        False, "--candidates",
        help="Show top-N career-WAR players who haven't been inducted yet.",
    ),
    era: str = typer.Option(
        "all",
        help="'all' (save + lahman), 'save' (OOTP only), 'lahman' (real Cooperstown). "
        "Only affects default mode; --candidates is always save-side.",
    ),
    limit: int = typer.Option(25, help="Top-N for --candidates mode."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/hof.md (or hof_candidates.md).",
    ),
) -> None:
    """Hall of Fame tracker — save HoFers + Cooperstown + future candidates.

    Examples:
        diamond hof                  # save HoFers + real Cooperstown
        diamond hof --era lahman     # real Cooperstown only
        diamond hof --candidates     # save shortlist (top-WAR not inducted)
    """
    hof_mod.run(candidates=candidates, era=era, limit=limit, output_path=output)


@app.command()
def streaks(
    all_time: bool = typer.Option(
        False, "--all-time",
        help="Show top-N all-time streaks (active + finished). "
        "Default is --active only.",
    ),
    category: int | None = typer.Option(
        None,
        help="Single streak_id to render (see diamond.constants.StreakId). "
        "0=Hitting, 5=Win, 9=GamesPlayed, 12=Saves, 19=K, 21=Appearance, etc. "
        "Default: render every category.",
    ),
    limit: int = typer.Option(10, help="Top-N per category (max 50)."),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/streaks_<scope>.md",
    ),
) -> None:
    """Streak leaderboards (active or all-time, per category).

    Reads from L3 `f_player_streak`. Labels come from the `StreakId`
    IntEnum and are best-guess pending OOTP UI cross-reference.

    Examples:
        diamond streaks                            # active streaks, every category
        diamond streaks --all-time                 # all-time, every category
        diamond streaks --category 0 --all-time    # all-time hitting streak only
        diamond streaks --category 4               # active scoreless-innings streaks
    """
    scope = "all_time" if all_time else "active"
    streaks_mod.run(
        scope=scope, category=category, limit=limit, output_path=output,
    )


@app.command()
def glossary(
    stat_id: str | None = typer.Argument(
        None,
        help="Stat id to render full detail for (e.g., 'wOBA', 'OPS_plus'). "
        "Omit to list every category.",
    ),
    category: str | None = typer.Option(
        None,
        help="Filter to one category (batting / pitching / fielding / "
        "advanced / value / statcast / ratings).",
    ),
    output: Path = typer.Option(
        None,
        help="Markdown output path. Defaults to audit_output/glossary.md "
        "when listing all categories; no output file when rendering "
        "a single stat unless --output is set.",
    ),
) -> None:
    """Stat dictionary glossary — D15 single source of truth.

    Reads from the canonical `diamond.dictionary.STATS` Python dict.
    Every column header / chart axis / AI prompt in Diamond points back
    here. Updating a stat's metadata = update the dictionary entry,
    never inline.

    Examples:
        diamond glossary                        # list every category
        diamond glossary wOBA                   # full detail on one stat
        diamond glossary --category advanced    # one category compact view
        diamond glossary --output docs/STAT_GLOSSARY.md   # write markdown
    """
    glossary_mod.run(
        stat_id=stat_id, category=category, output_path=output,
    )


@app.command()
def advanced(
    year: int | None = typer.Option(
        None,
        help="Season year. Defaults to MAX(year) from the dump's career_bat.",
    ),
    league_id: int = typer.Option(203, help="League id (default MLB=203)"),
    dump: str | None = typer.Option(None, help="Dump folder name; defaults to latest"),
    output: Path = typer.Option(
        Path("audit_output/advanced_stats_report.md"),
        help="Markdown report output path",
    ),
) -> None:
    """Compute modern advanced stats (Tiers 1-5) from at-bat + dump data."""
    advanced_mod.run(year=year, league_id=league_id, dump=dump, output_path=output)


if __name__ == "__main__":
    app()
