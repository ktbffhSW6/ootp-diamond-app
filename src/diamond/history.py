"""Real-life MLB historical data ingest — Lahman + Statcast.

**Design intent: this is a ONE-TIME BACKFILL, not a refreshable feed.**

Diamond's job is to track your OOTP universe. Real-life MLB history
(Lahman + Statcast) is loaded once so there are real records to
break — Bonds 73 in 2001, McGwire 70 in 1998, Stanton's 122 mph EV.
Once the historical floor is set, the OOTP simulation takes over: in
your save, the 2026+ "MLB" is your league, not real life. We don't
re-pull Lahman annually; we don't track real-life 2026+ stats. If
real-life Aaron Judge has a great 2026 season, that's noise relative
to your save's 2026.

Concretely:
  - Historical pulls cap at `save_start_year - 1`. The current Sox
    save starts in 2026, so we keep history through 2025 and drop
    anything from 2026 onward.
  - `diamond fetch-history` is intended to be run once. It IS
    idempotent (cached zips, INSERT OR REPLACE-style table builds),
    so if you do re-run it nothing breaks — but the canonical
    workflow is once-and-done.
  - There's no "auto-refresh" wired into `diamond ingest`. Adding
    new dumps doesn't re-pull history. Good.

Two sources, both loaded into per-save warehouse tables prefixed
`history_lahman_*` and `history_statcast_*`:

  - **Lahman** (1871–save_start_year-1): classic counting + rate
    stats, awards, HoF voting, people. Pulled as a single zip from
    cdalzell/Lahman (mirror of the original SeanLahman archive).
  - **Statcast** (2015–save_start_year-1): season-aggregated
    exit-velocity / barrel / hard-hit leaderboards via `pybaseball`.
    Per-PA Statcast is intentionally out of scope for v1 — season
    grain is the right shape for record leaderboards.

The original `chadwickbureau/baseballdatabank` GitHub repo (which
pybaseball still points at) is gone as of 2026. We use the
cdalzell/Lahman R-package mirror for the canonical zip — it's the
same file Sean Lahman used to ship, just hosted in a stable place.
"""

from __future__ import annotations

import io
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
import requests
from rich.console import Console

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Lahman — download + cache
# ─────────────────────────────────────────────────────────────────────────────


# Stable mirror of the original chadwickbureau/baseballdatabank zip.
LAHMAN_ZIP_URL = (
    "https://github.com/cdalzell/Lahman/raw/master/source-data/baseballdatabank-master.zip"
)
LAHMAN_ZIP_NAME = "baseballdatabank-master.zip"
LAHMAN_INNER_PREFIX = "baseballdatabank-master/core/"


@dataclass(frozen=True)
class LahmanTable:
    """Spec for one Lahman CSV → DuckDB table."""
    csv_name: str           # e.g. "People.csv"
    table_name: str         # e.g. "history_lahman_people"
    primary_key: tuple[str, ...]
    notes: str = ""


# The Lahman tables we care about for records / awards / HoF / player-page
# joins. Each uses Lahman's published column names verbatim.
LAHMAN_TABLES: list[LahmanTable] = [
    LahmanTable(
        csv_name="People.csv",
        table_name="history_lahman_people",
        primary_key=("playerID",),
        notes="One row per real-life MLB player ever. ~22k rows.",
    ),
    LahmanTable(
        csv_name="Batting.csv",
        table_name="history_lahman_batting",
        # (playerID, yearID, stint) is the published natural key.
        primary_key=("playerID", "yearID", "stint"),
        notes="Per (player, year, team-stint) batting line. ~115k rows.",
    ),
    LahmanTable(
        csv_name="Pitching.csv",
        table_name="history_lahman_pitching",
        primary_key=("playerID", "yearID", "stint"),
        notes="Per (player, year, stint) pitching line. ~50k rows.",
    ),
    LahmanTable(
        csv_name="Fielding.csv",
        table_name="history_lahman_fielding",
        primary_key=("playerID", "yearID", "stint", "POS"),
        notes="Per (player, year, stint, position) fielding line.",
    ),
    LahmanTable(
        csv_name="AwardsPlayers.csv",
        table_name="history_lahman_awards",
        # No published key; (playerID, awardID, yearID, lgID) is reasonable.
        primary_key=("playerID", "awardID", "yearID", "lgID"),
        notes="One row per (player, award, year, league).",
    ),
    LahmanTable(
        csv_name="HallOfFame.csv",
        table_name="history_lahman_hof",
        primary_key=("playerID", "yearid", "votedBy"),
        notes="Annual HoF ballot results — votes / inducted / category.",
    ),
    LahmanTable(
        csv_name="AllstarFull.csv",
        table_name="history_lahman_allstar",
        # Some rows lack gameID; use (playerID, yearID, gameNum) which is
        # always populated and matches the natural per-game key.
        primary_key=("playerID", "yearID", "gameNum"),
        notes="All-star game appearances.",
    ),
    LahmanTable(
        csv_name="Teams.csv",
        table_name="history_lahman_teams",
        primary_key=("yearID", "lgID", "teamID"),
        notes="One row per team-season. Used for franchise records and team_id resolution.",
    ),
]


