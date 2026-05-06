"""Roster Pydantic schemas — backs the ``/roster`` page.

The roster page is the missing entry point for player navigation: a
single screen showing every active player in the user's org tree,
grouped by level, with the basics needed to recognize a player + a
toggle into advanced stats. Each player name links to ``/player/[id]``.

Grain notes:

- One row per active player in the user's org. "Active" means
  ``players_current.retired = false`` AND on a team in the org tree
  (parent_team_id chain rooted at ``audit_team_id``).
- A player is **grouped by their current level** (the level of the
  team they're on right now in ``players_current``), and the displayed
  stats are **only their stats at that level for the current season**.
  Bouncing-up-and-down players don't surface their cross-level totals
  here — that's the player page's job. Roster-page logic stays clean:
  "where is Joe now and how is he hitting at that level?"
- Within each level, players split into ``position_players`` and
  ``pitchers`` (driven by ``players.position == 1``). Two-way players
  are filed by primary position for v1.

Per D15 maintenance contract: every numeric field maps to a
``STATS[id]`` in the dictionary. A future tooltip pass will wire
header hovers to the glossary; the field names already match
dictionary ids where the SQL allows.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


RosterRole = Literal["batter", "pitcher"]


class RosterTeamRef(BaseModel):
    """Slim team reference — current team for a roster row.

    Carries league + level identifiers so the frontend can render
    "MLB Boston (AL)" without a second lookup. Mirrors ``TeamRef``
    from the player schema but stays distinct so the roster contract
    is self-contained (per the schemas convention).
    """

    model_config = ConfigDict(frozen=True)

    team_id: int
    abbr: str | None
    nickname: str | None
    league_id: int | None
    league_abbr: str | None
    level_id: int | None
    level_name: str | None


class RosterBattingLine(BaseModel):
    """Latest-season batting line at the player's current level.

    Counting stats come from ``f_player_season_batting`` filtered to
    ``(year=latest, league_id=current, level_id=current, team_id=current,
    split_id=1)``. Rate stats are computed in the route. Advanced fields
    (``woba`` / ``wrc_plus`` / ``ops_plus`` / ``o_war``) come from
    ``f_player_season_advanced_batting`` joined on (year, league, level)
    — the advanced fact table already collapses stints within a level.

    Every numeric is nullable when the denominator is zero or the
    advanced row didn't materialize (sub-threshold sample, pre-2026
    seasons with no league baselines, etc.).
    """

    model_config = ConfigDict(frozen=True)

    # Counting (basic toggle)
    g: int
    pa: int
    ab: int
    h: int
    hr: int
    rbi: int
    sb: int
    bb: int
    so: int
    # Rate (basic toggle)
    avg: float | None
    obp: float | None
    slg: float | None
    ops: float | None
    # Advanced toggle — one shared block per row, frontend swaps columns.
    # ``o_war`` is offensive WAR ONLY (no defensive component); the
    # frontend labels it accordingly. A combined bWAR requires a
    # defensive-runs model that doesn't exist yet (see BACKLOG).
    woba: float | None
    wraa: float | None             # weighted Runs Above Average (raw)
    wrc: float | None              # weighted Runs Created (raw)
    wrc_plus: int | None
    ops_plus: int | None
    o_war: float | None
    park_avg: float | None         # dominant team's park factor (1.00 = neutral)
    # Statcast cohort — populated when the player has ≥30 BIP this
    # year at this level. ``max_ev`` is the 90th-percentile EV per
    # Statcast convention (not the absolute max).
    statcast_bip: int | None
    statcast_max_ev: float | None
    statcast_avg_ev: float | None
    statcast_hard_hit_pct: float | None
    statcast_barrel_pct: float | None
    statcast_sweet_spot_pct: float | None


class RosterPitchingLine(BaseModel):
    """Latest-season pitching line at the player's current level.

    Same pattern as the batting line: counting + rate stats from
    ``f_player_season_pitching``, advanced (FIP / ERA+ / pit_WAR) from
    ``f_player_season_advanced_pitching``. ``ip_display`` follows the
    OOTP convention (517 outs → 172.1 = 172⅓); use ``outs`` for any
    arithmetic.
    """

    model_config = ConfigDict(frozen=True)

    # Counting (basic toggle)
    g: int
    gs: int
    w: int
    l: int                # noqa: E741 — matches dictionary id "L"
    sv: int
    outs: int
    ip_display: float
    # Rate (basic toggle)
    era: float | None
    whip: float | None
    k_per_9: float | None
    bb_per_9: float | None
    # Advanced toggle. ``siera`` is the Fangraphs canonical regression
    # (Tier-2 sabermetric) — verified against IE in the audit harness
    # to within ±0.02 for MLB-only Sox.
    fip: float | None
    siera: float | None
    era_plus: int | None
    pit_war: float | None
    park_avg: float | None         # dominant team's park factor
    # Statcast allowed-contact cohort. ``statcast_*`` here describes
    # what the pitcher allowed, not what they generated as a hitter —
    # an "allowed" interpretation of every percentage.
    statcast_bip: int | None
    statcast_max_ev: float | None
    statcast_avg_ev: float | None
    statcast_hard_hit_pct: float | None
    statcast_barrel_pct: float | None
    statcast_sweet_spot_pct: float | None


class RosterPlayer(BaseModel):
    """One player on the user's org-tree roster.

    Bio fields come from ``players_current``; ``overall_rating`` (20-80
    scale per D6) from ``players_ratings_current`` (filtered to user-org
    scouted view per D12). ``team`` is the current team's identity;
    ``batting`` and ``pitching`` carry the latest-season stats at that
    team's level. Both stat blocks may be null — pitchers usually have
    ``batting=None``, position players ``pitching=None``.
    """

    model_config = ConfigDict(frozen=True)

    player_id: int
    full_name: str               # nick takes precedence over first per bio convention
    primary_position: str        # display: "1B", "RHP", "LHP", "C", etc.
    role: RosterRole             # discriminator: drives which table the row lands in
    age: int | None
    bats: str                    # "R" / "L" / "S" / "?"
    throws: str                  # "R" / "L" / "?"
    overall_rating: int | None   # 20-80 scouted, user-org view
    team: RosterTeamRef | None
    batting: RosterBattingLine | None
    pitching: RosterPitchingLine | None


class RosterLevelGroup(BaseModel):
    """All active org players currently at one level.

    ``level_id`` follows ``LEVEL_NAMES`` (1=MLB, 2=AAA, ...);
    ``level_name`` is pre-resolved for display. Sorted MLB first then
    descending by level. Within the group, ``position_players`` and
    ``pitchers`` are each sorted by position then descending overall
    rating then last name.
    """

    model_config = ConfigDict(frozen=True)

    level_id: int
    level_name: str
    position_players: list[RosterPlayer]
    pitchers: list[RosterPlayer]


class RosterResponse(BaseModel):
    """``GET /api/roster`` response.

    Whole org snapshot in one round-trip; the frontend handles all
    filter / sort / toggle interactions client-side over this payload.
    With ~150-200 players in a typical org, the JSON is small enough
    (~50KB uncompressed) that streaming or pagination would be
    premature.
    """

    model_config = ConfigDict(frozen=True)

    season: int
    org_team_id: int
    org_team_abbr: str | None
    org_team_nickname: str | None
    groups: list[RosterLevelGroup]
