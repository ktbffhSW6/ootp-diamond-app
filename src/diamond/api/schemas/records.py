"""Records leaderboards Pydantic schemas — backs the ``/history/records`` page.

The page answers "who tops this leaderboard, all-time?" across the
union of save data, real-life Lahman/BREF history, and Statcast
batted-ball quality. The wire shape mirrors the CLI's ``diamond
records`` surface — same scope/discipline/category vocabulary, same
``source`` enum, same ``direction`` for asc-vs-desc rate-stat ranking.

Picker hierarchy (3 axes + 1 orthogonal filter):

- **Scope** (season vs career) — flat 2-option toggle.
- **Discipline** (batting vs pitching) — flat 2-option toggle.
- **Category** — dynamic per (scope, discipline). Counting stats
  (HR/RBI/R/H/BB/SB/2B/3B/PA/WAR/W/S/K/IP/SHO/CG/QS) and a Statcast
  subset (MAX_EV/AVG_EV/HARD_HIT_PCT/BARREL_PCT/SWEET_SPOT_PCT/
  MAX_DIST). Built from the categories actually present in
  ``f_record_player`` so we never offer an empty leaderboard.
- **Era** (orthogonal filter, server applies):
  - ``all``      — merge all available sources, re-rank globally.
  - ``save``     — save-only (the user's universe).
  - ``real``     — lahman ∪ bref ∪ merged (real-life MLB history).
  - ``statcast`` — statcast-only (real EV/barrel records 2015-2025).

Source enum — these are the stored ``source`` values in
``f_record_player``:
- ``save``     — derived from the user's OOTP save data.
- ``lahman``   — Lahman 1871-2019 (rosters, awards, counting stats).
- ``bref``     — BREF 2020-2025 (fills the post-Lahman gap).
- ``merged``   — career-scope cross-source dedup via Chadwick
                 Register (Pujols Lahman 656 + BREF 30 = 686).
- ``statcast`` — pybaseball Statcast 2015-2025 (MAX_EV/AVG_EV/
                 HARD_HIT_PCT/BARREL_PCT/SWEET_SPOT_PCT/MAX_DIST).

Player linking: ``player_id`` is OOTP-internal; populated for ``save``
rows + cases where the cross-source matcher resolved a real-life
player to an OOTP-imported entry. When set, the UI links to
``/player/<id>``. ``external_id`` is the foreign-key into the source's
own ID system (bbref_id for lahman/bref, mlb_id for statcast) — kept
for traceability but not directly clickable in v1.

Direction: most categories rank descending (``rank_in_source=1`` =
highest value). Pitching rate-stats-allowed (AVG_EV/BARREL_PCT/
HARD_HIT_PCT/SWEET_SPOT_PCT) rank ascending (lowest = best). The
``direction`` field surfaces this so the UI can label the table
"Fewest" vs "Most" appropriately.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


# Source / scope / discipline / era enums — all string-typed at the wire
# boundary. We use Literal for documentation; the route validates and
# the frontend ts-gen picks them up as union types automatically.
RecordSource = Literal["save", "lahman", "bref", "merged", "statcast"]
RecordScope = Literal["season", "career"]
RecordDiscipline = Literal["batting", "pitching"]
RecordEra = Literal["all", "save", "real", "statcast"]
RecordDirection = Literal["asc", "desc"]


class RecordRow(BaseModel):
    """One leaderboard line.

    ``rank`` is the in-render rank — when ``era='all'`` the route
    re-ranks across the merged source list, so this can differ from
    ``rank_in_source`` (the original within-source rank, kept for
    traceability + tooltip).

    ``player_id`` populated → the UI renders the name as a link to
    ``/player/<id>``. When null (most lahman/bref/statcast rows for
    real players who aren't in the save), the name renders as plain
    text. ``external_id`` is the source's own ID (bbref_id for
    lahman/bref, mlb_id for statcast) — surfaced for completeness
    but not clickable.

    ``year`` is null for career-scope rows; ``team_abbr`` is the
    team at peak (career) or season team (season). Nullable in
    edge cases (early-1880s pre-team-tracking rows in Lahman).
    """

    model_config = ConfigDict(frozen=True)

    rank: int
    rank_in_source: int
    source: RecordSource
    player_id: int | None
    external_id: str | None
    display_name: str
    year: int | None
    team_abbr: str | None
    value: float


class RecordCategoryRef(BaseModel):
    """Lightweight category handle for the picker.

    ``available_sources`` lists which sources have data for this
    (scope, discipline, category). Used by the frontend to hide the
    Era filter when only one source exists (Career WAR is save-only,
    for example) or to grey out an Era option that won't return rows.
    ``label`` is the human-readable name ("Home Runs" / "Wins Above
    Replacement"); ``unit_label`` is the suffix to append after the
    value ("mph", "%", "ft", or empty for counters + WAR).
    """

    model_config = ConfigDict(frozen=True)

    category: str  # the codebook key, e.g. "HR" / "WAR" / "MAX_EV"
    label: str
    unit_label: str
    direction: RecordDirection
    available_sources: list[RecordSource]


class RecordsResponse(BaseModel):
    """Whole payload for one rendered leaderboard.

    The picker payload (``available_categories`` + the active
    scope/discipline/category/era) lets the frontend render every
    control without round-trips. Switching axes is a Link change —
    no client-side state.

    ``rows`` is already sorted (by ``rank`` ascending), already
    rank-stamped, already era-filtered. The frontend renders straight
    from this list with no additional sort/filter logic — keeps the
    server as the single source of ordering truth.

    ``total_in_source`` is the count *before* the limit was applied,
    so the page can show "showing top 25 of 150" hints when more
    rows exist (full top-50 / top-150 still surfaceable via the CLI
    or a future "show all" toggle).
    """

    model_config = ConfigDict(frozen=True)

    scope: RecordScope
    discipline: RecordDiscipline
    category: str
    era: RecordEra
    direction: RecordDirection
    available_categories: list[RecordCategoryRef]
    rows: list[RecordRow]
    total_in_source: int