def _history_cache_dir(save: SaveConfig) -> Path:
    return save.save_dir / "diamond" / "history_cache"


def _save_start_year(save: SaveConfig) -> int:
    """Derive the in-game year the save started in.

    Read from the earliest dump folder name: `dump_2026_03` → 2026.
    The historical backfill caps at this year - 1 so OOTP's
    universe is the only thing modeling save_start_year and beyond.
    """
    dumps = save.all_dump_names()
    if not dumps:
        raise FileNotFoundError(
            f"No dumps found in {save.dump_dir}; can't determine save start year."
        )
    # dumps are sorted; first one is earliest. dump_YYYY_MM
    parts = dumps[0].split("_")
    return int(parts[1])


def _fetch_lahman_zip(save: SaveConfig, *, force: bool = False) -> Path:
    """Download the Lahman zip to `<save>/diamond/history_cache/`. Returns path."""
    cache_dir = _history_cache_dir(save)
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / LAHMAN_ZIP_NAME

    if zip_path.exists() and not force:
        console.print(
            f"[dim]Using cached Lahman zip:[/dim] {zip_path} "
            f"({zip_path.stat().st_size:,} bytes)"
        )
        return zip_path

    console.print(f"Downloading Lahman: [cyan]{LAHMAN_ZIP_URL}[/cyan]")
    r = requests.get(LAHMAN_ZIP_URL, timeout=120)
    r.raise_for_status()
    zip_path.write_bytes(r.content)
    console.print(
        f"  [green]✓[/green] {zip_path} ({zip_path.stat().st_size:,} bytes)"
    )
    return zip_path


def _load_lahman_table(
    con: duckdb.DuckDBPyConnection,
    zip_path: Path,
    spec: LahmanTable,
    *,
    history_cap_year: int | None = None,
) -> int:
    """CREATE OR REPLACE TABLE `history_lahman_*` from one CSV inside the zip.

    DuckDB's `read_csv_auto` can read directly from a remote URL but
    not from a path-inside-zip, so we extract the CSV bytes once and
    pipe through a temp register.

    If `history_cap_year` is set, year-keyed Lahman tables (Batting,
    Pitching, Fielding, AwardsPlayers, AllstarFull, Teams) get a
    `WHERE yearID <= history_cap_year` filter at load time. People.csv
    has no year column so it loads fully (a few extra retired players
    is harmless).
    """
    inner = LAHMAN_INNER_PREFIX + spec.csv_name
    with zipfile.ZipFile(zip_path) as z:
        if inner not in z.namelist():
            raise RuntimeError(f"{spec.csv_name} not found inside Lahman zip")
        # Extract to a sibling location next to the zip — keeps DuckDB happy
        # (read_csv_auto needs a file path; can't read from BytesIO).
        extract_target = zip_path.parent / spec.csv_name
        with z.open(inner) as src, extract_target.open("wb") as dst:
            dst.write(src.read())

    con.execute(f"DROP TABLE IF EXISTS {spec.table_name}")

    # Year-cap filter for tables that have a yearID column. HoF uses
    # `yearid` (lowercase). People + Teams have a yearID-like column —
    # but People's `birthYear` etc. shouldn't be capped (a player born
    # in 1995 is fine to keep). For HoF, cap by election year.
    where = ""
    if history_cap_year is not None:
        if spec.csv_name in (
            "Batting.csv", "Pitching.csv", "Fielding.csv", "FieldingOF.csv",
            "FieldingOFsplit.csv", "FieldingPost.csv", "BattingPost.csv",
            "PitchingPost.csv", "AwardsPlayers.csv", "AllstarFull.csv",
            "Salaries.csv",
        ):
            where = f"WHERE yearID <= {history_cap_year}"
        elif spec.csv_name == "HallOfFame.csv":
            where = f"WHERE yearid <= {history_cap_year}"
        elif spec.csv_name == "Teams.csv":
            where = f"WHERE yearID <= {history_cap_year}"

    # sample_size=-1 forces full-file type inference (Lahman has sparse cols).
    con.execute(
        f"CREATE TABLE {spec.table_name} AS "
        f"SELECT * FROM read_csv_auto('{extract_target.as_posix()}', "
        f"sample_size=-1, ignore_errors=true) "
        f"{where}"
    )

    # PK enforcement is best-effort — Lahman has occasional dups in
    # secondary tables (e.g., HallOfFame can have repeated rows for the
    # same ballot in some years). If the PK fails, drop it but keep the
    # table.
    pk_cols = ", ".join(spec.primary_key)
    try:
        con.execute(f"ALTER TABLE {spec.table_name} ADD PRIMARY KEY ({pk_cols})")
    except duckdb.ConstraintException as e:
        console.print(
            f"  [yellow]⚠[/yellow] {spec.table_name}: PK ({pk_cols}) violated — "
            f"keeping table without PK.  ({e})"
        )

    n = con.execute(f"SELECT COUNT(*) FROM {spec.table_name}").fetchone()[0]
    return n


