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

from diamond.api.schemas.glossary import GlossaryEntry, GlossaryListResponse
from diamond.api.schemas.health import HealthResponse
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
    TeamRef,
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

__all__ = [
    "GlossaryEntry",
    "GlossaryListResponse",
    "HealthResponse",
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
    "PlayerCareerBatting",
    "PlayerCareerFielding",
    "PlayerCareerPitching",
    "PlayerFieldingRow",
    "PlayerPitchingSeason",
    "PlayerPitchingStint",
    "PlayerPositionFielding",
    "PlayerResponse",
    "PlayerRosterStatus",
    "RosterBattingLine",
    "RosterLevelGroup",
    "RosterPitchingLine",
    "RosterPlayer",
    "RosterResponse",
    "RosterTeamRef",
    "SaveResponse",
    "TeamRef",
]
