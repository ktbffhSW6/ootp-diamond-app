"""Static MLB team_id ↔ abbr ↔ display-name catalog.

OOTP assigns team_ids 1-30 to the 30 MLB clubs in alphabetical order
by city + abbreviation, and these IDs are stable across saves (the
engine seeds them deterministically from the bundled MLB roster).
This module hardcodes the mapping so the setup-wizard team picker
can offer a 30-team dropdown without needing to peek at the target
save's warehouse.

If a future OOTP version reorders these (or a save is started with
"include international leagues only" or some non-standard scope),
the picker will be wrong for that save and the user will have to
hand-edit ``~/.diamond/save_configs.toml``. That's the v2.1
trade-off; the auto-detect fallback in `routes/saves.py` peeks at
the save's `teams` table when available, which catches edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MlbTeam:
    team_id: int
    abbr: str
    name: str
    city: str
    division: str  # e.g. "AL East"


MLB_TEAMS: tuple[MlbTeam, ...] = (
    MlbTeam(1,  "AZ",  "Diamondbacks", "Arizona",     "NL West"),
    MlbTeam(2,  "ATL", "Braves",       "Atlanta",     "NL East"),
    MlbTeam(3,  "BAL", "Orioles",      "Baltimore",   "AL East"),
    MlbTeam(4,  "BOS", "Red Sox",      "Boston",      "AL East"),
    MlbTeam(5,  "CWS", "White Sox",    "Chicago",     "AL Central"),
    MlbTeam(6,  "CHC", "Cubs",         "Chicago",     "NL Central"),
    MlbTeam(7,  "CIN", "Reds",         "Cincinnati",  "NL Central"),
    MlbTeam(8,  "CLE", "Guardians",    "Cleveland",   "AL Central"),
    MlbTeam(9,  "COL", "Rockies",      "Colorado",    "NL West"),
    MlbTeam(10, "DET", "Tigers",       "Detroit",     "AL Central"),
    MlbTeam(11, "MIA", "Marlins",      "Miami",       "NL East"),
    MlbTeam(12, "HOU", "Astros",       "Houston",     "AL West"),
    MlbTeam(13, "KC",  "Royals",       "Kansas City", "AL Central"),
    MlbTeam(14, "LAA", "Angels",       "Los Angeles", "AL West"),
    MlbTeam(15, "LAD", "Dodgers",      "Los Angeles", "NL West"),
    MlbTeam(16, "MIL", "Brewers",      "Milwaukee",   "NL Central"),
    MlbTeam(17, "MIN", "Twins",        "Minnesota",   "AL Central"),
    MlbTeam(18, "NYY", "Yankees",      "New York",    "AL East"),
    MlbTeam(19, "NYM", "Mets",         "New York",    "NL East"),
    MlbTeam(20, "ATH", "Athletics",    "Athletics",   "AL West"),
    MlbTeam(21, "PHI", "Phillies",     "Philadelphia","NL East"),
    MlbTeam(22, "PIT", "Pirates",      "Pittsburgh",  "NL Central"),
    MlbTeam(23, "SD",  "Padres",       "San Diego",   "NL West"),
    MlbTeam(24, "SEA", "Mariners",     "Seattle",     "AL West"),
    MlbTeam(25, "SF",  "Giants",       "San Francisco","NL West"),
    MlbTeam(26, "STL", "Cardinals",    "St. Louis",   "NL Central"),
    MlbTeam(27, "TB",  "Rays",         "Tampa Bay",   "AL East"),
    MlbTeam(28, "TEX", "Rangers",      "Texas",       "AL West"),
    MlbTeam(29, "TOR", "Blue Jays",    "Toronto",     "AL East"),
    MlbTeam(30, "WSH", "Nationals",    "Washington",  "NL East"),
)


MLB_TEAMS_BY_ID: dict[int, MlbTeam] = {t.team_id: t for t in MLB_TEAMS}
MLB_TEAMS_BY_ABBR: dict[str, MlbTeam] = {t.abbr: t for t in MLB_TEAMS}
