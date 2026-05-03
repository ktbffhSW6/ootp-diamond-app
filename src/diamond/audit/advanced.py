"""Driver: run every advanced-stats module and produce a markdown report.

Picks an audit subject (default: the top Red Sox MLB hitter by PA + top
pitcher by IP) and produces a per-player report showing each metric.

Also produces league-wide top-N tables for each metric.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from rich.console import Console

from diamond.advanced import contact, defensive, approach, sabermetric, situational
from diamond.advanced.enriched import materialize_enriched_ab
from diamond.advanced.league_constants import compute_constants
from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# DuckDB setup
# ─────────────────────────────────────────────────────────────────────────────


def _csv(p: Path) -> str:
    return f"'{p.as_posix()}'"


def _connect(save: SaveConfig, dump: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    csvs = {
        "at_bat":       "players_at_bat_batting_stats.csv",
        "career_bat":   "players_career_batting_stats.csv",
        "career_pit":   "players_career_pitching_stats.csv",
        "career_field": "players_career_fielding_stats.csv",
        "games":        "games.csv",
        "players":      "players.csv",
        "teams":        "teams.csv",
    }
    csv_dir = save.csv_dir(dump)
    for view, fname in csvs.items():
        con.execute(
            f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto({_csv(csv_dir / fname)}, "
            f"sample_size=-1, ignore_errors=true)"
        )
    return con


def _player_name_lookup(con: duckdb.DuckDBPyConnection, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    id_list = ",".join(str(i) for i in ids if i is not None)
    rows = con.execute(
        f"SELECT player_id, first_name || ' ' || last_name AS name "
        f"FROM players WHERE player_id IN ({id_list})"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# Top-N renderer
# ─────────────────────────────────────────────────────────────────────────────


def _top_n_table(
    title: str,
    rows: list[tuple],
    cols: list[str],
    name_lookup: dict[int, str],
    n: int = 10,
    name_col_idx: int = 0,
) -> list[str]:
    """Render a top-N markdown table.

    `rows` = list of tuples whose first column is a player_id (the grouping key).
    `cols` = column headers; the first should be the name column header (e.g. "Player").
    """
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    out = [f"### {title}", "", header, sep]
    for row in rows[:n]:
        pid = row[0]
        name = name_lookup.get(pid, f"#{pid}")
        body = " | ".join(str(v) if v is not None else "—" for v in row[1:])
        out.append(f"| {name} | {body} |")
    out.append("")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main driver
# ─────────────────────────────────────────────────────────────────────────────


def run(
    save: SaveConfig = BUILDING_THE_GREEN_MONSTER,
    dump: str | None = None,
    year: int | None = None,
    league_id: int = 203,
    output_path: Path | None = None,
) -> Path:
    dump = dump or save.latest_dump_name()
    output_path = output_path or Path("audit_output") / "advanced_stats_report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = _connect(save, dump)
    if year is None:
        # Pick the most recent season present in the dump's career-batting log.
        # IE-aligned semantics: mid-season dumps return the in-progress year;
        # offseason dumps return the year that just ended.
        year = con.execute(
            "SELECT MAX(year) FROM career_bat WHERE split_id = 1"
        ).fetchone()[0]

    console.rule(f"[bold cyan]Advanced stats — {save.save_name} / {dump} / {year} MLB")

    # 1. Build league constants
    console.print("  - computing league constants...")
    lc = compute_constants(con, year, league_id)

    # 2. Materialize enriched at-bat view
    console.print("  - materializing enriched_ab (at-bat events with derived flags)...")
    materialize_enriched_ab(con)
    n_ab = con.execute("SELECT COUNT(*) FROM enriched_ab WHERE game_type = 0").fetchone()[0]
    console.print(f"    {n_ab:,} regular-season at-bat events loaded")

    # 3. Build RE matrix
    console.print("  - building empirical Run Expectancy matrix from at-bat data...")
    re_matrix = situational.build_re_matrix(con)

    md = [
        "# Modern Advanced Stats Report",
        "",
        f"- **Save**: `{save.save_name}`",
        f"- **Dump**: `{dump}`",
        f"- **Scope**: MLB ({year})",
        f"- **At-bat events**: {n_ab:,} (regular season)",
        "",
        "## League constants",
        "",
        "_Computed from `players_career_*_stats` aggregates for the year/league._",
        "",
        f"- League rates: AVG `{lc.lg_avg}` / OBP `{lc.lg_obp}` / SLG `{lc.lg_slg}` / OPS `{lc.lg_ops}` / BABIP `{lc.lg_babip}` / ERA `{lc.lg_era}`",
        f"- Runs per PA: `{lc.runs_per_pa}` (used for wRC normalization)",
        f"- wOBA scale: `{lc.woba_scale}`",
        f"- Linear weights: wBB=`{lc.wBB}` wHBP=`{lc.wHBP}` w1B=`{lc.w1B}` w2B=`{lc.w2B}` w3B=`{lc.w3B}` wHR=`{lc.wHR}`",
        f"- FIP constant: `{lc.fip_constant}`",
        "",
        "## Run Expectancy matrix (derived from this season's at-bat data)",
        "",
        "_Mean runs from this state to end of half-inning._",
        "",
        "| base_state | outs | n | exp_runs |",
        "| --- | --- | --- | --- |",
    ]
    for bs, outs, n, er in re_matrix:
        md.append(f"| {bs} | {outs} | {n:,} | {er} |")
    md.append("")
    md.append("Base-state encoding: 0=empty, 1=1st, 2=2nd, 3=1st+2nd, 4=3rd, 5=1st+3rd, 6=2nd+3rd, 7=loaded.")
    md.append("")

    # 4. Run each metric, collect names for the top results
    console.print("  - computing Tier 1 (contact quality)...")
    hh_buckets = contact.hard_hit_buckets(con)
    sweet     = contact.sweet_spot_pct(con)
    barrel    = contact.barrel_pct(con)
    squared   = contact.squared_up_pct(con)
    ev_buckets= contact.avg_ev_by_bip_type(con)
    spray     = contact.spray_pct(con)
    pit_qual  = contact.pitcher_contact_quality_allowed(con)

    console.print("  - computing Tier 2 (situational)...")
    risp      = situational.risp_split(con)
    two_out   = situational.two_out_split(con)
    pinch     = situational.pinch_hit_split(con)
    late_clo  = situational.late_close_split(con)
    by_inning = situational.by_inning_split(con)
    by_lev    = situational.by_leverage_tier(con)
    re24      = situational.re24_per_player(con)

    console.print("  - computing Tier 3 (sabermetric)...")
    woba      = sabermetric.woba_per_player(con, lc)
    ops_plus  = sabermetric.ops_plus_per_player(con, lc)
    era_plus  = sabermetric.era_plus_per_pitcher(con, lc)
    fip       = sabermetric.fip_per_pitcher(con, lc)
    psn       = sabermetric.power_speed_number(con, lc)
    speed_sc  = sabermetric.speed_score(con, lc)
    iso       = sabermetric.iso_d_p(con, lc)

    console.print("  - computing Tier 4 (defensive)...")
    rf        = defensive.range_factor(con, year, league_id)
    framing   = defensive.catcher_framing_plus(con, year, league_id)
    of_assist = defensive.of_assist_rate(con, year, league_id)

    console.print("  - computing Tier 5 (approach)...")
    two_k     = approach.two_strike_performance(con)
    count_st  = approach.count_state_splits(con)
    fp_bb     = approach.four_pitch_walks_rate(con)
    tp_k      = approach.three_pitch_k_rate(con)

    # 5. Collect every player_id we might display. Cheap to look up all of them
    # rather than guess which subset will appear after filtering / re-sorting.
    all_ids: set[int] = set()
    for source in [hh_buckets, sweet, barrel, squared, ev_buckets, spray, pit_qual,
                   risp, two_out, pinch, late_clo, by_lev, re24,
                   woba, ops_plus, era_plus, fip, psn, speed_sc, iso,
                   rf, framing, of_assist, two_k, fp_bb, tp_k]:
        for row in source:
            if row[0] is not None:
                all_ids.add(row[0])
    names = _player_name_lookup(con, list(all_ids))

    # 6. Render report sections
    # Minimum-sample thresholds for top-N rate-stat displays
    MIN_BIP = 100   # contact-quality
    MIN_PA  = 250   # batting rate stats
    MIN_IP_OUTS = 90  # 30 IP

    def _qual(rows, idx, threshold):
        return [r for r in rows if (r[idx] or 0) >= threshold]

    md.append("## Tier 1 — Modern Contact Quality")
    md.append("")
    md.extend(_top_n_table(
        f"Hard Hit % buckets (95+/100+/105+/110+ mph) — top 10 by 95+% (min {MIN_BIP} BIP)",
        sorted(_qual(hh_buckets, 1, MIN_BIP), key=lambda r: -(r[2] or 0)),
        ["Player", "BIP", "95%+", "100%+", "105%+", "110%+"], names))
    md.extend(_top_n_table(
        f"Sweet Spot % (LA 8°-32°) — top 10 (min {MIN_BIP} BIP)",
        _qual(sweet, 1, MIN_BIP), ["Player", "BIP", "Sweet%"], names))
    md.extend(_top_n_table(
        f"Barrel % (Statcast formula, expanding LA window) — top 10 (min {MIN_BIP} BIP)",
        _qual(barrel, 1, MIN_BIP), ["Player", "BIP", "Barrels", "Barrel%"], names))
    md.extend(_top_n_table(
        f"Squared-up % (top-decile EV proxy) — top 10 (min {MIN_BIP} BIP)",
        _qual(squared, 1, MIN_BIP), ["Player", "BIP", "Squared%"], names))
    md.extend(_top_n_table(
        "Average EV by BIP type (GB / LD / FB) — top 10 by overall EV",
        sorted(ev_buckets, key=lambda r: -(r[4] or 0)),
        ["Player", "EV-GB", "EV-LD", "EV-FB", "EV-Overall"], names))
    md.extend(_top_n_table(
        "Pull / Center / Oppo % — top 10 most-pull (min 100 BIP)",
        sorted([r for r in spray if (r[1] or 0) >= 100], key=lambda r: -(r[2] or 0)),
        ["Player", "BIP", "Pull%", "Cent%", "Oppo%"], names))
    md.extend(_top_n_table(
        "Pitcher contact-quality allowed — top 10 worst by Hard Hit % allowed (min 50 BIP)",
        sorted([r for r in pit_qual if (r[1] or 0) >= 50], key=lambda r: -(r[4] or 0)),
        ["Pitcher", "BIP-allowed", "EV-allowed", "LA-allowed", "HardHit%-allowed", "Barrel%-allowed"], names))

    md.append("## Tier 2 — Situational / Leverage")
    md.append("")
    md.extend(_top_n_table(
        "RISP — slash line with runners in scoring position (top 10 by PA)",
        risp, ["Player", "Split", "PA", "AB", "H", "HR", "BB", "K", "AVG", "OBP", "SLG"], names))
    md.extend(_top_n_table(
        "2 Outs — slash line with 2 outs (top 10 by PA)",
        two_out, ["Player", "Split", "PA", "AB", "H", "HR", "BB", "K", "AVG", "OBP", "SLG"], names))
    md.extend(_top_n_table(
        "Pinch Hit performance (top 10 by PA)",
        pinch, ["Player", "Split", "PA", "AB", "H", "HR", "BB", "K", "AVG", "OBP", "SLG"], names))
    md.extend(_top_n_table(
        "Late & Close (Close=1 AND inning>=7) (top 10 by PA)",
        late_clo, ["Player", "Split", "PA", "AB", "H", "HR", "BB", "K", "AVG", "OBP", "SLG"], names))
    md.extend(_top_n_table(
        "RE24 exposure — total expected-runs faced across all PAs (top 10)",
        re24, ["Player", "PA", "Exp-Runs-Exposed", "Avg-RE/PA"], names))

    md.append("## Tier 3 — Sabermetric (with league constants)")
    md.append("")
    md.extend(_top_n_table(
        f"wOBA / wRAA / wRC / wRC+ — top 10 by wRC (min {MIN_PA} PA)",
        _qual(woba, 1, MIN_PA),
        ["Player", "PA", "wOBA", "wRAA", "wRC", "wRC+"], names))
    md.extend(_top_n_table(
        f"OPS+ (park-neutral) — top 10 (min {MIN_PA} PA)",
        _qual(ops_plus, 1, MIN_PA),
        ["Player", "PA", "OBP", "SLG", "OPS+"], names))
    md.extend(_top_n_table(
        "ERA+ — top 10 (10+ IP)",
        era_plus, ["Pitcher", "IP", "ERA", "ERA+"], names))
    md.extend(_top_n_table(
        "FIP — top 10 lowest (10+ IP)",
        fip, ["Pitcher", "IP", "FIP"], names))
    md.extend(_top_n_table(
        "Power-Speed Number — top 10",
        psn, ["Player", "HR", "SB", "PSN"], names))
    md.extend(_top_n_table(
        "Speed Score (Bill James composite) — top 10",
        speed_sc, ["Player", "Speed Score"], names))
    md.extend(_top_n_table(
        "isoP / isoD — top 10 by isoP (min 200 PA)",
        sorted([r for r in iso if (r[1] or 0) >= 200], key=lambda r: -(r[5] or 0)),
        ["Player", "PA", "AVG", "SLG", "OBP", "isoP", "isoD"], names))

    md.append("## Tier 4 — Defensive")
    md.append("")
    md.extend(_top_n_table(
        "Range Factor (RF/9, RF/G) — top 10 by RF/9 (min 10 G)",
        rf, ["Player", "Pos", "G", "PO", "A", "IP", "RF/G", "RF/9"], names))
    md.extend(_top_n_table(
        "Catcher Framing+ (lg-relative, 100 = avg, 110 = +1σ) — top 10",
        framing, ["Catcher", "G", "Framing", "Framing+"], names))
    md.extend(_top_n_table(
        "OF Assist Rate (per 1000 IP) — top 10",
        of_assist, ["Player", "Pos", "G", "A", "PO", "IP", "Asst/1000IP"], names))

    md.append("## Tier 5 — Approach Metrics (terminal-count proxies)")
    md.append("")
    md.extend(_top_n_table(
        "2-strike performance — slash line in PAs ending at 2 strikes (top 10 by PA)",
        two_k, ["Player", "PA", "AB", "H", "HR", "BB", "K", "AVG-2K", "OBP-2K", "SLG-2K"], names))
    md.extend(_top_n_table(
        "Four-pitch walk rate (P) — top 10 worst (min 5 BB allowed)",
        fp_bb, ["Pitcher", "BB", "4pitch BB", "4pitch BB%"], names))
    md.extend(_top_n_table(
        "Three-pitch K rate (P) — top 10 best (min 10 K)",
        tp_k, ["Pitcher", "K", "3pitch K", "3pitch K%"], names))

    md.append("---")
    md.append("")
    md.append(f"*Sample table (count_state_splits) — first 30 rows of {len(count_st):,} for sanity:*")
    md.append("")
    md.append("| Player | count_state | PA | AB | H | AVG |")
    md.append("| --- | --- | --- | --- | --- | --- |")
    for r in count_st[:30]:
        nm = names.get(r[0], f"#{r[0]}")
        md.append(f"| {nm} | {r[1]} | {r[2]} | {r[4]} | {r[3]} | {r[5]} |")
    md.append("")

    output_path.write_text("\n".join(md), encoding="utf-8")
    console.print(f"\n[green]Report written:[/green] {output_path}")
    return output_path


if __name__ == "__main__":
    run()
