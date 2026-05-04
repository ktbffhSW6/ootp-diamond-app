"""Canonical stat entries for the dictionary.

See ``diamond.dictionary.__init__`` for the ``Stat`` dataclass shape and
maintenance contract. Entries are grouped by category for readability;
the order of entries here doesn't matter (consumers index by ``id``).

The thin v1 dictionary covers ~35 stats. Long-tail entries land here as
UI screens reach for them — strict rule per D15: any new label or chart
axis comes from this dictionary, never inline.
"""

from __future__ import annotations

from diamond.dictionary import Stat


# Reference URL helpers (keep entries readable).
_FG = "https://library.fangraphs.com"
_BR = "https://www.baseball-reference.com/bullpen"
_SAVANT = "https://baseballsavant.mlb.com"


_ENTRIES: list[Stat] = [

    # ─────────────────────────────────────────────────────────────────
    # Batting — slash line + rate
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="AVG",
        display_name="Batting Average",
        short_label="AVG",
        category="batting",
        formula_tex=r"\mathrm{AVG} = \dfrac{H}{AB}",
        formula_plain="AVG = H / AB",
        description=(
            "Hits per at-bat. The oldest mainstream batting metric, but "
            "treats walks as nonexistent and weights singles equally to home runs."
        ),
        units="rate (.000-1.000)",
        typical_range="MLB stars: .300+; league avg: ~.245; replacement: ~.220",
        interpretation="Higher = better. Conventionally rendered to 3 decimals.",
        caveats="Ignores walks and extra-base value. Use OBP/SLG/wOBA for richer context.",
        source="f_player_season_batting.h / f_player_season_batting.ab",
        formula_source="OOTP raw / standard",
        related=("OBP", "SLG", "OPS", "wOBA", "BABIP"),
        refs={"Fangraphs": f"{_FG}/offense/avg/", "Bref": f"{_BR}/Batting_average"},
    ),

    Stat(
        id="OBP",
        display_name="On-Base Percentage",
        short_label="OBP",
        category="batting",
        formula_tex=r"\mathrm{OBP} = \dfrac{H + BB + HBP}{AB + BB + HBP + SF}",
        formula_plain="OBP = (H + BB + HBP) / (AB + BB + HBP + SF)",
        description=(
            "Frequency of reaching base via hit, walk, or HBP. The single "
            "most predictive easy-to-compute hitting stat for run scoring."
        ),
        units="rate (.000-1.000)",
        typical_range="MLB stars: .380+; league avg: ~.315; replacement: ~.290",
        interpretation="Higher = better. ~80 points above AVG is typical.",
        caveats=None,
        source="f_player_season_batting (h, bb, hp, ab, sf)",
        formula_source="OOTP raw / standard",
        related=("AVG", "SLG", "OPS", "wOBA"),
        refs={"Fangraphs": f"{_FG}/offense/obp/", "Bref": f"{_BR}/On_Base_Percentage"},
    ),

    Stat(
        id="SLG",
        display_name="Slugging Percentage",
        short_label="SLG",
        category="batting",
        formula_tex=r"\mathrm{SLG} = \dfrac{1B + 2 \cdot 2B + 3 \cdot 3B + 4 \cdot HR}{AB}",
        formula_plain="SLG = (1B + 2*2B + 3*3B + 4*HR) / AB",
        description=(
            "Total bases per at-bat. Captures power but ignores walks; "
            "reads as a roughly .000-1.000 rate but is unbounded above 1.000 "
            "in theory (max is 4.000 for an all-HR season)."
        ),
        units="rate (.000-1.000+)",
        typical_range="MLB stars: .500+; league avg: ~.400; replacement: ~.350",
        interpretation="Higher = better. Power hitters can clear .550 in elite seasons.",
        caveats="Treats walks as zero — pair with OBP for full picture.",
        source="f_player_season_batting (h, d, t, hr, ab)",
        formula_source="OOTP raw / standard",
        related=("AVG", "OBP", "OPS", "ISO"),
        refs={"Fangraphs": f"{_FG}/offense/slg/", "Bref": f"{_BR}/Slugging_percentage"},
    ),

    Stat(
        id="OPS",
        display_name="On-Base Plus Slugging",
        short_label="OPS",
        category="batting",
        formula_tex=r"\mathrm{OPS} = \mathrm{OBP} + \mathrm{SLG}",
        formula_plain="OPS = OBP + SLG",
        description=(
            "Sum of OBP and SLG — fast, intuitive batting summary. Less "
            "precise than wOBA but instantly readable."
        ),
        units="rate (.500-1.200+)",
        typical_range="MLB stars: .900+; league avg: ~.720; elite: 1.000+",
        interpretation="Higher = better. Adds OBP to SLG without weighting; "
                       "wOBA does the proper weighted version.",
        caveats="Implicitly weights SLG higher than OBP because SLG has a wider "
                "range — wOBA corrects this.",
        source="OBP + SLG (computed)",
        formula_source="OOTP raw / standard",
        related=("OBP", "SLG", "wOBA", "OPS_plus"),
        refs={"Fangraphs": f"{_FG}/offense/ops/", "Bref": f"{_BR}/OPS"},
    ),

    Stat(
        id="ISO",
        display_name="Isolated Power",
        short_label="ISO",
        category="batting",
        formula_tex=r"\mathrm{ISO} = \mathrm{SLG} - \mathrm{AVG}",
        formula_plain="ISO = SLG - AVG",
        description=(
            "Extra-base hits per at-bat — pure power isolated from contact "
            "ability. A singles hitter and a HR specialist can have the "
            "same AVG but very different ISO."
        ),
        units="rate (.000-.350+)",
        typical_range="Power: .250+; avg: ~.150; light hitter: <.120",
        interpretation="Higher = more power. Equivalent to (2B + 2*3B + 3*HR) / AB.",
        caveats=None,
        source="diamond.advanced.sabermetric.iso_d_p",
        formula_source="Bill James",
        related=("SLG", "AVG", "HR"),
        refs={"Fangraphs": f"{_FG}/offense/iso/"},
    ),

    Stat(
        id="BABIP",
        display_name="Batting Average on Balls in Play",
        short_label="BABIP",
        category="batting",
        formula_tex=r"\mathrm{BABIP} = \dfrac{H - HR}{AB - K - HR + SF}",
        formula_plain="BABIP = (H - HR) / (AB - K - HR + SF)",
        description=(
            "Hit rate on balls put in play (excludes HR, K). A regression "
            "tell — extreme values usually mean luck rather than skill, "
            "though contact quality + speed shift the baseline."
        ),
        units="rate (.250-.350 typical)",
        typical_range="League avg: ~.300; high-BABIP: .330+; low: <.270",
        interpretation="Most players regress toward .300. Sustained .340+ "
                       "is real (high LD% + speed); sustained <.260 means "
                       "weak contact or slow.",
        caveats="One-year BABIP is noisy. Three-year rolling is more stable.",
        source="f_player_season_batting (h, hr, ab, k, sf)",
        formula_source="OOTP raw / standard",
        related=("AVG", "HARD_HIT_PCT"),
        refs={"Fangraphs": f"{_FG}/offense/babip/"},
    ),

    Stat(
        id="K_pct_batter",
        display_name="Strikeout Rate (batter)",
        short_label="K%",
        category="batting",
        formula_tex=r"\mathrm{K\%} = \dfrac{K}{PA}",
        formula_plain="K% = K / PA",
        description="Frequency the batter strikes out per plate appearance.",
        units="rate (%)",
        typical_range="Patient: <15%; league avg: ~22%; whiff-prone: 30%+",
        interpretation="Lower = better. Pairs with BB% as plate discipline.",
        caveats=None,
        source="f_player_season_batting (k / pa)",
        formula_source="OOTP raw",
        related=("BB_pct_batter", "PA", "K_pitcher"),
        refs={"Fangraphs": f"{_FG}/offense/k/"},
    ),

    Stat(
        id="BB_pct_batter",
        display_name="Walk Rate (batter)",
        short_label="BB%",
        category="batting",
        formula_tex=r"\mathrm{BB\%} = \dfrac{BB}{PA}",
        formula_plain="BB% = BB / PA",
        description="Frequency the batter walks per plate appearance.",
        units="rate (%)",
        typical_range="Elite: 12%+; league avg: ~8.5%; aggressive: <6%",
        interpretation="Higher = better. Indicates pitch selection / "
                       "willingness to take pitches.",
        caveats=None,
        source="f_player_season_batting (bb / pa)",
        formula_source="OOTP raw",
        related=("K_pct_batter", "OBP", "PA"),
        refs={"Fangraphs": f"{_FG}/offense/bb/"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Batting — counting
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="G_batter",
        display_name="Games (batter)",
        short_label="G",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games in which the player appeared as a batter (any PA). "
            "Distinct from pitcher G (mound appearances) and fielder G "
            "(defensive appearances) — two-way players have separate "
            "totals across all three."
        ),
        units="count",
        typical_range="Full-time MLB: ~140+; everyday: ~120; bench: <80",
        interpretation="Higher = more playing time. Pair with PA for "
                       "depth-of-role context.",
        caveats="Counts any game with a PA, including pinch-hit-only appearances.",
        source="f_player_season_batting.g",
        formula_source="OOTP raw",
        related=("PA", "G_pitcher"),
        refs={"Bref": f"{_BR}/Games_played"},
    ),

    Stat(
        id="AB",
        display_name="At Bats",
        short_label="AB",
        category="batting",
        formula_tex=r"\mathrm{AB} = \mathrm{PA} - BB - HBP - SF - SH - CI",
        formula_plain="AB = PA - BB - HBP - SF - SH - CI",
        description=(
            "Plate appearances excluding walks, HBPs, sacrifices, and catcher's "
            "interference. The denominator for AVG and SLG."
        ),
        units="count",
        typical_range="Full-time MLB: ~550+; everyday: ~450; bench: <250",
        interpretation="Lower than PA by ~50-100 over a full season.",
        caveats=None,
        source="f_player_season_batting.ab",
        formula_source="OOTP raw / standard",
        related=("PA", "AVG", "SLG"),
        refs={"Bref": f"{_BR}/At_bat"},
    ),

    Stat(
        id="H",
        display_name="Hits",
        short_label="H",
        category="batting",
        formula_tex=r"H = 1B + 2B + 3B + HR",
        formula_plain="H = 1B + 2B + 3B + HR",
        description="Total hits — singles plus extra-base hits.",
        units="count",
        typical_range="Star: 180+; batting-title contender: 200+",
        interpretation="Higher = more contact production. Pair with AB → AVG.",
        caveats=None,
        source="f_player_season_batting.h",
        formula_source="OOTP raw",
        related=("AB", "AVG", "D", "T", "HR"),
        refs={"Bref": f"{_BR}/Hit_(baseball)"},
    ),

    Stat(
        id="D",
        display_name="Doubles",
        short_label="2B",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Hits where the batter reached 2nd base on the play (without an "
            "error advancing). The most common extra-base hit."
        ),
        units="count",
        typical_range="Doubles hitter: 40+; league leader: 50+",
        interpretation="Higher = more gap power.",
        caveats=None,
        source="f_player_season_batting.d",
        formula_source="OOTP raw",
        related=("H", "T", "HR", "SLG", "ISO"),
        refs={"Bref": f"{_BR}/Double_(baseball)"},
    ),

    Stat(
        id="T",
        display_name="Triples",
        short_label="3B",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Hits where the batter reached 3rd base on the play. Rare; "
            "speed and ballpark geometry both contribute."
        ),
        units="count",
        typical_range="Speed-and-gap hitter: 8+; league leader: 12+",
        interpretation="Higher = speed plus gap-power combo. Park-sensitive.",
        caveats="Heavily ballpark-dependent — Coors / spacious gaps inflate.",
        source="f_player_season_batting.t",
        formula_source="OOTP raw",
        related=("H", "D", "HR", "SLG"),
        refs={"Bref": f"{_BR}/Triple_(baseball)"},
    ),

    Stat(
        id="PA",
        display_name="Plate Appearances",
        short_label="PA",
        category="batting",
        formula_tex=r"\mathrm{PA} = AB + BB + HBP + SF + SH + CI",
        formula_plain="PA = AB + BB + HBP + SF + SH + CI",
        description=(
            "Total times to the plate, regardless of outcome. The "
            "denominator for most batting rate stats and the standard "
            "qualifying threshold for leaderboards (~3.1 PA per team game)."
        ),
        units="count",
        typical_range="Full-time MLB: ~600+; everyday: ~500; bench: <250",
        interpretation="More PA = more opportunity + more sample-size signal.",
        caveats="Differs from AB — AB excludes walks, HBPs, and sacrifices.",
        source="f_player_season_batting.pa",
        formula_source="OOTP raw / standard",
        related=("BB", "K_batter"),
        refs={"Fangraphs": f"{_FG}/offense/pa/"},
    ),

    Stat(
        id="HR",
        display_name="Home Runs",
        short_label="HR",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Fair balls that land beyond the outfield fence (or are otherwise "
            "scored as HR). The single most-watched offensive counting stat."
        ),
        units="count",
        typical_range="Power hitter: 30+; star: 40+; league HR leader: ~50+",
        interpretation="Higher = more power. Bonds 73 (2001) is the all-time "
                       "single-season MLB record.",
        caveats=None,
        source="f_player_season_batting.hr",
        formula_source="OOTP raw",
        related=("RBI", "SLG", "ISO", "BARREL_PCT"),
        refs={"Bref": f"{_BR}/Home_run"},
    ),

    Stat(
        id="RBI",
        display_name="Runs Batted In",
        short_label="RBI",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Runs that score as a direct result of the batter's PA "
            "(hit, walk with bases loaded, sacrifice fly, etc.). "
            "Heavily lineup-context-dependent."
        ),
        units="count",
        typical_range="Cleanup hitter: 100+; star: 120+; MVP-tier: 130+",
        interpretation="Higher = better, but a player batting 9th has "
                       "fewer opportunities. Pair with R for context.",
        caveats="Lineup-position-dependent — leadoff hitters have systemic "
                "RBI ceilings vs cleanup batters.",
        source="f_player_season_batting.rbi",
        formula_source="OOTP raw",
        related=("R", "HR", "wRC"),
        refs={"Bref": f"{_BR}/Runs_batted_in"},
    ),

    Stat(
        id="R",
        display_name="Runs Scored",
        short_label="R",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Runs the batter scored personally — typically requires getting "
            "on base + a teammate driving them in (or hitting a HR)."
        ),
        units="count",
        typical_range="Star leadoff: 100+; MVP-tier: 120+",
        interpretation="Higher = better. Strongly correlated with OBP + lineup quality.",
        caveats="Like RBI, lineup-context-dependent.",
        source="f_player_season_batting.r",
        formula_source="OOTP raw",
        related=("RBI", "OBP"),
        refs={"Bref": f"{_BR}/Run_(baseball)"},
    ),

    Stat(
        id="BB",
        display_name="Walks (Bases on Balls)",
        short_label="BB",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Times the batter reached base via four balls. A skill in "
            "patience and pitch recognition."
        ),
        units="count",
        typical_range="Patient: 90+; league avg starter: ~50",
        interpretation="Higher = better plate discipline. Pair with K for context.",
        caveats="Includes intentional walks (IBB) by default in this metric.",
        source="f_player_season_batting.bb",
        formula_source="OOTP raw",
        related=("BB_pct_batter", "OBP", "K_batter"),
        refs={"Bref": f"{_BR}/Base_on_balls"},
    ),

    Stat(
        id="K_batter",
        display_name="Strikeouts (batter)",
        short_label="K",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description="Plate appearances ending in a strikeout.",
        units="count",
        typical_range="Patient hitter: <100; whiff-prone: 200+",
        interpretation="Lower = better, but high-K power hitters can still "
                       "be productive (modern game accepts higher K rates).",
        caveats=None,
        source="f_player_season_batting.k",
        formula_source="OOTP raw",
        related=("K_pct_batter", "BB", "K_pitcher"),
        refs={"Bref": f"{_BR}/Strikeout"},
    ),

    Stat(
        id="SB",
        display_name="Stolen Bases",
        short_label="SB",
        category="batting",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Bases gained by attempting to steal during a play not "
            "involving a hit, walk, or wild pitch."
        ),
        units="count",
        typical_range="Speedster: 30+; league leader: 50+; historical: 100+",
        interpretation="Higher = more aggressive baserunning. Pair with CS "
                       "for efficiency.",
        caveats="Without SB%, raw SB can mislead — high SB + low SB% is "
                "net-negative.",
        source="f_player_season_batting.sb",
        formula_source="OOTP raw",
        related=("R", "RBI"),
        refs={"Bref": f"{_BR}/Stolen_base"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Batting — advanced (league-relative)
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="wOBA",
        display_name="Weighted On-Base Average",
        short_label="wOBA",
        category="advanced",
        formula_tex=(
            r"\mathrm{wOBA} = \dfrac{w_{BB}\,uBB + w_{HBP}\,HBP + "
            r"w_{1B}\,1B + w_{2B}\,2B + w_{3B}\,3B + w_{HR}\,HR}"
            r"{AB + BB - IBB + SF + HBP}"
        ),
        formula_plain=(
            "wOBA = (wBB*uBB + wHBP*HBP + w1B*1B + w2B*2B + w3B*3B + wHR*HR) "
            "/ (AB + BB - IBB + SF + HBP); weights from Fangraphs linear "
            "weights table per league-year."
        ),
        description=(
            "Weighted on-base average — like OBP, but each event is weighted "
            "by its average run-value contribution. The cleanest single-stat "
            "summary of offensive output per PA."
        ),
        units="rate (matches OBP scale)",
        typical_range="MLB stars: .380+; league avg: ~.320; replacement: ~.295",
        interpretation="Higher = better. Reads exactly like OBP — .350 is "
                       "above-average, .400 is elite, .450+ is generational.",
        caveats="Weights are league-year-specific (run environment shifts). "
                "Cross-era comparisons should use wRC+ instead.",
        source="diamond.advanced.sabermetric.woba_per_player",
        formula_source="Fangraphs canonical linear weights",
        related=("OBP", "SLG", "OPS", "wRAA", "wRC_plus"),
        refs={"Fangraphs": f"{_FG}/offense/woba/"},
    ),

    Stat(
        id="wRAA",
        display_name="Weighted Runs Above Average",
        short_label="wRAA",
        category="advanced",
        formula_tex=(
            r"\mathrm{wRAA} = \dfrac{\mathrm{wOBA} - \mathrm{lgwOBA}}"
            r"{\mathrm{wOBAscale}} \times PA"
        ),
        formula_plain="wRAA = ((wOBA - lgwOBA) / wOBA_scale) * PA",
        description=(
            "Runs above average from offense. wOBA-based: a player's PA-"
            "weighted contribution above (or below) the league average bat."
        ),
        units="runs",
        typical_range="MVP-tier: +50; star: +30; replacement: ~-20 per 600 PA",
        interpretation="Positive = above-average bat; negative = below. "
                       "Roughly +10 wRAA = +1 win.",
        caveats=None,
        source="diamond.advanced.sabermetric.woba_per_player (wRAA column)",
        formula_source="Fangraphs",
        related=("wOBA", "wRC", "wRC_plus", "oWAR"),
        refs={"Fangraphs": f"{_FG}/offense/wraa/"},
    ),

    Stat(
        id="wRC",
        display_name="Weighted Runs Created",
        short_label="wRC",
        category="advanced",
        formula_tex=(
            r"\mathrm{wRC} = \left(\dfrac{\mathrm{wOBA} - \mathrm{lgwOBA}}"
            r"{\mathrm{wOBAscale}} + \mathrm{R/PA}\right) \times PA"
        ),
        formula_plain="wRC = ((wOBA - lgwOBA) / wOBA_scale + R/PA) * PA",
        description=(
            "Runs created — the absolute (not relative-to-average) version "
            "of wRAA. Counts the runs a batter produced above replacement-"
            "league-zero rather than above average."
        ),
        units="runs",
        typical_range="Star: 100+ per 600 PA; MVP-tier: 130+",
        interpretation="Higher = more runs produced. Counting-stat-shaped "
                       "version of wOBA.",
        caveats=None,
        source="diamond.advanced.sabermetric.woba_per_player (wRC column)",
        formula_source="Fangraphs",
        related=("wRAA", "wRC_plus", "wOBA"),
        refs={"Fangraphs": f"{_FG}/offense/wrc/"},
    ),

    Stat(
        id="wRC_plus",
        display_name="Weighted Runs Created Plus",
        short_label="wRC+",
        category="advanced",
        formula_tex=(
            r"\mathrm{wRC^+} = 100 \times \dfrac{\mathrm{wRC/PA}}{\mathrm{lg \, R/PA}}"
        ),
        formula_plain="wRC+ = 100 * (wRC/PA) / (league R/PA)",
        description=(
            "Park- and league-adjusted wRC, indexed so 100 = league average "
            "and each point = 1% above/below average. The cleanest cross-era "
            "comparison stat available."
        ),
        units="index (100 = lg avg)",
        typical_range="Star: 130+; MVP-tier: 160+; replacement: ~70",
        interpretation="A 145 wRC+ = 45% above league-average production "
                       "per PA, after park/league adjustment.",
        caveats="Park-halved factor in Diamond per the audit-decoded OOTP "
                "convention.",
        source="diamond.advanced.sabermetric.woba_per_player (wRCplus column)",
        formula_source="Fangraphs",
        related=("wRC", "wRAA", "OPS_plus"),
        refs={"Fangraphs": f"{_FG}/offense/wrc/"},
    ),

    Stat(
        id="OPS_plus",
        display_name="OPS Plus",
        short_label="OPS+",
        category="advanced",
        formula_tex=(
            r"\mathrm{OPS^+} = 100 \times "
            r"\dfrac{\dfrac{\mathrm{OBP}}{\mathrm{lgOBP}} + "
            r"\dfrac{\mathrm{SLG}}{\mathrm{lgSLG}} - 1}{\mathrm{PF_{halved}}}"
        ),
        formula_plain=(
            "OPS+ = 100 * (OBP/lgOBP + SLG/lgSLG - 1) / halved_park_factor; "
            "halved_park_factor = 1 + (parks.avg - 1) / 2"
        ),
        description=(
            "Park- and league-adjusted OPS, indexed so 100 = league average. "
            "Bref convention; reads similar to wRC+ but is computed off OPS "
            "rather than wOBA."
        ),
        units="index (100 = lg avg)",
        typical_range="Star: 140+; MVP-tier: 170+; replacement: ~75",
        interpretation="Cross-era comparable. 150 OPS+ = 50% above league average.",
        caveats="Halved park factor per OOTP convention (audit-verified 8/9 "
                "exact match for MLB-only Sox in reconcile.py).",
        source="diamond.advanced.sabermetric.ops_plus_per_player",
        formula_source="Bref convention; halved park factor per OOTP",
        related=("OBP", "SLG", "OPS", "wRC_plus"),
        refs={"Bref": f"{_BR}/Adjusted_OPS%2B"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Pitching — counting + rate
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="G_pitcher",
        display_name="Games (pitcher)",
        short_label="G",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Mound appearances. Distinct from G as a batter — for two-way "
            "players, this counts only games where the player pitched."
        ),
        units="count",
        typical_range="SP: ~30; closer: ~60; setup/middle: 70+",
        interpretation="Higher = more mound usage. Workload signal.",
        caveats=None,
        source="f_player_season_pitching.g",
        formula_source="OOTP raw",
        related=("GS", "IP", "G_batter"),
        refs={"Bref": f"{_BR}/Games_played"},
    ),

    Stat(
        id="GS",
        display_name="Games Started (pitcher)",
        short_label="GS",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description="Games where this pitcher was the starting pitcher.",
        units="count",
        typical_range="Full SP: 30+; swing/spot starter: 10-20; reliever: 0",
        interpretation="GS / G ratio identifies SP vs RP role.",
        caveats=None,
        source="f_player_season_pitching.gs",
        formula_source="OOTP raw",
        related=("G_pitcher", "IP"),
        refs={"Bref": f"{_BR}/Games_started"},
    ),

    Stat(
        id="L",
        display_name="Losses (pitcher)",
        short_label="L",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games where the pitcher gets credited as the losing pitcher of "
            "record. Like W, heavily team- and bullpen-dependent."
        ),
        units="count",
        typical_range="Workhorse SP: 8-12 in a typical year; rough season: 15+",
        interpretation="Lower = better, but offense-starved teams inflate "
                       "ace pitchers' losses.",
        caveats="Team-context-dependent. Use FIP / ERA+ for pitcher quality.",
        source="f_player_season_pitching.l",
        formula_source="OOTP raw",
        related=("W", "ERA", "FIP"),
        refs={"Bref": f"{_BR}/Loss_(baseball)"},
    ),

    Stat(
        id="W",
        display_name="Wins (pitcher)",
        short_label="W",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games the pitcher gets credited as the winning pitcher of "
            "record. Heavily team- and bullpen-dependent."
        ),
        units="count",
        typical_range="Ace SP: 18+; Cy contender: 20+",
        interpretation="Higher = better, but a fig-leaf metric — IP and FIP "
                       "are stronger signals.",
        caveats="Bullpen-dependent. Skubal in 2029 OOTP went 19-3 with FIP 2.65; "
                "many comparable seasons get 12-9 records under bad bullpens.",
        source="f_player_season_pitching.w",
        formula_source="OOTP raw",
        related=("SV", "FIP", "pit_WAR"),
        refs={"Bref": f"{_BR}/Win_(baseball)"},
    ),

    Stat(
        id="SV",
        display_name="Saves",
        short_label="SV",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games where the pitcher finished a winning effort under save-"
            "qualifying conditions (typically: ≤3-run lead entering the inning)."
        ),
        units="count",
        typical_range="Closer: 30+; elite closer: 40+",
        interpretation="Higher = closer leverage. Useful for role identification, "
                       "less so for pitcher quality.",
        caveats="Closer-role-dependent — a great middle reliever has 0 SV. "
                "Pair with K/9 + FIP for quality.",
        source="f_player_season_pitching.s",
        formula_source="OOTP raw",
        related=("W", "FIP", "ERA"),
        refs={"Bref": f"{_BR}/Save_(baseball)"},
    ),

    Stat(
        id="IP",
        display_name="Innings Pitched",
        short_label="IP",
        category="pitching",
        formula_tex=r"\mathrm{IP} = \mathrm{outs} \times \tfrac{1}{3}",
        formula_plain="IP = outs / 3 (rendered as integer.frac, e.g., 172.1 = 172⅓)",
        description=(
            "Total innings pitched. The denominator for most pitching rate "
            "stats and the qualifying threshold for ERA leaderboards (~1 IP "
            "per team game)."
        ),
        units="count (innings, .1/.2 fractional)",
        typical_range="Workhorse SP: 200+; closer: 60-70; long reliever: 80+",
        interpretation="Display: 172.1 = 172 1/3 IP = 517 outs.",
        caveats=(
            "Display convention: integer + (outs%3)*0.1, NOT integer.frac "
            "decimal. So 172.2 = 172 2/3 IP, not 172.667."
        ),
        source="f_player_season_pitching.outs",
        formula_source="OOTP raw / standard",
        related=("ERA", "FIP", "WHIP", "K_pitcher"),
        refs={"Bref": f"{_BR}/Innings_pitched"},
    ),

    Stat(
        id="K_pitcher",
        display_name="Strikeouts (pitcher)",
        short_label="K",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description="Total strikeouts recorded by the pitcher.",
        units="count",
        typical_range="Ace SP: 220+; Cy contender: 270+; elite closer: 90+",
        interpretation="Higher = better. Pair with IP via K/9 for rate context.",
        caveats=None,
        source="f_player_season_pitching.k",
        formula_source="OOTP raw",
        related=("FIP", "K_batter", "ERA"),
        refs={"Bref": f"{_BR}/Strikeout"},
    ),

    Stat(
        id="H_allowed",
        display_name="Hits Allowed",
        short_label="H",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description="Hits given up by the pitcher across the period.",
        units="count",
        typical_range="Workhorse SP season: 150-200 H allowed",
        interpretation="Lower = better. Pair with IP via H/9 for rate.",
        caveats="Doesn't isolate pitcher contribution from defense; FIP "
                "strips out defensive variation.",
        source="f_player_season_pitching.ha",
        formula_source="OOTP raw",
        related=("WHIP", "ERA", "FIP"),
        refs={"Bref": f"{_BR}/Hits_allowed"},
    ),

    Stat(
        id="R_allowed",
        display_name="Runs Allowed",
        short_label="R",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Runs (earned + unearned) scored against this pitcher. "
            "RA/9 is sometimes preferred over ERA in WAR computations "
            "because it's defense-blind in the same direction as FIP."
        ),
        units="count",
        typical_range="Ace season: <70; replacement-level full year: 100+",
        interpretation="Lower = better.",
        caveats="Includes unearned runs — pair with ER for context.",
        source="f_player_season_pitching.r",
        formula_source="OOTP raw",
        related=("ER", "ERA"),
        refs={"Bref": f"{_BR}/Runs_allowed"},
    ),

    Stat(
        id="ER",
        display_name="Earned Runs",
        short_label="ER",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Runs scored against the pitcher excluding those that scored "
            "as a result of fielding errors or passed balls. The numerator "
            "of ERA."
        ),
        units="count",
        typical_range="Ace SP: <60; league avg starter: ~80",
        interpretation="Lower = better.",
        caveats="The official-scorer judgement on errors makes ER slightly "
                "subjective; FIP avoids this entirely.",
        source="f_player_season_pitching.er",
        formula_source="OOTP raw",
        related=("ERA", "R_allowed"),
        refs={"Bref": f"{_BR}/Earned_run"},
    ),

    Stat(
        id="HR_allowed",
        display_name="Home Runs Allowed",
        short_label="HR",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Home runs given up. The single biggest input to FIP — each "
            "HR weighted 13× (vs 3× for BB and -2× for K)."
        ),
        units="count",
        typical_range="Ace SP: <20; HR-prone season: 30+",
        interpretation="Lower = better. Park- and contact-sensitive.",
        caveats="Park-sensitive (Coors / Yankee Stadium inflate, Petco "
                "deflates). Use ERA+ / xFIP for park-neutral readings.",
        source="f_player_season_pitching.hra",
        formula_source="OOTP raw",
        related=("FIP", "HR", "BARREL_PCT"),
        refs={"Bref": f"{_BR}/Home_run"},
    ),

    Stat(
        id="BB_allowed",
        display_name="Walks Allowed",
        short_label="BB",
        category="pitching",
        formula_tex="",
        formula_plain="(count)",
        description="Walks issued by the pitcher.",
        units="count",
        typical_range="Control artist: <30 per season; league avg SP: ~50",
        interpretation="Lower = better. Pair with IP via BB/9 for rate.",
        caveats=None,
        source="f_player_season_pitching.bb",
        formula_source="OOTP raw",
        related=("WHIP", "FIP", "BB"),
        refs={"Bref": f"{_BR}/Base_on_balls"},
    ),

    Stat(
        id="ERA",
        display_name="Earned Run Average",
        short_label="ERA",
        category="pitching",
        formula_tex=r"\mathrm{ERA} = 9 \times \dfrac{ER}{IP}",
        formula_plain="ERA = 9 * ER / IP",
        description=(
            "Earned runs allowed per 9 innings. The classic pitcher-quality "
            "summary, but noisy at small samples and influenced by defense + park."
        ),
        units="rate (runs per 9 IP)",
        typical_range="Ace: <3.00; league avg: ~4.00; replacement: ~5.50",
        interpretation="Lower = better. Pairs with FIP for luck adjustment.",
        caveats="Defense-, park-, and luck-affected. Use FIP / xFIP / SIERA to "
                "isolate pitcher contribution.",
        source="f_player_season_pitching (er, outs)",
        formula_source="OOTP raw / standard",
        related=("FIP", "WHIP", "ERA_plus", "SIERA"),
        refs={"Fangraphs": f"{_FG}/pitching/era/"},
    ),

    Stat(
        id="WHIP",
        display_name="Walks + Hits per Inning Pitched",
        short_label="WHIP",
        category="pitching",
        formula_tex=r"\mathrm{WHIP} = \dfrac{H + BB}{IP}",
        formula_plain="WHIP = (H + BB) / IP",
        description=(
            "Baserunners allowed per inning. Shorthand for how often the "
            "pitcher puts runners on; doesn't distinguish singles from HR."
        ),
        units="rate (per inning)",
        typical_range="Ace: <1.00; league avg: ~1.30; struggling: 1.50+",
        interpretation="Lower = better. 1.00 means 1 baserunner per inning.",
        caveats="Excludes HBP — strict (BB+H)/IP. Doesn't capture HR damage.",
        source="f_player_season_pitching (ha, bb, outs)",
        formula_source="standard",
        related=("ERA", "FIP"),
        refs={"Fangraphs": f"{_FG}/pitching/whip/"},
    ),

    Stat(
        id="FIP",
        display_name="Fielding Independent Pitching",
        short_label="FIP",
        category="advanced",
        formula_tex=(
            r"\mathrm{FIP} = \dfrac{13 \cdot HR + 3 \cdot (BB + HBP) - 2 \cdot K}"
            r"{IP} + \mathrm{cFIP}"
        ),
        formula_plain="FIP = (13*HR + 3*(BB + HBP) - 2*K) / IP + cFIP",
        description=(
            "Pitcher quality measured only on outcomes the pitcher fully "
            "controls (HR, BB, HBP, K). Reads on the same scale as ERA but "
            "strips out defensive luck and BABIP variation."
        ),
        units="rate (matches ERA scale)",
        typical_range="Ace: <3.00; league avg: ~4.00 (≈ lgERA); replacement: ~5.40",
        interpretation="Lower = better. The cFIP constant calibrates per-year "
                       "so league-mean FIP equals league-mean ERA exactly.",
        caveats="Doesn't credit weak-contact-inducing skill (use SIERA for that).",
        source="diamond.advanced.sabermetric.fip_per_pitcher",
        formula_source="Fangraphs canonical (DIPS family)",
        related=("ERA", "SIERA", "ERA_plus", "pit_WAR"),
        refs={"Fangraphs": f"{_FG}/pitching/fip/"},
    ),

    Stat(
        id="ERA_plus",
        display_name="ERA Plus",
        short_label="ERA+",
        category="advanced",
        formula_tex=(
            r"\mathrm{ERA^+} = 100 \times \dfrac{\mathrm{lgERA}}{\mathrm{ERA}} "
            r"\times \mathrm{PF_{80\%}}"
        ),
        formula_plain=(
            "ERA+ = 100 * (lgERA / ERA) * (1 + (parks.avg - 1) * 0.8)"
        ),
        description=(
            "Park- and league-adjusted ERA, indexed so 100 = league average. "
            "Pitchers in hitter-friendly parks get a credit (numerator bumped); "
            "pitchers in pitcher-friendly parks get docked."
        ),
        units="index (100 = lg avg)",
        typical_range="Cy-tier: 160+; ace: 130+; replacement: ~80",
        interpretation="Higher = better. 150 ERA+ = 50% better than league.",
        caveats="80% park factor per OOTP convention (audit-verified Crochet "
                "ERA+ 127 vs IE 127 for Fenway).",
        source="diamond.advanced.sabermetric.era_plus_per_pitcher",
        formula_source="Bref convention; 80% park factor per OOTP",
        related=("ERA", "FIP", "pit_WAR"),
        refs={"Bref": f"{_BR}/Adjusted_ERA%2B"},
    ),

    Stat(
        id="SIERA",
        display_name="Skill-Interactive ERA",
        short_label="SIERA",
        category="advanced",
        formula_tex=(
            r"\mathrm{SIERA} = 6.145 - 16.986\,\dfrac{K}{BF} + 11.434\,\dfrac{BB}{BF} "
            r"- 1.858\,\dfrac{GB-FB}{BF} + 7.653\left(\dfrac{K}{BF}\right)^2 "
            r"- 6.664\left(\dfrac{GB-FB}{BF}\right)^2 + \cdots"
        ),
        formula_plain=(
            "SIERA = quadratic regression on (K/BF, BB/BF, GB-FB/BF) — see "
            "Fangraphs full coefficient table"
        ),
        description=(
            "ERA estimator that rewards groundball tendency and accounts for "
            "K-BB interaction effects. Better than FIP at distinguishing "
            "weak-contact-inducing pitchers from pure power arms."
        ),
        units="rate (matches ERA scale)",
        typical_range="Ace: <3.00; league avg: ~4.00",
        interpretation="Lower = better. Often closer to next-year ERA than "
                       "current-year ERA.",
        caveats="Coefficient set is era-specific; we use the Fangraphs "
                "modern-era set verified 96/101 within ±0.1 vs IE.",
        source="diamond.audit.reconcile (SIERA derivation)",
        formula_source="Fangraphs (Eric Seidman / Matt Swartz)",
        related=("FIP", "ERA", "ERA_plus"),
        refs={"Fangraphs": f"{_FG}/pitching/siera/"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Value (WAR family)
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="WAR",
        display_name="Wins Above Replacement (OOTP)",
        short_label="WAR",
        category="value",
        formula_tex="",
        formula_plain="(OOTP-computed; opaque)",
        description=(
            "OOTP's internal WAR field. Convenient because it's already "
            "computed, but opaque — we don't see the formula. Diamond's "
            "Custom oWAR / pit_WAR are the inspectable alternatives."
        ),
        units="wins",
        typical_range="MVP-tier: 8+; star: 5+; avg starter: ~2; replacement: 0",
        interpretation="OOTP convention matches public-stats convention "
                       "(replacement = 0; ~10 runs = 1 win).",
        caveats="Black-box formula. For inspectable WAR, use oWAR / pit_WAR.",
        source="f_player_season_batting.war / f_player_season_pitching.war",
        formula_source="OOTP internal",
        related=("oWAR", "pit_WAR"),
        refs={"Fangraphs": f"{_FG}/misc/war/"},
    ),

    Stat(
        id="oWAR",
        display_name="Custom Offensive WAR",
        short_label="oWAR",
        category="value",
        formula_tex=(
            r"\mathrm{oWAR} = \dfrac{\mathrm{wRAA} + "
            r"\tfrac{20}{600} \cdot PA}{10}"
        ),
        formula_plain=(
            "oWAR = (wRAA + (20/600)*PA) / 10; "
            "replacement = -20 wRAA per 600 PA, runs_per_win = 10"
        ),
        description=(
            "Diamond's offensive-only Custom WAR, computed from wRAA with a "
            "replacement-level adjustment. Inspectable counterpart to OOTP's "
            "opaque WAR field."
        ),
        units="wins",
        typical_range="MVP-tier: 8+; star: 5+; avg full-time bat: ~2; "
                      "replacement: 0",
        interpretation="0 oWAR = replacement-level offense; 2 oWAR = "
                       "league-average bat over a full season.",
        caveats=(
            "Offensive only — does NOT include positional adjustment, "
            "baserunning runs, or defensive runs above average. "
            "For a true position-player WAR, fold those in once they're "
            "calibrated to runs."
        ),
        source="diamond.advanced.sabermetric.o_war_per_player",
        formula_source="Diamond (Fangraphs framework simplified)",
        related=("wRAA", "WAR", "wRC_plus"),
        refs={"Fangraphs": f"{_FG}/misc/war/"},
    ),

    Stat(
        id="pit_WAR",
        display_name="Custom Pitching WAR",
        short_label="pWAR",
        category="value",
        formula_tex=(
            r"\mathrm{pit\_WAR} = \dfrac{(1.13 \cdot \mathrm{lgFIP} - "
            r"\mathrm{FIP}) \cdot \tfrac{IP}{9}}{10}"
        ),
        formula_plain=(
            "pit_WAR = ((replacement_FIP - FIP) * IP/9) / 10; "
            "replacement_FIP = lgFIP * 1.13"
        ),
        description=(
            "Diamond's FIP-based pitching WAR. Replacement-level FIP is "
            "league FIP × 1.13 (a flat multiplier — Fangraphs splits this "
            "into 1.27 for SP and 1.06 for RP, but we use the geometric mean)."
        ),
        units="wins",
        typical_range="Cy-tier: 6+; ace: 4+; replacement: 0",
        interpretation="0 pit_WAR = replacement-level pitcher; positive "
                       "values scale with IP × FIP-quality.",
        caveats="Doesn't role-split SP vs RP. RP slightly over-credited, "
                "SP slightly under-credited. Refine via gs >= g/2 split if needed.",
        source="diamond.advanced.sabermetric.pit_war_per_pitcher",
        formula_source="Diamond (Fangraphs framework simplified)",
        related=("FIP", "ERA_plus", "WAR"),
        refs={"Fangraphs": f"{_FG}/misc/war/"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Statcast — exit velocity, barrel, hard-hit
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="MAX_EV",
        display_name="Maximum Exit Velocity",
        short_label="Max EV",
        category="statcast",
        formula_tex=r"\mathrm{Max\,EV} = \max(\text{exit\_velo over BIP})",
        formula_plain="MAX_EV = max(exit_velo) over balls in play",
        description=(
            "The hardest-hit ball (in mph) over the period. A pure peak-"
            "power signal — one transcendent swing can hold the leaderboard."
        ),
        units="mph",
        typical_range="Real Statcast: 110-122 mph for power hitters; "
                      "all-time MLB record 122.9 (Cruz 2025).",
        interpretation="Higher = harder peak contact.",
        caveats=(
            "OOTP's per-PA EV is NOT calibrated to Statcast — save scale "
            "averages ~5 mph below real Statcast and has a wider tail "
            "(some non-everyday batters reach 125+). See DATA_NOTES.md "
            "for the calibration probe."
        ),
        source="f_pa_event.exit_velo (save) / history_statcast_batting_season.max_hit_speed",
        formula_source="OOTP raw / Statcast raw",
        related=("AVG_EV", "BARREL_PCT", "HARD_HIT_PCT"),
        refs={"Savant": f"{_SAVANT}/leaderboard/exit-velocity"},
    ),

    Stat(
        id="AVG_EV",
        display_name="Average Exit Velocity",
        short_label="Avg EV",
        category="statcast",
        formula_tex=r"\mathrm{Avg\,EV} = \dfrac{\sum \text{exit\_velo}}{\mathrm{BBE}}",
        formula_plain="AVG_EV = mean(exit_velo) over balls in play; min 50 BBE",
        description=(
            "Mean exit velocity across balls in play. Reflects sustained "
            "contact quality — a one-pitch outlier can't carry it."
        ),
        units="mph",
        typical_range=(
            "Real Statcast: stars 92-95 mph; league avg ~88-89; "
            "save scale: stars ~88 mph, league avg ~83 (-5 mph offset)."
        ),
        interpretation="Higher = better sustained contact quality.",
        caveats=(
            "Save and Statcast scales differ — see MAX_EV caveat. "
            "Min 50 BBE applied per Statcast convention so cup-of-coffee "
            "batters don't post outlier-led leaderboards."
        ),
        source="f_pa_event.exit_velo (save) / history_statcast_batting_season.avg_hit_speed",
        formula_source="OOTP raw / Statcast raw",
        related=("MAX_EV", "BARREL_PCT", "HARD_HIT_PCT"),
        refs={"Savant": f"{_SAVANT}/leaderboard/exit-velocity"},
    ),

    Stat(
        id="HARD_HIT_PCT",
        display_name="Hard-Hit %",
        short_label="HH%",
        category="statcast",
        formula_tex=(
            r"\mathrm{HH\%} = \dfrac{|\{\text{BBE} : \text{EV} \geq 95\}|}"
            r"{\mathrm{BBE}} \times 100"
        ),
        formula_plain="HH% = (% of BBE with exit_velo ≥ 95 mph) over balls in play",
        description=(
            "Fraction of balls in play struck at 95+ mph. A consistency "
            "metric — sustained hard contact, not just peaks."
        ),
        units="rate (%)",
        typical_range=(
            "Real Statcast: stars 50%+; league avg ~38%; "
            "save scale: stars ~30%, much lower than Statcast (-5 mph "
            "scale offset shifts the cutoff effectively)."
        ),
        interpretation="Higher = more frequent hard contact.",
        caveats=(
            "Same calibration gap as AVG_EV — save HH% values are "
            "internally consistent but not directly comparable to real "
            "Statcast."
        ),
        source="f_pa_event (save) / history_statcast_batting_season.ev95percent",
        formula_source="Statcast 95-mph cutoff convention",
        related=("AVG_EV", "BARREL_PCT", "MAX_EV"),
        refs={"Savant": f"{_SAVANT}/leaderboard/hard-hit"},
    ),

    Stat(
        id="BARREL_PCT",
        display_name="Barrel %",
        short_label="Brl%",
        category="statcast",
        formula_tex=(
            r"\mathrm{Brl\%} = \dfrac{|\{\text{barrels}\}|}{\mathrm{BBE}} \times 100"
        ),
        formula_plain=(
            "Brl% = (barrel events / BBE) * 100; barrel = optimal EV/LA "
            "combo expected to produce ≥.500 AVG and ≥1.500 SLG"
        ),
        description=(
            "Fraction of balls in play categorized as barrels — Statcast's "
            "highest-quality contact bucket, defined by an EV-LA polygon."
        ),
        units="rate (%)",
        typical_range=(
            "Real Statcast: elite 17%+ (Judge 27.5% in 2023); league "
            "avg ~7-8%; save uses a flat-threshold barrel definition, "
            "not the polygon — values differ in shape."
        ),
        interpretation="Higher = more elite-quality contact.",
        caveats=(
            "Save's barrel% uses a flat EV+LA threshold rather than "
            "Statcast's full expanding polygon (per audit decode). "
            "Numerically similar but not identical."
        ),
        source="history_statcast_batting_season.brl_percent",
        formula_source="Statcast (EV-LA polygon)",
        related=("HARD_HIT_PCT", "MAX_EV", "SWEET_SPOT_PCT"),
        refs={"Savant": f"{_SAVANT}/leaderboard/barrels"},
    ),

    Stat(
        id="SWEET_SPOT_PCT",
        display_name="Sweet-Spot %",
        short_label="SwSp%",
        category="statcast",
        formula_tex=(
            r"\mathrm{SwSp\%} = \dfrac{|\{\text{BBE}: 8° \leq \text{LA} \leq 32°\}|}"
            r"{\mathrm{BBE}} \times 100"
        ),
        formula_plain=(
            "SwSp% = (% of BBE with launch_angle in [8°, 32°]) over BIP"
        ),
        description=(
            "Fraction of balls in play hit in the optimal launch-angle "
            "range. Captures angle without requiring high EV."
        ),
        units="rate (%)",
        typical_range="Real Statcast: elite 38%+; league avg ~33%",
        interpretation="Higher = more line-drive / shallow-fly tendency.",
        caveats=None,
        source="history_statcast_batting_season.anglesweetspotpercent",
        formula_source="Statcast convention",
        related=("BARREL_PCT", "AVG_EV"),
        refs={"Savant": f"{_SAVANT}/leaderboard/sweet-spot"},
    ),

    # ─────────────────────────────────────────────────────────────────
    # Fielding — counting + rate
    # ─────────────────────────────────────────────────────────────────

    Stat(
        id="G_fielder",
        display_name="Games (fielding)",
        short_label="G",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games played at this defensive position. A multi-position "
            "player has separate G totals per position — a UTIL with "
            "30 games at 2B + 20 at SS + 15 at 3B totals 65 G across "
            "positions, not 65 in any one row."
        ),
        units="count",
        typical_range="Everyday: 130+; backup at the position: <50",
        interpretation="Higher = more time at this spot. Add across "
                       "positions for total defensive games.",
        caveats="Per-position; sums across positions for the same year/"
                "team can exceed the player's batting G if they switched "
                "positions mid-game.",
        source="f_player_season_fielding.g",
        formula_source="OOTP raw",
        related=("GS_fielder", "G_batter", "INN"),
        refs={"Bref": f"{_BR}/Games_played"},
    ),

    Stat(
        id="GS_fielder",
        display_name="Games Started (fielding)",
        short_label="GS",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Games started at this position. Distinguishes a true "
            "regular at the spot from a late-game defensive replacement."
        ),
        units="count",
        typical_range="Everyday: 130+; platoon partner: 60-90; sub: <30",
        interpretation="GS / G ratio identifies regular vs. backup status.",
        caveats=None,
        source="f_player_season_fielding.gs",
        formula_source="OOTP raw",
        related=("G_fielder", "INN"),
        refs={"Bref": f"{_BR}/Games_started"},
    ),

    Stat(
        id="INN",
        display_name="Innings (fielding)",
        short_label="INN",
        category="fielding",
        formula_tex=r"\mathrm{INN} = \mathrm{ip} + \tfrac{\mathrm{ipf}}{3}",
        formula_plain=(
            "INN = ip + ipf/3 (rendered as integer.frac, e.g., 147.0 = 147 IP, "
            "147.1 = 147⅓, 147.2 = 147⅔)"
        ),
        description=(
            "Defensive innings at this position. The denominator for "
            "RF/9 and similar rate stats. Bref-style display: integer + "
            "fractional outs (`.1` = 1 out, `.2` = 2 outs)."
        ),
        units="count (innings, .1/.2 fractional)",
        typical_range="Full season at one position: 1300+; backup: <500",
        interpretation="Display: 147.1 = 147⅓ defensive innings.",
        caveats=(
            "Display convention: integer + (ipf)*0.1, NOT integer.frac "
            "decimal. Same rule as IP for pitching."
        ),
        source="f_player_season_fielding.ip + ipf/3",
        formula_source="OOTP raw / standard",
        related=("G_fielder", "RF_per_9"),
        refs={"Bref": f"{_BR}/Innings_played"},
    ),

    Stat(
        id="PO",
        display_name="Putouts",
        short_label="PO",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Defensive plays where the player records the out by tagging "
            "the runner, catching a fly ball, or stepping on a base. "
            "Highly position-dependent — first basemen rack up PO from "
            "throws across the diamond, outfielders from fly balls."
        ),
        units="count",
        typical_range="1B: 1200+; OF: 250-400; SS: 200-280; pitcher: <50",
        interpretation="Higher = more plays. Compare WITHIN position only.",
        caveats="Strongly position-dependent; cross-position raw PO "
                "comparisons are meaningless.",
        source="f_player_season_fielding.po",
        formula_source="OOTP raw",
        related=("A", "FPCT", "RF_per_9"),
        refs={"Bref": f"{_BR}/Putout"},
    ),

    Stat(
        id="A",
        display_name="Assists",
        short_label="A",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Defensive plays where the player throws or deflects to a "
            "teammate who records the out. Infielders dominate — SS and "
            "2B accumulate hundreds per season, outfielders rack up "
            "double-digits at most."
        ),
        units="count",
        typical_range="SS: 400+; 3B: 250+; 2B: 350+; OF: 5-15",
        interpretation="Higher = more throws made. Position-dependent.",
        caveats="Don't compare across positions; OF assists are a "
                "fundamentally different skill (arm + situational reads).",
        source="f_player_season_fielding.a",
        formula_source="OOTP raw",
        related=("PO", "FPCT", "RF_per_9"),
        refs={"Bref": f"{_BR}/Assist_(baseball)"},
    ),

    Stat(
        id="E",
        display_name="Errors",
        short_label="E",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Defensive plays the player should have made but didn't. "
            "Subjective scorer judgement — modern advanced metrics "
            "(DRS / UZR / OAA) avoid the official-scorer dependency."
        ),
        units="count",
        typical_range="Gold-glove tier: <10; bad season at a position: 25+",
        interpretation="Lower = better. Pair with FPCT for rate context.",
        caveats="Official-scorer-subjective. Pair with range-based metrics "
                "(DRS / UZR / OAA) for fielder evaluation.",
        source="f_player_season_fielding.e",
        formula_source="OOTP raw",
        related=("FPCT", "PO", "A"),
        refs={"Bref": f"{_BR}/Error_(baseball)"},
    ),

    Stat(
        id="DP",
        display_name="Double Plays",
        short_label="DP",
        category="fielding",
        formula_tex="",
        formula_plain="(count)",
        description=(
            "Double plays this player participated in (as a fielder of "
            "record on either out). Concentrated at SS, 2B, 1B — the "
            "6-4-3 / 4-6-3 / 5-4-3 routes."
        ),
        units="count",
        typical_range="2B: 100+; SS: 80+; 1B: 130+; OF: <5",
        interpretation="Higher = more pivot opportunity. Strongly affected "
                       "by team groundball rate and runners-on rate.",
        caveats="Team-context-dependent — high-K pitching staffs starve "
                "infielders of DP opportunities.",
        source="f_player_season_fielding.dp",
        formula_source="OOTP raw",
        related=("PO", "A"),
        refs={"Bref": f"{_BR}/Double_play"},
    ),

    Stat(
        id="FPCT",
        display_name="Fielding Percentage",
        short_label="FPCT",
        category="fielding",
        formula_tex=r"\mathrm{FPCT} = \dfrac{PO + A}{PO + A + E}",
        formula_plain="FPCT = (PO + A) / (PO + A + E)",
        description=(
            "Successful defensive plays as a fraction of total chances. "
            "The classic measure but a flawed one — doesn't reward range "
            "(a poor fielder who never reaches a ball can post a perfect "
            "FPCT)."
        ),
        units="rate (.000-1.000)",
        typical_range="Gold-glove tier: .985+; league avg: ~.980; rough: <.965",
        interpretation="Higher = fewer errors per chance. Use DRS / UZR "
                       "for true defensive value.",
        caveats="Doesn't distinguish range from sure-handedness — a "
                "player who never gets to the ball can't make an error.",
        source="f_player_season_fielding (po, a, e)",
        formula_source="standard",
        related=("E", "PO", "A", "RF_per_9"),
        refs={"Bref": f"{_BR}/Fielding_percentage"},
    ),

    Stat(
        id="RF_per_9",
        display_name="Range Factor per 9 Innings",
        short_label="RF/9",
        category="fielding",
        formula_tex=r"\mathrm{RF/9} = \dfrac{9 \cdot (PO + A)}{IP}",
        formula_plain="RF/9 = 9 * (PO + A) / IP",
        description=(
            "Defensive plays made per 9 innings. Higher = wider range or "
            "higher chance frequency. Position-dependent — center fielders "
            "get more chances than third basemen, so RF/9 isn't directly "
            "comparable across positions."
        ),
        units="plays per 9 IP",
        typical_range="SS: ~4.5; CF: ~2.6; 1B: ~9 (chances dominated by 3B/SS throws)",
        interpretation="Higher = more chances handled. Compare WITHIN position only.",
        caveats="Doesn't distinguish range from positioning luck. Pair with "
                "scouted ratings (RNG / DEF) for full picture.",
        source="diamond.advanced.defensive.range_factor",
        formula_source="standard",
        related=("Framing_plus",),
        refs={"Bref": f"{_BR}/Range_factor"},
    ),

    Stat(
        id="Framing_plus",
        display_name="Catcher Framing Plus",
        short_label="Fram+",
        category="fielding",
        formula_tex=(
            r"\mathrm{Fram^+} = 100 + 10 \cdot "
            r"\dfrac{\mathrm{framing} - \mathrm{lg\,framing}}"
            r"{\sigma_{\mathrm{framing}}}"
        ),
        formula_plain=(
            "Framing+ = 100 + 10 * (player - lg_avg) / lg_stdev; "
            "100 = avg, 110 = +1σ"
        ),
        description=(
            "League-relative catcher framing index. Z-scored against "
            "league-average catcher framing × 10, anchored at 100."
        ),
        units="index (100 = lg avg, 10 = 1σ)",
        typical_range="Elite: 115+; below avg: <90",
        interpretation="Higher = better at converting borderline pitches "
                       "into strikes.",
        caveats="Catchers only (position=2). Min 20 G qualifying.",
        source="diamond.advanced.defensive.catcher_framing_plus",
        formula_source="Diamond (z-score normalization)",
        related=("RF_per_9",),
        refs={"Fangraphs": f"{_FG}/defense/framing/"},
    ),

]


# Build the canonical id-keyed mapping. Detect duplicates explicitly —
# silent override would be a maintenance trap.
_seen: set[str] = set()
STATS: dict[str, Stat] = {}
for _s in _ENTRIES:
    if _s.id in _seen:
        raise ValueError(f"Duplicate Stat id: {_s.id!r} in dictionary")
    _seen.add(_s.id)
    STATS[_s.id] = _s
del _seen, _ENTRIES, _s
