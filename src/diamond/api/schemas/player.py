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
    batting_career: PlayerCareerBatting | None
    pitching_career: PlayerCareerPitching | None
    fielding_career: list[PlayerCareerFielding]   # one row per position
