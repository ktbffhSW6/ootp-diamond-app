"""Draft classes Pydantic schemas — backs ``/history/draft``.

Per-year draft retrospectives. Backed by the L3 fact ``f_draft_class``
(one row per drafted player, 4 years × ~575 picks = ~2,300 rows in
this save). Each row carries the draft tuple (year/round/pick/team)
plus the player's current location (team/level) and an ``outcome``
bucket for the "where are they now?" framing.

Outcome buckets (from ``f_draft_class.outcome``):

- ``mlb_regular`` — made the majors, accumulated meaningful WAR.
- ``mlb_callup`` — made the majors briefly (cup of coffee).
- ``in_draft_org`` — still developing in the org that drafted them.
- ``traded_away`` — moved to another org.
- ``released`` — released without making MLB.
- ``retired`` — retired without making MLB (or post-MLB retirement).

A 2026 first-rounder (drafted years ago) typically resolves to one
of mlb_regular / mlb_callup / in_draft_org. A 2029 first-rounder
(just drafted) is almost always still in_draft_org — the page's
year picker defaults to the OLDEST class with material outcome
variation, since fresh classes are mostly identical "still
developing" rows.

Picker hierarchy:
- **Year** — every year with at least one drafted player. Defaults
  to the oldest year with any non-``in_draft_org`` outcomes (the
  richest retrospective). Newest years sit further down the strip.

The response groups rows by outcome bucket; within each bucket rows
are ordered by ``draft_overall_pick`` ASC (top-of-class first). The
outcome bucket order itself is fixed: mlb_regular → mlb_callup →
in_draft_org → traded_away → released → retired (most-impact first).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


DraftOutcome = Literal[
    "mlb_regular",
    "mlb_callup",
    "in_draft_org",
    "traded_away",
    "released",
    "retired",
]


class DraftPick(BaseModel):
    """One drafted player + their current outcome.

    ``draft_overall_pick`` is the global pick number (1.1 = 1, 1.2 = 2,
    ..., 2.1 = 31, etc. — depends on round size). ``draft_round`` is
    the round number, kept for display ("Rd 4, Pick 124").

    ``career_mlb_war`` is the canonical "how did this pick turn out?"
    number — sums batting + pitching WAR across the player's MLB
    career. Always populated (zeros for players who never made MLB).

    ``mlb_g`` / ``mlb_pa`` / ``mlb_outs`` are batting/pitching career
    counters; the UI picks one to display based on the player's
    primary discipline.

    ``current_team_name`` is the team they're on now (could be the
    drafting org for ``in_draft_org`` outcomes, a different MLB org
    for ``traded_away``, or null for retired/released). ``current_level_id``
    1=MLB, 2=AAA, 3=AA, 4=A+/A, 6=Rk/DSL — same convention as
    elsewhere.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    position: int  # POSITION_NAMES enum (1=P, 2=C, 3=1B...)
    bats: int | None  # 1=R 2=L 3=S
    throws: int | None  # 1=R 2=L
    draft_age: int | None
    draft_round: int | None
    draft_overall_pick: int | None
    draft_team_name: str | None
    current_team_name: str | None
    current_level_id: int | None
    outcome: DraftOutcome
    ever_made_mlb: bool
    first_mlb_date: date | None
    mlb_g: int  # batting games
    mlb_pa: int
    mlb_hr: int
    mlb_war_bat: float
    mlb_g_pit: int  # pitching games
    mlb_outs: int
    mlb_w: int
    mlb_s: int  # saves
    mlb_war_pit: float
    career_mlb_war: float


class DraftBucket(BaseModel):
    """One outcome bucket, with its picks ordered by overall pick ASC.

    Per-bucket count surfaced separately so the UI can render
    section headers with size hints ("MLB Regulars · 7") without
    counting client-side.
    """

    model_config = ConfigDict(frozen=True)

    outcome: DraftOutcome
    label: str
    count: int
    rows: list[DraftPick]


class DraftClassSummary(BaseModel):
    """Year-level summary for the page header.

    ``total_picks`` is the count of all rows in the class (≈573-599
    per year in this save). ``ever_made_mlb`` is the cumulative
    promote-to-MLB count across the class — the headline "x% of this
    class has made the show" stat.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    total_picks: int
    ever_made_mlb: int
    mlb_regular: int
    mlb_callup: int
    in_draft_org: int
    traded_away: int
    released: int
    retired: int


class DraftClassResponse(BaseModel):
    """Whole payload for one rendered draft year.

    ``available_years`` lists every year with picks (used by the
    year picker). ``summary`` is the headline counts for the rendered
    year. ``buckets`` is the actual roster, grouped + ordered.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    available_years: list[int]
    summary: DraftClassSummary
    buckets: list[DraftBucket]
