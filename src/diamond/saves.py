"""Save discovery + active-save persistence + per-save config (D3).

Lists OOTP saves under ``OOTP_SAVED_GAMES``, persists the user's
chosen active save to ``~/.diamond/active_save.toml``, and stores
**per-save scope config** (audit_team_id + league_ids) in
``~/.diamond/save_configs.toml`` so each save's "your team" identity
+ league scope follows it across switches.

Layout:

  ~/.diamond/active_save.toml      — single-string pointer to the
                                     currently-active save's folder
                                     name. Single source of truth
                                     for "which save is Diamond
                                     looking at right now."

  ~/.diamond/save_configs.toml     — per-save scope. Each `[saves."<name>"]`
                                     section holds:
                                       audit_team_id        (int)
                                       reference_scope_enabled (bool)
                                       league_ids           (int[])
                                     Saves not listed here fall back
                                     to ``DEFAULT_LEAGUE_IDS`` +
                                     ``audit_team_id = None`` (which
                                     the API surfaces as "needs
                                     configure" so the wizard prompts
                                     the user).

Convention: save_name always includes the `.lg` suffix (matches
``SaveConfig.save_name`` and the directory name). audit_team_id is
the OOTP team_id for the user's MLB team — for the standard MLB
scope the 30 IDs are stable across saves (1=ARI, 2=ATL, ..., 30=WSH).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from diamond.config import OOTP_SAVED_GAMES


# Standard MLB org-tree league_ids (matches BUILDING_THE_GREEN_MONSTER's
# tuple). New saves get this as the default scope; v2.2 will let the
# user customize per-save (different scoped leagues for non-MLB sims).
DEFAULT_LEAGUE_IDS: tuple[int, ...] = (
    203,                                # MLB
    204, 205,                           # AAA: IL, PCL
    206, 207, 208,                      # AA: EL, SL, TL
    209, 210, 211, 212, 213, 252,       # A+/A: NWL, SAL, MWL, CAL, CAR, FSL
    217, 218,                           # Complex: ACL, FCL
    234,                                # International rookie: DSL
    70,                                 # AFL
)


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


@dataclass(frozen=True)
class PersistedSaveConfig:
    """One save's scope + identity, persisted to save_configs.toml.

    `audit_team_id` is the user's MLB team — the org-scoped pages
    (cockpit, roster, movements, pressure) all read from this. None
    means the save has never been configured; the UI surfaces this
    as "needs configure" so the wizard runs before activation.

    `reference_scope_enabled` is the D13 flag that expands
    `_scoped_players` to include any player with ≥1 MLB appearance.
    Off by default; the user toggles it via the configure form or
    the existing CLI flag.

    `league_ids` defaults to ``DEFAULT_LEAGUE_IDS`` (standard MLB
    org tree); v2.2 will let the user customize.
    """

    audit_team_id: int | None = None
    reference_scope_enabled: bool = False
    league_ids: tuple[int, ...] = DEFAULT_LEAGUE_IDS

    @property
    def is_configured(self) -> bool:
        """True iff the save has at least an audit_team_id set.

        Org-scoped pages can't render meaningfully without one;
        the API gates activation on this.
        """
        return self.audit_team_id is not None


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
# ~/.diamond resolution
# ─────────────────────────────────────────────────────────────────────────────


def _diamond_dir() -> Path:
    base = Path(os.path.expanduser("~")) / ".diamond"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _active_save_path() -> Path:
    return _diamond_dir() / "active_save.toml"


def _save_configs_path() -> Path:
    return _diamond_dir() / "save_configs.toml"


# ─────────────────────────────────────────────────────────────────────────────
# Active-save persistence (single string)
# ─────────────────────────────────────────────────────────────────────────────


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


def get_active_save_display_name() -> str:
    """Return the active save's display name (no `.lg` suffix).

    Reads `~/.diamond/active_save.toml` directly — does NOT depend on
    the API warehouse module so the desktop launcher (which boots
    before any FastAPI machinery) can use it for window titles.
    Falls back to ``"Building the Green Monster"`` (the legacy default
    save) when no active save is persisted yet.
    """
    name = load_active_save_name() or "Building the Green Monster.lg"
    return name.removesuffix(".lg")


def get_active_window_title() -> str:
    """Compute the desktop-window title for the active save.

    Used by ``diamond.desktop.launcher`` (`setWindowTitle`) and by
    ``diamond.desktop.single_instance`` (`FindWindowW`). Both must
    return the same value or the focus-existing-instance flow breaks,
    so they share this helper.
    """
    return f"Diamond — {get_active_save_display_name()}"


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


# ─────────────────────────────────────────────────────────────────────────────
# Per-save config persistence
#
# Single TOML file with one section per save. Defensive against:
# - missing file → returns defaults / None
# - malformed TOML → returns defaults / None (no crash)
# - missing fields per save → fall back per-field
# ─────────────────────────────────────────────────────────────────────────────


def _load_all_configs_raw() -> dict[str, dict]:
    """Read the entire save_configs.toml, returning the [saves] table."""
    path = _save_configs_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return {}
    saves = data.get("saves", {})
    return saves if isinstance(saves, dict) else {}


def load_save_config(save_name: str) -> PersistedSaveConfig:
    """Read one save's config, returning defaults if not configured.

    Always returns a valid ``PersistedSaveConfig`` — the
    ``is_configured`` predicate is the way to ask whether the user
    has actually run through the setup wizard.
    """
    raw_all = _load_all_configs_raw()
    raw = raw_all.get(save_name, {}) if isinstance(raw_all, dict) else {}

    audit_team_id_raw = raw.get("audit_team_id")
    audit_team_id = (
        int(audit_team_id_raw)
        if isinstance(audit_team_id_raw, int) and audit_team_id_raw > 0
        else None
    )
    reference_scope_enabled = bool(raw.get("reference_scope_enabled", False))

    league_ids_raw = raw.get("league_ids")
    if isinstance(league_ids_raw, list) and all(
        isinstance(x, int) for x in league_ids_raw
    ):
        league_ids = tuple(league_ids_raw)
    else:
        league_ids = DEFAULT_LEAGUE_IDS

    return PersistedSaveConfig(
        audit_team_id=audit_team_id,
        reference_scope_enabled=reference_scope_enabled,
        league_ids=league_ids,
    )


def bootstrap_legacy_default_config() -> None:
    """One-time migration for the pre-D3-v2 hardcoded default save.

    Before per-save config existed, all saves shared the
    ``BUILDING_THE_GREEN_MONSTER`` constants (audit_team_id=4 +
    league_ids tuple + reference_scope_enabled). After v2.1 the
    is_configured gate refuses to activate a save that has no
    persisted config — which would lock the Sox user out of their
    own save on first launch with the new code. This function
    persists the legacy values to ``save_configs.toml`` if and only
    if no config exists for that save name yet, so the upgrade is
    seamless for the existing user.

    Idempotent: subsequent calls are no-ops because the second-time
    config exists.
    """
    from diamond.config import BUILDING_THE_GREEN_MONSTER

    legacy_name = BUILDING_THE_GREEN_MONSTER.save_name
    raw_all = _load_all_configs_raw()
    if legacy_name in raw_all:
        return
    save_save_config(
        legacy_name,
        PersistedSaveConfig(
            audit_team_id=BUILDING_THE_GREEN_MONSTER.audit_team_id,
            reference_scope_enabled=BUILDING_THE_GREEN_MONSTER.reference_scope_enabled,
            league_ids=BUILDING_THE_GREEN_MONSTER.league_ids,
        ),
    )


def save_save_config(save_name: str, config: PersistedSaveConfig) -> None:
    """Write one save's config to ``save_configs.toml`` (preserving others).

    Loads the full file, replaces just this save's section, and
    rewrites. Atomic-enough for a single-user local app — the
    sub-millisecond write window doesn't realistically race with
    anything.
    """
    if not save_name.endswith(".lg"):
        raise ValueError(f"Save name should end with '.lg' — got {save_name!r}")

    all_raw = _load_all_configs_raw()
    if not isinstance(all_raw, dict):
        all_raw = {}

    all_raw[save_name] = {
        "audit_team_id": config.audit_team_id,
        "reference_scope_enabled": config.reference_scope_enabled,
        "league_ids": list(config.league_ids),
    }

    # Hand-roll TOML serialization (stdlib doesn't ship a writer; tomli-w
    # would work but this stays dep-free). Quoted keys handle the `.lg`
    # dots in save names; lists of ints render as `[a, b, c]`.
    lines: list[str] = [
        "# Diamond per-save scope config (D3 v2). One section per save under",
        "# ~/.diamond/save_configs.toml. Edit via the /settings/save Configure",
        "# form, or hand-edit here — Diamond reloads on every API request.",
        "",
    ]
    for name in sorted(all_raw):
        cfg = all_raw[name]
        if not isinstance(cfg, dict):
            continue
        lines.append(f'[saves."{name}"]')
        if cfg.get("audit_team_id") is not None:
            lines.append(f"audit_team_id = {int(cfg['audit_team_id'])}")
        else:
            # Comment-out unconfigured saves so the file stays parseable
            # and the absence is visible to a human reader.
            lines.append("# audit_team_id = (not set — run the configure wizard)")
        lines.append(
            f"reference_scope_enabled = "
            f"{'true' if cfg.get('reference_scope_enabled') else 'false'}"
        )
        lg = cfg.get("league_ids", list(DEFAULT_LEAGUE_IDS))
        if isinstance(lg, list) and lg:
            lines.append(f"league_ids = [{', '.join(str(int(i)) for i in lg)}]")
        lines.append("")
    _save_configs_path().write_text("\n".join(lines), encoding="utf-8")
