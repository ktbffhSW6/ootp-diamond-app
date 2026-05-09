"""Save discovery + active-save persistence (D3 v2 / setup wizard).

Lists OOTP saves under ``OOTP_SAVED_GAMES`` and persists the user's
chosen active save to ``~/.diamond/active_save.toml`` so the next
launch resumes against the same warehouse.

v1 scope:
- Save discovery is a directory scan — every ``*.lg`` folder under
  the OOTP saves root is a candidate. We expose `has_warehouse`
  (whether ``diamond/diamond.duckdb`` exists in the save) so the UI
  can disambiguate "imported but not yet ingested" saves.
- Persistent choice is a single string (the save_name including the
  ``.lg`` suffix). League-scope tuple stays hardcoded in
  ``BUILDING_THE_GREEN_MONSTER`` for now — switching scope across
  different team org-trees is v2.1.
- We do NOT mutate ``OOTP_SAVED_GAMES`` itself in v1 — relocating the
  saves root is a future setting (the D3 wizard mentions it for
  cross-machine portability, but v1 users all have the default path).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from diamond.config import OOTP_SAVED_GAMES


@dataclass(frozen=True)
class SaveSummary:
    """Per-save metadata for the picker UI.

    `name` is the directory name including the ``.lg`` suffix, which
    is also the SaveConfig.save_name field. `has_warehouse` is True
    iff ``<save>/diamond/diamond.duckdb`` exists; the picker uses this
    to render an "ingest first" hint for unprocessed saves.
    """

    name: str
    path: str
    has_warehouse: bool
    last_modified: float | None  # epoch seconds


def list_saves() -> list[SaveSummary]:
    """Enumerate ``*.lg`` directories under ``OOTP_SAVED_GAMES``.

    Returns saves sorted alphabetically. If the saves root doesn't
    exist (user moved or doesn't have OOTP installed there), returns
    an empty list rather than raising.
    """
    if not OOTP_SAVED_GAMES.exists():
        return []
    out: list[SaveSummary] = []
    for entry in sorted(OOTP_SAVED_GAMES.iterdir()):
        if not entry.is_dir() or not entry.name.endswith(".lg"):
            continue
        wh = entry / "diamond" / "diamond.duckdb"
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = None
        out.append(
            SaveSummary(
                name=entry.name,
                path=str(entry),
                has_warehouse=wh.exists(),
                last_modified=mtime,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Active-save persistence
# ─────────────────────────────────────────────────────────────────────────────


def _active_save_path() -> Path:
    base = Path(os.path.expanduser("~")) / ".diamond"
    base.mkdir(parents=True, exist_ok=True)
    return base / "active_save.toml"


def load_active_save_name() -> str | None:
    """Read the persisted active save name, or None if not set / unparseable."""
    path = _active_save_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return None
    name = data.get("active", {}).get("save_name")
    if isinstance(name, str) and name:
        return name
    return None


def save_active_save_name(name: str) -> None:
    """Persist the active save name to ``~/.diamond/active_save.toml``."""
    if not name.endswith(".lg"):
        raise ValueError(f"Save name should end with '.lg' — got {name!r}")
    body = (
        "# Diamond active-save selection. Set via /settings/save in the\n"
        "# UI or by editing this file directly. Reloaded on every API\n"
        "# request that opens the warehouse.\n"
        "[active]\n"
        f'save_name = "{name}"\n'
    )
    _active_save_path().write_text(body, encoding="utf-8")
