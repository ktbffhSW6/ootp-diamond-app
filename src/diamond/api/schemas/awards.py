"""Awards leaderboards Pydantic schemas — backs ``/history/awards``.

The page answers "who's won this award the most times, all-time?"
across every scoped league. Backed by the L3 fact
``f_award_career_player`` (per-(player × league × award) career
rollup) which UNIONs save data with cross-source dedup'd Lahman +
MLB Stats API real-life awards (collapsed via Chadwick Register
into ``source='merged'``).

The wire shape mirrors the records page layout — three axes plus
one orthogonal era filter — but with a flatter category list since
awards are categorical (MVP / Cy Young / Gold Glove / ...) rather
than scope+discipline+stat-key.

Picker hierarchy (2 axes + 1 orthogonal filter):

- **League** — every scoped league with at least one award row.
  Defaults to MLB (203). Ordered by ``league_level`` so MLB sits at
  the top of the picker, AAA next, etc.
- **Award** — every award_id with at least one row in the chosen
  league. Defaults to MVP (5). Ordered by prestige (MVP / Cy /
  RoY / Gold Glove / Silver Slugger / Reliever / All-Star / WS
  Champion / Series MVP) then weekly/monthly minor awards.
- **Era** (orthogonal): ``all`` (default) | ``save`` (your save
  universe only) | ``real`` (cross-source merged real-life awards
  for retired players who aren't in the save).

Source enum — ``f_award_career_player.source`` is one of:

- ``save``   — derived from OOTP save data (player_id populated;
                links to ``/player/<id>``).
- ``merged`` — Lahman + MLB Stats API + BREF dedup'd to bbref_id
                via Chadwick Register, only for bbref_ids NOT in
                the save (Yadier Molina 9 GG, R.A. Dickey 1 Cy,
                etc.). external_id (bbref_id) populated; not
                clickable since the save's player pages don't
                extend to non-save players.

Why no rate stat / direction here: every award has the same
ranking semantic — n_won DESC with tiebreaker last_year DESC
(recency wins ties). No "Fewest Cy Youngs" framing; just trophy
count.

Per D17 awards lives under ``/history``. ``GET /api/awards`` is the
single endpoint; switching axes is a navigation, not a state
mutation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


# Source / era enums — string-typed at the wire. Awards has only
# 2 sources (save + merged) compared to records' 5; the era filter
# maps real → merged (UI thinks in "real-life" terms).
AwardSource = Literal["save", "merged"]
AwardEra = Literal["all", "save", "real"]


class AwardLeagueRef(BaseModel):
    """Lightweight league handle for the picker. ``league_level``
    mirrors OOTP's level numeric (1 = MLB, 2 = AAA, 3 = AA, etc.)
    so the frontend can group / order leagues by tier.
    """

    model_config = ConfigDict(frozen=True)

    league_id: int
    abbr: str | None
    name: str | None
    league_level: int


class AwardCategoryRef(BaseModel):
    """One award type with its display label + which sources have data
    for it in the current league. Used by the frontend to render the
    award picker and grey out era filters that would yield zero rows.
    """

    model_config = ConfigDict(frozen=True)

    award_id: int  # AwardId enum value
    label: str
    available_sources: list[AwardSource]


class AwardHolderRow(BaseModel):
    """One trophy-case row.

    ``rank`` is the in-render rank (1-based). Ties broken by
    ``last_year DESC`` (recency over depth) — matches the existing
    ``diamond awards`` CLI behavior. ``n_won`` is the career trophy
    count for this (player, league, award) combination.

    ``player_id`` populated → name renders as a link to
    ``/player/<id>``. Otherwise plain text (real-life player not
    in the save). ``external_id`` is the bbref_id when ``source =
    'merged'`` — kept for traceability + tooltip.

    ``first_team_abbr`` / ``last_team_abbr`` may be null for merged
    rows (Lahman team mapping isn't bijective with OOTP teams) and
    for save rows where the underlying snapshot didn't carry team
    metadata at the time of the win (rare).
    """

    model_config = ConfigDict(frozen=True)

    rank: int
    source: AwardSource
    player_id: int | None
    external_id: str | None
    display_name: str
    n_won: int
    first_year: int | None
    last_year: int | None
    first_team_abbr: str | None
    last_team_abbr: str | None


class AwardsResponse(BaseModel):
    """Whole payload for one rendered awards leaderboard.

    The picker payload (``available_leagues`` + ``available_awards``
    + the active league/award/era) lets the frontend render every
    control without round-trips.

    ``rows`` is sorted by rank ASC (n_won DESC, last_year DESC tie-
    break), already era-filtered, already capped at the route's
    limit. ``total_in_source`` is the count *before* the limit was
    applied so the UI can show "showing top 25 of 173" hints.
    """

    model_config = ConfigDict(frozen=True)

    league: AwardLeagueRef
    award_id: int
    era: AwardEra
    available_leagues: list[AwardLeagueRef]
    available_awards: list[AwardCategoryRef]
    rows: list[AwardHolderRow]
    total_in_source: int
