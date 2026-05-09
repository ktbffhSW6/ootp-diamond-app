"""Player endpoint Pydantic schemas.

The single response shape `PlayerResponse` is the contract for the player
page's Stats tab. It carries:

- bio (name, position, current team, retired flag, etc.)
- per-(year, level, team) batting stints with both counting + slash-line
- per-(year, level, team) pitching stints with both counting + ERA/WHIP
- a synthesized "combined" row per season when there were multiple stints
  (the Bref "TOT" row). The frontend uses ``combined`` to know whether to
  render a top-level "TOT" row + indented stints, or just the single stint.
- career totals across all stints

Fielding stats (added 2026-05-07): `PlayerFieldingRow` is keyed by
`(year, league, level, team, position)` — note the extra `position`
dimension vs batting/pitching. A single player can have multiple
fielding rows in one (year, team) pair when they played multiple
positions; we render those as flat rows rather than a TOT-style
disclosure since combining PO+A+E across positions doesn't carry
meaningful semantics.

What's intentionally NOT here yet (deferred to a follow-up slice):

- Advanced stats (wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR) — currently
  computed in `diamond.advanced.*` over the full warehouse; routing them
  through the player endpoint requires either materializing per-season
  advanced facts or threading the on-demand computation through the
  request handler. Either is a meaningful chunk of work.
- Statcast-cohort fields (MAX_EV / AVG_EV / barrel% etc.) — defer to
  the player Charts tab.

Per D15 maintenance contract: every numeric field maps to a `STATS[id]`
in the dictionary. Field names match dictionary ids (lowercased) where
possible, so the frontend's column header lookup is mechanical.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# Bio
# ─────────────────────────────────────────────────────────────────────────────


class TeamRef(BaseModel):
    """Slim team reference embedded in stints + bio.

    Carries enough to render a column without round-tripping the team list:
    abbr (short label), nickname (long label), league_abbr (e.g. "AL/NL"
    or affiliate league), and level_id (mapped to MLB/AAA/AA/etc. via
    `LEVEL_NAMES` on the frontend or via the `level_name` convenience).
    """

    model_config = ConfigDict(frozen=True)

    team_id: int
    abbr: str | None
    nickname: str | None
    league_id: int | None
    league_abbr: str | None
    level_id: int | None
    level_name: str | None


class PlayerBio(BaseModel):
    """Identifying / display fields for the player header.

    `position_name` is the resolved display string ("1B", "RHP", etc.)
    via `POSITION_NAMES`. `bats_throws` collapses bats + throws to
    Bref-style "L/R" / "R/R" / "S/R" — three letters of useful signal
    in one line of the header.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    bbref_id: str | None      # `players.historical_id` — null for AI-generated
    first_name: str
    last_name: str
    nick_name: str | None
    full_name: str            # convenience: nick_name takes precedence over first_name
    age: int | None
    date_of_birth: str | None    # ISO yyyy-mm-dd; serialized as string
    height_cm: int | None        # OOTP stores cm; frontend converts if needed
    weight_kg: int | None
    bats: int | None             # raw OOTP code; 1=R, 2=L, 3=S
    throws: int | None           # raw OOTP code; 1=R, 2=L
    bats_throws: str             # display: "L/R", "R/R", "S/R", or "?/?"
    position: int | None         # raw OOTP code 1-10
    position_name: str           # display: "1B", "RHP", etc.
    uniform_number: int | None
    retired: bool
    free_agent: bool
    hall_of_fame: bool
    current_team: TeamRef | None     # null if no current team (FA / retired)


# ─────────────────────────────────────────────────────────────────────────────
# Per-stint batting / pitching
# ─────────────────────────────────────────────────────────────────────────────


class PlayerBattingStint(BaseModel):
    """One batter row at (year, league, level, team) grain.

    Counting fields come straight from `f_player_season_batting`; rate
    fields are computed in the route. `is_combined=True` flags the
    synthesized per-season "TOT" row (team_id is null on those).
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    is_combined: bool
    team: TeamRef | None
    # Counting (match dictionary ids: G_batter→g, AB, H, D, T, HR, RBI, R,
    # SB, CS, BB, K_batter→so, HBP→hp, SF, PA, ...)
    g: int
    pa: int
    ab: int
    r: int
    h: int
    d: int            # 2B
    t: int            # 3B
    hr: int
    rbi: int
    sb: int
    cs: int
    bb: int
    so: int
    hbp: int
    sf: int
    # Rate (computed; None when denominator is zero)
    avg: float | None
    obp: float | None
    slg: float | None
    ops: float | None


class PlayerBattingSeason(BaseModel):
    """A year's worth of batting — one or more stints + optional TOT row.

    `stints` always has 1+ rows (sorted by level then team). `combined`
    is populated only when there were multiple stints; equal to None
    when a single stint covers the whole year.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    stints: list[PlayerBattingStint]
    combined: PlayerBattingStint | None