def fetch_and_load_lahman(
    con: duckdb.DuckDBPyConnection,
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    *,
    force_download: bool = False,
    verbose: bool = True,
    history_cap_year: int | None = None,
) -> dict[str, int]:
    """Top-level Lahman ingest. Returns `{table_name: row_count}`.

    Lahman year-keyed tables are filtered to `yearID <= history_cap_year`
    at load time. If `history_cap_year` is None, derive it as
    `save_start_year - 1` (the year before OOTP took over).
    """
    if history_cap_year is None:
        history_cap_year = _save_start_year(save) - 1
    zip_path = _fetch_lahman_zip(save, force=force_download)
    rows: dict[str, int] = {}
    if verbose:
        console.rule(f"Lahman tables  (yearID ≤ {history_cap_year})")
    for spec in LAHMAN_TABLES:
        n = _load_lahman_table(con, zip_path, spec, history_cap_year=history_cap_year)
        rows[spec.table_name] = n
        if verbose:
            pk = ", ".join(spec.primary_key)
            console.print(
                f"  [green]✓[/green] {spec.table_name:<30} "
                f"[dim]{n:>8,} rows  PK=({pk})[/dim]"
            )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Statcast — season-aggregated exit-velocity / barrel leaderboards
# ─────────────────────────────────────────────────────────────────────────────


# Statcast began in 2015; pybaseball wraps the Savant leaderboard endpoint
# year-by-year. We default to 2015–<current> and let the fetcher discover
# the actual upper bound by probing.
STATCAST_FIRST_YEAR = 2015
STATCAST_MIN_BBE = 50           # both batter and pitcher endpoints take minBBE


