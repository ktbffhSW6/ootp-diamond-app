"""Hall of Fame Pydantic schemas — backs ``/history/hof``.

Two views in one payload:

- **Inductees** — every player flagged ``hall_of_fame=1`` in
  ``players_current``, ordered by induction year DESC. OOTP imports
  the real Cooperstown roster (Aaron, Mays, Mantle, Pujols 2028,
  Cabrera 2029, etc.) plus any in-save inductees the simulation has
  voted in. ~285 rows in this save.
- **Candidates** — top-N players ranked by career batting WAR who
  *aren't* yet inducted. The "who should be next" view. Powered by
  ``f_record_player`` career-WAR + a ``hall_of_fame=0`` filter; surfaces
  active stars (Trout, Judge), recent retirees the sim hasn't yet
  voted in, and the very rare real-life player OOTP didn't import as
  HoF. Defaults to top-25.

No era picker — OOTP's HoF flag lives only on save data. Real-life
HoFers are already in the inductees list because OOTP imports them.

Per D17 HoF lives under ``/history``. Single endpoint
``GET /api/hof?view=&limit=`` returns whichever view is requested
plus a count of the other so the toggle pill can show the size
("Inductees · 285 / Candidates · 25").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


HofView = Literal["inductees", "candidates"]


class HofPlayer(BaseModel):
    """One Hall row — same shape for inductees + candidates so the
    table component is uniform.

    For inductees, ``inducted_year`` is populated and ``rank`` is
    null (inductees are ordered by year, not WAR rank).

    For candidates, ``inducted_year`` is null and ``rank`` is the
    1-based career-WAR rank within the non-inducted cohort.

    ``career_war`` is OOTP's directly-supplied combined WAR (sum of
    ``f_player_season_advanced_batting.b_war`` across the player's
    seasons — same value the player page Advanced view shows). May
    be null for pure-pitcher inductees from the pre-fWAR era; the UI
    renders a dash in that case.

    ``last_team_abbr`` is the most recent team the player wore;
    blank for ancient retirees whose final team didn't survive
    OOTP's team-history tracking.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    display_name: str
    inducted_year: int | None
    rank: int | None
    career_war: float | None
    last_team_abbr: str | None
    retired: bool


class HofResponse(BaseModel):
    """Whole payload — inductees-or-candidates rows + the counts so
    the toggle pill can show "·N" hints on each side without a second
    round-trip.
    """

    model_config = ConfigDict(frozen=True)

    view: HofView
    rows: list[HofPlayer]
    inductees_count: int
    candidates_count: int  # always = limit (or fewer if not enough non-inducted players)