class PlayerPitchingStint(BaseModel):
    """One pitcher row at (year, league, level, team) grain.

    `ip_display` is the Bref-style innings-pitched representation
    (172.1 = 172⅓ IP = 517 outs); the frontend renders it as-is. Use
    `outs` for any computation — display-form IP is lossy across
    arithmetic.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    is_combined: bool
    team: TeamRef | None
    # Counting
    g: int
    gs: int
    w: int
    l: int                # noqa: E741 — matches dictionary id "L" + Bref column convention
    sv: int
    outs: int             # canonical IP storage; ip_display derived
    ip_display: float     # 517 outs → 172.1 (Bref convention)
    h: int                # H allowed
    r: int                # R allowed
    er: int
    hr: int               # HR allowed
    bb: int
    so: int
    bf: int
    # Rate (computed; None when denominator is zero)
    era: float | None
    whip: float | None
    k_per_9: float | None
    bb_per_9: float | None


class PlayerPitchingSeason(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    stints: list[PlayerPitchingStint]
    combined: PlayerPitchingStint | None


# ─────────────────────────────────────────────────────────────────────────────
# Career totals
# ─────────────────────────────────────────────────────────────────────────────


class PlayerCareerBatting(BaseModel):
    """Cross-season cross-level batting career totals (counting + slash).

    Computed by SUMing every stint with split_id=1 (the overall split),
    matching the convention in `f_player_career`. Restricted to
    counting-stat fields per Decision D11 — rate stats are derivable.
    """

    model_config = ConfigDict(frozen=True)

    g: int
    pa: int
    ab: int
    r: int
    h: int
    d: int
    t: int
    hr: int
    rbi: int
    sb: int
    cs: int
    bb: int
    so: int
    hbp: int
    sf: int
    avg: float | None
    obp: float | None
    slg: float | None
    ops: float | None


class PlayerCareerPitching(BaseModel):
    model_config = ConfigDict(frozen=True)

    g: int
    gs: int
    w: int
    l: int                # noqa: E741 — matches dictionary id "L" + Bref column convention
    sv: int
    outs: int
    ip_display: float
    h: int
    r: int
    er: int
    hr: int
    bb: int
    so: int
    bf: int
    era: float | None
    whip: float | None
    k_per_9: float | None
    bb_per_9: float | None


# ─────────────────────────────────────────────────────────────────────────────
# Fielding — per (year, league, level, team, position) flat rows
#
# Why no disclosure: fielding rows aren't naturally summable across
# positions (a player's PO at 2B + PO at SS sum to a number but it
# doesn't mean "putouts as an infielder" in any useful sense), so the
# TOT-row pattern that works for batting/pitching doesn't fit. The
# frontend renders these as a flat table sorted by year-then-position-
# then-team, with `position_name` resolved server-side.
# ─────────────────────────────────────────────────────────────────────────────


class PlayerFieldingRow(BaseModel):
    """One fielding row at (year, league, level, team, position) grain.

    `inn_outs` is the total defensive outs (`ip*3 + ipf`); `inn_display`
    is the Bref-style "147.1" form (147⅓). Use `inn_outs` for any
    arithmetic; display form is lossy.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    team: TeamRef | None
    position: int               # raw OOTP code 1-9 (no DH at fielding grain)
    position_name: str          # resolved display: "P", "C", "1B", ...
    g: int
    gs: int
    inn_outs: int               # total defensive outs (ip*3 + ipf)
    inn_display: float          # Bref-style display (147.1 = 147⅓ INN)
    po: int
    a: int
    e: int
    dp: int
    fpct: float | None          # (PO+A)/(PO+A+E); None when total chances are 0