def _fetch_statcast_one_year(year: int, *, batting: bool):
    """Pull season-aggregated Statcast leaderboard for one year. Returns
    a pandas DataFrame or None if the year isn't available."""
    import pybaseball as pyb
    fn = (
        pyb.statcast_batter_exitvelo_barrels
        if batting else pyb.statcast_pitcher_exitvelo_barrels
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            df = fn(year, minBBE=STATCAST_MIN_BBE)
        except Exception as e:
            console.print(
                f"  [yellow]⚠[/yellow] {year} {'batting' if batting else 'pitching'}: "
                f"fetch failed — {e}"
            )
            return None
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    df["year"] = year
    return df


def fetch_and_load_statcast(
    con: duckdb.DuckDBPyConnection,
    *,
    first_year: int = STATCAST_FIRST_YEAR,
    last_year: int | None = None,
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    verbose: bool = True,
) -> dict[str, int]:
    """Pull Statcast season-aggregated EV/barrel leaderboards for batting
    and pitching, year by year, and load to `history_statcast_*`.

    Defaults to `last_year = save_start_year - 1` so the OOTP universe
    owns save_start_year onward. Pass an explicit `last_year` to
    override (rare).

    Returns `{table_name: row_count}`.
    """
    if last_year is None:
        last_year = _save_start_year(save) - 1
    import pandas as pd
    if verbose:
        console.rule("Statcast season leaderboards")

    # Batting ---------------------------------------------------------
    bat_frames: list[pd.DataFrame] = []
    for y in range(first_year, last_year + 1):
        df = _fetch_statcast_one_year(y, batting=True)
        if df is None or len(df) == 0:
            continue
        bat_frames.append(df)
        if verbose:
            console.print(f"  batting {y}: [dim]{len(df):,} players[/dim]")
    rows: dict[str, int] = {}
    if bat_frames:
        bat_all = pd.concat(bat_frames, ignore_index=True)
        # Some years return columns the others don't — fill missing with NaN.
        # DuckDB's CTAS-from-DataFrame handles that naturally.
        con.execute("DROP TABLE IF EXISTS history_statcast_batting_season")
        con.register("_bat_tmp", bat_all)
        con.execute(
            "CREATE TABLE history_statcast_batting_season AS SELECT * FROM _bat_tmp"
        )
        con.unregister("_bat_tmp")
        try:
            con.execute(
                "ALTER TABLE history_statcast_batting_season "
                "ADD PRIMARY KEY (player_id, year)"
            )
        except duckdb.ConstraintException as e:
            console.print(
                f"  [yellow]⚠[/yellow] history_statcast_batting_season PK violated: {e}"
            )
        n = con.execute(
            "SELECT COUNT(*) FROM history_statcast_batting_season"
        ).fetchone()[0]
        rows["history_statcast_batting_season"] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] history_statcast_batting_season   "
                f"[dim]{n:>8,} rows  PK=(player_id, year)[/dim]"
            )

    # Pitching --------------------------------------------------------
    pit_frames: list[pd.DataFrame] = []
    for y in range(first_year, last_year + 1):
        df = _fetch_statcast_one_year(y, batting=False)
        if df is None or len(df) == 0:
            continue
        pit_frames.append(df)
        if verbose:
            console.print(f"  pitching {y}: [dim]{len(df):,} pitchers[/dim]")
    if pit_frames:
        pit_all = pd.concat(pit_frames, ignore_index=True)
        con.execute("DROP TABLE IF EXISTS history_statcast_pitching_season")
        con.register("_pit_tmp", pit_all)
        con.execute(
            "CREATE TABLE history_statcast_pitching_season AS SELECT * FROM _pit_tmp"
        )
        con.unregister("_pit_tmp")
        try:
            con.execute(
                "ALTER TABLE history_statcast_pitching_season "
                "ADD PRIMARY KEY (player_id, year)"
            )
        except duckdb.ConstraintException as e:
            console.print(
                f"  [yellow]⚠[/yellow] history_statcast_pitching_season PK violated: {e}"
            )
        n = con.execute(
            "SELECT COUNT(*) FROM history_statcast_pitching_season"
        ).fetchone()[0]
        rows["history_statcast_pitching_season"] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] history_statcast_pitching_season  "
                f"[dim]{n:>8,} rows  PK=(player_id, year)[/dim]"
            )

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Baseball-Reference — fills the 2020-(save_start-1) gap
# ─────────────────────────────────────────────────────────────────────────────


# cdalzell/Lahman caps at 2019, but cleared MLB careers continue through
# the user's save start. BREF scraping via pybaseball fills the post-2019
# gap so retirees from 2020-2025 (Pujols 703 HR, Cabrera 511, etc.) get
# their full careers in records leaderboards.
BREF_FIRST_YEAR = 2020


def _bref_clean_batting(df):
    """Filter BREF batting frame to MLB rows; one row per (player_id, year, team)."""
    import pandas as pd
    df = df.copy()
    if "Lev" in df.columns:
        df = df[df["Lev"].isin(["Maj-AL", "Maj-NL"])]
    # mlbID is the canonical id; some rows may have NaN if BREF couldn't link.
    # Drop those — they're unusable for joins.
    if "mlbID" in df.columns:
        df = df[df["mlbID"].notna()]
        df["mlbID"] = df["mlbID"].astype(str)
    return df


def _bref_clean_pitching(df):
    """Filter BREF pitching frame to MLB rows."""
    df = _bref_clean_batting(df)  # same filter logic
    # Convert IP from BREF baseball format (172.1 = 172 1/3) to outs.
    if "IP" in df.columns:
        ip = df["IP"].astype(float)
        whole = ip.astype(int)
        frac = (ip - whole) * 10
        df["IPouts"] = (whole * 3 + frac.round().astype(int)).astype(int)
    return df


