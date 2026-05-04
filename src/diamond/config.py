"""Per-save paths and scope configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


OOTP_SAVED_GAMES = Path(
    r"C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games"
)


@dataclass(frozen=True)
class SaveConfig:
    """Configuration for one OOTP save."""

    save_name: str
    league_ids: tuple[int, ...]
    audit_team_id: int = 4  # Boston Red Sox
    reference_scope_enabled: bool = False
    """Per Decision D13: when True, `_scoped_players` is expanded to
    include any player with ≥1 career MLB appearance (PA or IP outs at
    level_id=1) regardless of whether they ever played for a scoped team.
    Adds ~5-15K reference-scope players (HoFers, current-era stars on
    other orgs, historical legends OOTP imports). Default False.

    The CLI `--reference-scope` / `--no-reference-scope` flags toggle
    the persisted value in the warehouse `_diamond_settings` table; the
    SaveConfig field here is the in-memory representation that
    `build_l1_machinery` reads."""

    @property
    def save_dir(self) -> Path:
        return OOTP_SAVED_GAMES / self.save_name

    @property
    def dump_dir(self) -> Path:
        return self.save_dir / "dump"

    @property
    def import_export_dir(self) -> Path:
        return self.save_dir / "import_export"

    def csv_dir(self, dump_name: str) -> Path:
        return self.dump_dir / dump_name / "csv"

    def latest_dump_name(self) -> str:
        dumps = sorted(p.name for p in self.dump_dir.iterdir() if p.name.startswith("dump_"))
        if not dumps:
            raise FileNotFoundError(f"No dump folders in {self.dump_dir}")
        return dumps[-1]

    def all_dump_names(self) -> list[str]:
        return sorted(p.name for p in self.dump_dir.iterdir() if p.name.startswith("dump_"))


# MLB org tree + AFL — the v1 hardcoded scope for "Building the Green Monster"
BUILDING_THE_GREEN_MONSTER = SaveConfig(
    save_name="Building the Green Monster.lg",
    league_ids=(
        203,                                          # MLB
        204, 205,                                     # AAA: IL, PCL
        206, 207, 208,                                # AA: EL, SL, TL
        209, 210, 211, 212, 213, 252,                 # A+/A: NWL, SAL, MWL, CAL, CAR, FSL
        217, 218,                                     # Complex: ACL, FCL
        234,                                          # International rookie: DSL
        70,                                           # AFL
    ),
)
