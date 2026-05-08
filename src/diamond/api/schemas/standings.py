"""Standings Pydantic schemas — backs the ``/league`` page's standings tab.

The page answers "where does my team sit, right now?" for every scoped
league (MLB tree + AFL). Layout mirrors a Bref standings cut:

- League picker (defaults to MLB — the most-watched scope).
- Year picker (defaults to latest year with data; resolves to that
  year's most recent dump_date — November = end-of-season).
- Sub-leagues side-by-side (AL / NL on MLB).
- Within each sub-league: divisions stacked vertically.
- Within each division: team rows ordered by ``pos``.

Grain notes:
- One row per ``(team_id, dump_date)`` from ``team_record_snapshot``.
- All-Star teams (g=0) are filtered out at the route layer — they
  carry the league's allstar_team_id slots and clutter the standings.
- ``magic_number`` uses two OOTP sentinels: ``-1`` means *clinched*
  (treated as a boolean flag); ``1000`` means *not applicable / out
  of contention* (surfaced as null). All other positive values pass
  through as the live magic number.
- ``streak`` is signed (positive = win streak, negative = loss streak,
  zero = no current streak). Frontend renders as "W9" / "L4" / "—".
- Some leagues have sub-leagues but no divisions (AAA: just IL East/West).
  Some have no sub-leagues at all (AFL is one flat division). The
  layout helpers handle both shapes — sub_league_name / division_name
  are nullable.

Per D17 the standings tab lives under ``/league``; this is the first
real content for that tab (the rest stays a stub for now).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class StandingsTeamRow(BaseModel):
    """One team line in the standings table.

    ``pos`` is the position within division (1 = leader). ``gb`` is
    games behind the division leader (0.0 for the leader). ``streak``
    is signed: positive integer = current win streak length, negative
    = loss streak length, zero = no streak (e.g., season hasn't started
    or last result was a tie).

    ``magic_number`` is null when OOTP's "1000" sentinel applied
    (out of contention / not yet meaningful); ``clinched`` is true
    when OOTP's "-1" sentinel applied (division clinched). The two
    flags are mutually exclusive — at most one is set on any row.
    ``is_user_org`` flags the row for the audit team (Boston) so the
    UI can highlight it without needing to know the team_id.
    """

    model_config = ConfigDict(frozen=True)

    team_id: int
    abbr: str | None
    nickname: str | None
    g: int
    w: int
    l: int
    t: int
    pct: float
    gb: float
    streak: int
    magic_number: int | None
    clinched: bool
    pos: int
    is_user_org: bool


class StandingsDivision(BaseModel):
    """A division — a list of team rows ordered by ``pos`` ascending.

    For leagues with no divisions (AFL) the route still emits a single
    placeholder division with ``division_id=0`` and ``division_name=None``
    so the rendering stays uniform.
    """

    model_config = ConfigDict(frozen=True)

    division_id: int
    division_name: str | None
    teams: list[StandingsTeamRow]


class StandingsSubLeague(BaseModel):
    """A sub-league — one or more divisions stacked vertically in the UI.

    For leagues with no sub-leagues (AAA / AA / A* / DSL etc.) the route
    emits a single placeholder sub-league with ``sub_league_id=0`` and
    ``sub_league_name=None``. The frontend hides the sub-league header
    in that case to avoid an empty band.
    """

    model_config = ConfigDict(frozen=True)

    sub_league_id: int
    sub_league_name: str | None
    divisions: list[StandingsDivision]


class StandingsLeagueRef(BaseModel):
    """Lightweight league handle — used in both the headline and the
    league-picker payload. ``league_level`` mirrors OOTP's level numeric
    (1 = MLB, 2 = AAA, 3 = AA, 4 = A+/A, 6 = Rk/Complex/DSL, 9 = AFL).
    """

    model_config = ConfigDict(frozen=True)

    league_id: int
    abbr: str | None
    name: str | None
    league_level: int


class StandingsResponse(BaseModel):
    """Whole payload for the standings tab.

    ``available_leagues`` and ``available_years`` let the page render
    both pickers without round-trips. ``dump_date`` is the resolved
    snapshot date (MAX dump within the chosen year) — shown in the
    header so the user knows whether they're looking at end-of-season
    or a mid-season cut.
    """

    model_config = ConfigDict(frozen=True)

    league: StandingsLeagueRef
    year: int
    dump_date: date
    available_leagues: list[StandingsLeagueRef]
    available_years: list[int]
    org_team_id: int
    sub_leagues: list[StandingsSubLeague]