def fetch_and_load_bref(
    con: duckdb.DuckDBPyConnection,
    *,
    first_year: int = BREF_FIRST_YEAR,
    last_year: int | None = None,
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    verbose: bool = True,
) -> dict[str, int]:
    """Pull Baseball-Reference batting + pitching season stats per year.

    Defaults to `last_year = save_start_year - 1` so we don't pull
    real-life 2026/2027/etc. stats once OOTP takes over.

    Returns `{table_name: row_count}`.
    """
    import pandas as pd
    import pybaseball as pyb

    if last_year is None:
        last_year = _save_start_year(save) - 1
    if first_year > last_year:
        if verbose:
            console.rule("Baseball-Reference")
            console.print(
                f"[dim]No BREF years to fetch (first={first_year}, last={last_year}).[/dim]"
            )
        return {}

    if verbose:
        console.rule(f"Baseball-Reference  ({first_year}–{last_year})")

    bat_frames: list = []
    for y in range(first_year, last_year + 1):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                df = pyb.batting_stats_bref(y)
            except Exception as e:
                console.print(f"  [yellow]⚠[/yellow] {y} batting BREF: {e}")
                continue
        df = _bref_clean_batting(df)
        df["year"] = y
        bat_frames.append(df)
        if verbose:
            console.print(f"  batting {y}: [dim]{len(df):,} MLB rows[/dim]")

    pit_frames: list = []
    for y in range(first_year, last_year + 1):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                df = pyb.pitching_stats_bref(y)
            except Exception as e:
                console.print(f"  [yellow]⚠[/yellow] {y} pitching BREF: {e}")
                continue
        df = _bref_clean_pitching(df)
        df["year"] = y
        pit_frames.append(df)
        if verbose:
            console.print(f"  pitching {y}: [dim]{len(df):,} MLB rows[/dim]")

    rows: dict[str, int] = {}

    if bat_frames:
        bat_all = pd.concat(bat_frames, ignore_index=True)
        con.execute("DROP TABLE IF EXISTS history_bref_batting")
        con.register("_bref_bat_tmp", bat_all)
        con.execute(
            "CREATE TABLE history_bref_batting AS SELECT * FROM _bref_bat_tmp"
        )
        con.unregister("_bref_bat_tmp")
        n = con.execute("SELECT COUNT(*) FROM history_bref_batting").fetchone()[0]
        rows["history_bref_batting"] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] history_bref_batting             "
                f"[dim]{n:>8,} rows[/dim]"
            )

    if pit_frames:
        pit_all = pd.concat(pit_frames, ignore_index=True)
        con.execute("DROP TABLE IF EXISTS history_bref_pitching")
        con.register("_bref_pit_tmp", pit_all)
        con.execute(
            "CREATE TABLE history_bref_pitching AS SELECT * FROM _bref_pit_tmp"
        )
        con.unregister("_bref_pit_tmp")
        n = con.execute("SELECT COUNT(*) FROM history_bref_pitching").fetchone()[0]
        rows["history_bref_pitching"] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] history_bref_pitching            "
                f"[dim]{n:>8,} rows[/dim]"
            )

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────────────


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    *,
    skip_lahman: bool = False,
    skip_statcast: bool = False,
    skip_bref: bool = False,
    force_download: bool = False,
    statcast_first_year: int = STATCAST_FIRST_YEAR,
    statcast_last_year: int | None = None,
    bref_first_year: int = BREF_FIRST_YEAR,
    bref_last_year: int | None = None,
    history_cap_year: int | None = None,
) -> dict[str, int]:
    """Top-level `diamond fetch-history` driver — one-time backfill.

    Pulls Lahman + Statcast into `history_*` tables on the warehouse,
    capped at `save_start_year - 1` so the OOTP universe owns save
    start onward. After this lands, run `diamond ingest --rebuild-only`
    so L3 picks up the new rows in `f_record_player` /
    `f_award_career_player`.

    `history_cap_year` and `statcast_last_year` default to
    `save_start_year - 1` when None.
    """
    from diamond.schema import open_warehouse_db

    cap = history_cap_year
    if cap is None:
        cap = _save_start_year(save) - 1

    con = open_warehouse_db(save)
    db_path = save.save_dir / "diamond" / "diamond.duckdb"
    console.print(f"[bold]Warehouse:[/bold] {db_path}")
    console.print(
        f"[dim]Save starts {_save_start_year(save)} — capping historical "
        f"backfill at year {cap}.[/dim]\n"
    )

    rows: dict[str, int] = {}
    try:
        if not skip_lahman:
            rows.update(fetch_and_load_lahman(
                con, save,
                force_download=force_download,
                history_cap_year=cap,
            ))
        if not skip_statcast:
            rows.update(
                fetch_and_load_statcast(
                    con, save=save,
                    first_year=statcast_first_year,
                    last_year=statcast_last_year if statcast_last_year is not None else cap,
                )
            )
        if not skip_bref:
            rows.update(
                fetch_and_load_bref(
                    con, save=save,
                    first_year=bref_first_year,
                    last_year=bref_last_year if bref_last_year is not None else cap,
                )
            )
    finally:
        con.close()

    console.print(
        f"\n[bold]Done.[/bold] {len(rows)} history table(s) loaded. "
        f"Run [cyan]diamond ingest --rebuild-only[/cyan] to rebuild L3 with "
        f"the new historical rows."
    )
    return rows
