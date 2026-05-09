"""Pydantic schemas — the API contract between FastAPI and Next.js.

Per D16: these models are the single source of truth for response
shapes. ``make types`` regenerates ``web/lib/types/api.ts`` from
them, so a field-name change here propagates automatically to the
frontend on the next type-gen run.

Conventions:
- One module per logical resource (``glossary.py``, future
  ``player.py``, ``records.py``, etc.).
- Schemas use snake_case field names (matches Python convention +
  matches the dictionary's internal ids). The frontend re-maps to
  camelCase only where idiomatic React requires it.
- Pure read-models — no input/POST schemas needed in v1; the API is
  read-only.
- Re-export at the package level so ``from diamond.api.schemas
  import GlossaryEntry`` works regardless of the source file.
"""

from diamond.api.schemas.awards import (
    AwardCategoryRef,
    AwardHolderRow,
    AwardLeagueRef,
    AwardsResponse,
)
from diamond.api.schemas.compare import ComparePlayer, CompareResponse
from diamond.api.schemas.cockpit import (
    CockpitMovementRow,
    CockpitPressureRow,
    CockpitPressureSummary,
    CockpitResponse,
    CockpitSpotlightCard,
    CockpitStandingsBlock,
    CockpitStandingsRow,
)
from diamond.api.schemas.contract import ContractYear, PlayerContract
from diamond.api.schemas.draft import (
    DraftBucket,
    DraftClassResponse,
    DraftClassSummary,
    DraftPick,
)
from diamond.api.schemas.glossary import GlossaryEntry, GlossaryListResponse
from diamond.api.schemas.health import HealthResponse
from diamond.api.schemas.hof import HofPlayer, HofResponse
from diamond.api.schemas.leaderboards import (
    LeaderboardOption,
    LeaderboardOptionsResponse,
    LeaderboardResponse,
    LeaderboardRow,
    LeaderboardStatSpec,
)
from diamond.api.schemas.movements import (
    MovementBattingStats,
    MovementPitchingStats,
    MovementRow,
    MovementsResponse,
    MovementTeamRef,
)
from diamond.api.schemas.player import (
    PlayerAdvancedBattingRow,
    PlayerAdvancedPitchingRow,
    PlayerBattingSeason,
    PlayerBattingStint,
    PlayerBio,
    PlayerCareerBatting,
    PlayerCareerFielding,
    PlayerCareerPitching,
    PlayerFieldingRow,
    PlayerPitchingSeason,
    PlayerPitchingStint,
    PlayerPositionFielding,
    PlayerResponse,
    PlayerRosterStatus,
    PlayerSituationalRow,
    TeamRef,
)
from diamond.api.schemas.pressure import (
    PressureLevelGroup,
    PressurePlayer,
    PressureResponse,
)
from diamond.api.schemas.records import (
    RecordCategoryRef,
    RecordRow,
    RecordsResponse,
)
from diamond.api.schemas.roster import (
    RosterBattingLine,
    RosterLevelGroup,
    RosterPitchingLine,
    RosterPlayer,
    RosterResponse,
    RosterTeamRef,
)
from diamond.api.schemas.save import SaveResponse
from diamond.api.schemas.standings import (
    StandingsDivision,
    StandingsLeagueRef,
    StandingsResponse,
    StandingsSubLeague,
    StandingsTeamRow,
)
from diamond.api.schemas.streaks import (
    StreakCategoryRef,
    StreakRow,
    StreaksResponse,
)

__all__ = [
    "AwardCategoryRef",
    "AwardHolderRow",
    "AwardLeagueRef",
    "AwardsResponse",
    "CockpitMovementRow",
    "CockpitPressureRow",
    "CockpitPressureSummary",
    "CockpitResponse",
    "CockpitSpotlightCard",
    "CockpitStandingsBlock",
    "CockpitStandingsRow",
    "ComparePlayer",
    "CompareResponse",
    "ContractYear",
    "DraftBucket",
    "DraftClassResponse",
    "DraftClassSummary",
    "DraftPick",
    "GlossaryEntry",
    "GlossaryListResponse",
    "HealthResponse",
    "HofPlayer",
    "HofResponse",
    "LeaderboardOption",
    "LeaderboardOptionsResponse",
    "LeaderboardResponse",
    "LeaderboardRow",
    "LeaderboardStatSpec",
    "MovementBattingStats",
    "MovementPitchingStats",
    "MovementRow",
    "MovementTeamRef",
    "MovementsResponse",
    "PlayerAdvancedBattingRow",
    "PlayerAdvancedPitchingRow",
    "PlayerBattingSeason",
    "PlayerBattingStint",
    "PlayerBio",
    "PlayerContract",
    "PlayerCareerBatting",
    "PlayerCareerFielding",
    "PlayerCareerPitching",
    "PlayerFieldingRow",
    "PlayerPitchingSeason",
    "PlayerPitchingStint",
    "PlayerPositionFielding",
    "PlayerResponse",
    "PlayerRosterStatus",
    "PlayerSituationalRow",
    "PressureLevelGroup",
    "PressurePlayer",
    "PressureResponse",
    "RecordCategoryRef",
    "RecordRow",
    "RecordsResponse",
    "RosterBattingLine",
    "RosterLevelGroup",
    "RosterPitchingLine",
    "RosterPlayer",
    "RosterResponse",
    "RosterTeamRef",
    "SaveResponse",
    "StandingsDivision",
    "StandingsLeagueRef",
    "StandingsResponse",
    "StandingsSubLeague",
    "StandingsTeamRow",
    "StreakCategoryRef",
    "StreakRow",
    "StreaksResponse",
    "TeamRef",
]