class PlayerAdvancedBattingRow(BaseModel):
    """Per-(year, league_id, level_id) advanced batting stats.

    One row per league-year-level a player accumulated PA in. Multi-team
    stints within the same level collapse to one row (the dominant
    team's park factor applies). Cross-level rollups are intentionally
    omitted — league constants differ by level so cross-level wRC+
    isn't a well-defined number.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    level_id: int
    level_name: str
    league_id: int
    league_abbr: str | None
    pa: int
    woba: float | None
    wraa: float | None
    wrc: float | None
    wrc_plus: int | None
    ops_plus: int | None
    o_war: float | None
    b_war: float | None           # OOTP combined bWAR (off + def + pos)
    park_avg: float | None        # the dominant-team park factor used


class PlayerAdvancedPitchingRow(BaseModel):
    """Per-(year, league_id, level_id) advanced pitching stats.

    Only pitchers with ≥ 30 outs (≥ 10 IP) at the level appear — matches
    the audit's quality threshold. Park factor is the dominant team's
    (most outs at this level).
    """

    model_config = ConfigDict(frozen=True)

    year: int
    age: int | None
    level_id: int
    level_name: str
    league_id: int
    league_abbr: str | None
    outs: int
    ip_display: float
    fip: float | None
    era_plus: int | None
    pit_war: float | None
    p_war: float | None           # OOTP FIP-WAR (canonical pWAR)
    p_ra9_war: float | None       # OOTP RA9-based WAR
    park_avg: float | None


class PlayerRosterStatus(BaseModel):
    """Service-time / arbitration / options / roster-status block.

    Sourced from the latest ``roster_status_current`` row. The
    canonical "when does this guy hit FA?" answer + the GM-side
    flags (active / DL / DFA / waivers) used to read player
    availability at a glance.

    Semantics:
    - **MLB service time** — OOTP credits 172 days per season-year.
      ``mlb_service_days`` is total accumulated days; whole years =
      ``mlb_service_years`` (= ``floor(days / 172)``); leftover days =
      ``mlb_service_days - 172 * mlb_service_years``. The header
      conventionally displays "Xy Yd" where Y is leftover days
      (Bref / MLBPA convention).
    - **Service class** is computed in the route: ``pre_arb`` (<3y),
      ``arb_y1`` / ``arb_y2`` / ``arb_y3`` (3-6y, by full year), or
      ``fa_eligible`` (≥6y). 6.000 = free-agent eligible at end of
      season unless extended.
    - **Days-to-FA** = max(0, 6 × 172 - mlb_service_days). The
      remaining service days the player needs before reaching free
      agency. Zero when already FA-eligible.
    - **Options** — minor-league options. OOTP's convention matches
      MLB's: a player has 3 option years; ``options_used`` counts how
      many have been burned career-to-date (0-3+). Once exhausted, a
      player can no longer be sent to AAA/MiLB without DFA.
    - **Status flags** — ``is_active`` is on the active 26-man;
      ``is_on_secondary`` is the 40-man / reserve placeholder;
      ``is_on_dl`` / ``_dl60`` mark IL placements (10-day / 60-day);
      ``designated_for_assignment`` / ``is_on_waivers`` are the
      transactional out-of-roster states. Most flags are zero in the
      November end-of-season snapshot — they light up in mid-season
      ingests.

    Fields not surfaced (semantics unclear without further audit):
    ``years_protected_from_rule_5``, ``has_received_arbitration``.
    Add when needed.
    """

    model_config = ConfigDict(frozen=True)

    # Raw service counters (for power-user inspection)
    mlb_service_years: int                     # whole years (floor)
    mlb_service_days: int                      # total days accumulated
    mlb_service_days_this_year: int            # days credited this calendar year

    # Display-formatted service time: "4y 128d" (Bref/MLBPA convention)
    service_display: str

    # Computed eligibility
    service_class: str                         # "pre_arb" | "arb_y1/y2/y3" | "fa_eligible"
    service_class_label: str                   # display: "Pre-arb" / "Arb (Y2)" / "FA-eligible"
    days_to_free_agency: int                   # remaining; 0 when FA-eligible
    is_free_agent_eligible: bool

    # Options
    options_used: int
    options_used_this_year: int
    options_remaining: int                     # max(0, 3 - options_used); -1 if over (rare edge)

    # Status flags
    is_active: bool                            # on the active 26-man
    is_on_secondary: bool                      # 40-man / reserve roster
    is_on_dl: bool                             # 10-day IL
    is_on_dl60: bool                           # 60-day IL
    designated_for_assignment: bool
    is_on_waivers: bool


class PlayerPositionFielding(BaseModel):
    """One row in the per-position fielding cube — current rating +
    ceiling + experience for a single defensive spot.

    Materialized from ``players_fielding_current`` (the latest
    ``players_fielding_snapshot`` row). Per-position columns are the
    OOTP-scouted 20-80 ratings — ``fielding_rating_pos1..9`` for current
    skill, ``fielding_rating_pos1..9_pot`` for ceiling. Position
    indexing follows the standard OOTP convention (1=P, 2=C, 3=1B,
    4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF — no DH at the fielding grain).

    ``experience`` comes from ``fielding_experience1..9`` (the
    1-indexed columns; index 0 is unused / DH-bucket and isn't
    surfaced). Units are OOTP "play attempts" — useful as a relative
    weight ("this guy has 200 plays at 1B vs 4 at 2B") rather than a
    sample-size threshold.

    Conventions:
    - All three fields are nullable. A zero rating means "the player
      has never been rated at this position in scouting"; we surface
      it as ``None`` rather than ``0`` so the UI can render an
      em-dash without ambiguity.
    - Zero experience also surfaces as ``None`` for the same reason
      — distinguishes "never tried" from "tried briefly with 0 plays
      somehow logged."

    Why surface this at all: the `fielding_rating_pos*` cube answers
    the GM-side question "where should this player actually play?"
    That info is fully populated in every dump but never reads in any
    L2/L3/UI surface today (highest-value find from the 2026-05-09
    dump-CSV audit — see PROJECT_STATUS / DATA_NOTES).
    """

    model_config = ConfigDict(frozen=True)

    position: int                 # 1-9 (P/C/1B/2B/3B/SS/LF/CF/RF)
    position_name: str            # display: "P", "C", "1B", ...
    rating_current: int | None    # 20-80 scouted rating; null when 0
    rating_potential: int | None  # 20-80 ceiling; null when 0
    experience: int | None        # plays at this position; null when 0


class PlayerCareerFielding(BaseModel):
    """Career rollup per position.

    One row per position the player ever played; sums G/GS/INN/PO/A/E/
    DP across years. Career-summary FPCT is the position-rollup ratio.
    Career-across-positions totals aren't included — see PlayerFieldingRow
    for why combining across positions is semantically fraught.
    """

    model_config = ConfigDict(frozen=True)

    position: int
    position_name: str
    g: int
    gs: int
    inn_outs: int
    inn_display: float
    po: int
    a: int
    e: int
    dp: int
    fpct: float | None


# ─────────────────────────────────────────────────────────────────────────────
# Top-level envelope
# ─────────────────────────────────────────────────────────────────────────────


class PlayerSituationalRow(BaseModel):
    """Per-(year, level, split) situational stats from `f_pa_event`.

    Same row shape for both batter and pitcher views — the difference
    is the dimension used to filter the PA log:

    - **Batter view** (``situational_batting``): keyed on ``batter_id``.
      Slash line is what the player hit. Higher OPS in clutch = good.
    - **Pitcher view** (``situational_pitching``): keyed on ``pitcher_id``.
      Slash line is what the player ALLOWED. Lower OPS in clutch = good
      (the UI inverts the color hint accordingly).

    Splits cover the canonical clutch / leverage / platoon / count /
    spray cuts (14 in total, organized into five clusters):

    Leverage:

    - ``all``          — every regular-season PA (parity row vs the
      regular batting/pitching season totals).
    - ``risp``         — runner on 2nd OR 3rd at start of PA (`risp_flag`).
    - ``risp_2out``    — RISP AND outs ≥ 2 (the highest-leverage RBI chance).
    - ``late_close``   — 7th inning or later AND OOTP `Close` flag (Bref-style
      "Late & Close": tying / go-ahead run on / at-bat / on-deck).

    Bases:

    - ``bases_empty``  — base1=base2=base3=0 (low-leverage baseline).
    - ``bases_loaded`` — base1>0 AND base2>0 AND base3>0 (max RBI chance).

    Platoon:

    - ``vs_left`` / ``vs_right`` — opposing hand (LHP/RHP for batter
      view, LHB/RHB for pitcher view). Switch-hitters resolve to the
      opposite of the pitcher's throwing hand for the pitcher view.

    Counts (count BEFORE the resolving pitch):

    - ``first_pitch`` — 0-0 result (PA resolved on pitch 1).
    - ``two_strike``  — strikes=2 when resolved.
    - ``full_count``  — 3-2 when resolved.

    Spray (BIP only — K/BB/HBP excluded; AVG within these splits is
    hits-per-BIP since AB ≈ COUNT(*) within the BIP filter; OBP
    collapses to AVG since BB/HBP are zero):

    - ``pull`` / ``center`` / ``oppo`` — based on `hit_xy` packed
      coord (`x = hit_xy / 16`). Empirically batter-relative — same
      `x ≤ 5 → pull`, `6..9 → center`, `x ≥ 10 → oppo` rule for
      both hands.

    Sanity invariants (verified live): bases_empty + (bases-with-runners)
    = all; vs_left + vs_right = all when handedness is fully populated;
    pull + center + oppo = total BIP for that (year, level).

    Slash line is computed server-side so the frontend doesn't have to
    re-derive it. ``split_label`` is the display string ("RISP, 2 out" /
    "Late & Close"); ``split`` is the stable id for sort + frontend cases.

    OOTP's looser ``close_flag`` (~80% of all PAs at MLB) is intentionally
    NOT surfaced as a split — it's too permissive to mean "clutch" in the
    Bref sense; ``late_close_flag`` (the strict 7th+ tying-run window) is
    the right analog and what we use here. See DATA_NOTES.

    **Multi-year coverage**: ``f_pa_event`` is sourced from L0 with
    cross-dump dedup (the L0 layer retains every previously-ingested
    dump's rows by ``dump_date``, so historical seasons survive the OOTP
    rollover that overwrites ``at_bats_event.csv``). Splits cover every
    year the warehouse has ingested (2026-2029 in this save).
    """

    model_config = ConfigDict(frozen=True)

    year: int
    level_id: int
    level_name: str | None
    split: str           # "all" | "risp" | "risp_2out" | "late_close"
    split_label: str     # "All" | "RISP" | "RISP, 2 out" | "Late & Close"
    pa: int
    ab: int
    h: int
    doubles: int         # 2B (avoid `2b` Python identifier issue)
    triples: int         # 3B
    hr: int
    bb: int
    k: int
    hbp: int
    sf: int              # sacrifice flies — used in OBP denom
    avg: float | None
    obp: float | None
    slg: float | None
    ops: float | None


class PlayerResponse(BaseModel):
    """``GET /api/players/{player_id}`` response.

    Fields are nullable when the player never accumulated stats of that
    type — e.g. a position player has `pitching_seasons=[]` and
    `pitching_career=None`. The frontend uses these nulls to decide
    which subsections of the page to render.
    """

    model_config = ConfigDict(frozen=True)

    bio: PlayerBio
    batting_seasons: list[PlayerBattingSeason]
    pitching_seasons: list[PlayerPitchingSeason]
    fielding_rows: list[PlayerFieldingRow]
    advanced_batting: list[PlayerAdvancedBattingRow]
    advanced_pitching: list[PlayerAdvancedPitchingRow]
    batting_career: PlayerCareerBatting | None
    pitching_career: PlayerCareerPitching | None
    fielding_career: list[PlayerCareerFielding]   # one row per position
    # Per-position scouted-rating cube from the latest snapshot. Always
    # length 9 (one entry per position 1-9), even when the player has
    # zero rating across the board (each entry's fields will be null
    # in that case). Order is fixed at position 1..9 server-side; the
    # frontend can re-sort by experience for the "where they actually
    # play" view.
    position_fielding: list[PlayerPositionFielding]
    # Service-time + roster status from latest roster_status_current.
    # None when the player has no roster row in the current snapshot
    # (retired, never on a roster, etc.).
    roster_status: PlayerRosterStatus | None
    # Per-(year, level, split) situational batting from f_pa_event. Empty
    # for pitchers (zero batter PAs) and pre-warehouse imported players
    # (no at-bat log). Sorted year DESC, level (MLB first), split
    # (all → risp → risp_2out → late_close).
    situational_batting: list[PlayerSituationalRow]
    # Same row shape but keyed on pitcher_id — the PA log filtered to
    # PAs where this player was on the mound. Slash columns reflect
    # what the pitcher ALLOWED. Empty for position players who never
    # took the mound.
    situational_pitching: list[PlayerSituationalRow]
