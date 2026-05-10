"""Save-switcher endpoints (D3 v2 / setup wizard).

Endpoints:
- ``GET /api/saves`` — discover all saves under the OOTP saves root,
  flagging which one is currently active + whether each is configured.
- ``POST /api/saves/active`` — switch the active save. Persists the
  choice to ``~/.diamond/active_save.toml`` and updates the in-memory
  warehouse singleton so subsequent requests hit the new save's DB.
  Refuses to activate a save that hasn't been configured yet (the
  wizard runs first).
- ``GET /api/saves/{name}/config`` — current per-save scope + the
  30-team picker catalog + a smart-default suggestion based on
  peeking at the target save's warehouse (when one exists).
- ``POST /api/saves/{name}/config`` — write the user's audit_team_id
  + optional reference_scope_enabled + league_ids. Persists to
  ``~/.diamond/save_configs.toml``. If the save being configured is
  the active save, the in-memory warehouse singleton is also updated
  so org-scoped pages reflect the new choice immediately.

Constraints:
- Switching a save with no warehouse is allowed — Diamond's UI shows
  a "Needs ingest" hint, but the user might be configuring the save
  *before* running ``diamond ingest --save`` in their terminal.
- Switching a save with no config is BLOCKED (409) — org-scoped pages
  would render Sox data on a Padres save and confuse the user. Walk
  them through the wizard first.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from diamond.api.schemas import (
    ActiveSaveUpdate,
    MlbTeamOption,
    SaveConfigResponse,
    SaveConfigUpdate,
    SavesListResponse,
    SaveSummaryDto,
)
from diamond.api.warehouse import (
    build_save_config,
    get_active_save,
    set_active_save,
)
from diamond.config import OOTP_SAVED_GAMES
from diamond.mlb_teams import MLB_TEAMS, MLB_TEAMS_BY_ID
from diamond.saves import (
    PersistedSaveConfig,
    list_saves,
    load_save_config,
    save_active_save_name,
    save_save_config,
)

router = APIRouter()


def _to_team_option(team_id: int) -> MlbTeamOption | None:
    """Resolve an OOTP team_id to the picker option, or None if out of range."""
    t = MLB_TEAMS_BY_ID.get(team_id)
    if t is None:
        return None
    return MlbTeamOption(
        team_id=t.team_id,
        abbr=t.abbr,
        name=t.name,
        city=t.city,
        division=t.division,
    )


def _all_team_options() -> list[MlbTeamOption]:
    return [
        MlbTeamOption(
            team_id=t.team_id,
            abbr=t.abbr,
            name=t.name,
            city=t.city,
            division=t.division,
        )
        for t in MLB_TEAMS
    ]


@router.get("/saves", response_model=SavesListResponse)
def list_saves_endpoint() -> SavesListResponse:
    """Enumerate saves under the OOTP saves root."""
    active = get_active_save()
    saves = list_saves()
    return SavesListResponse(
        saves_root=str(OOTP_SAVED_GAMES),
        active_save_name=active.save_name,
        saves=[
            SaveSummaryDto(
                name=s.name,
                path=s.path,
                has_warehouse=s.has_warehouse,
                last_modified=s.last_modified,
                is_active=(s.name == active.save_name),
                is_configured=load_save_config(s.name).is_configured,
            )
            for s in saves
        ],
    )


@router.post("/saves/active", response_model=SavesListResponse)
def set_active_save_endpoint(body: ActiveSaveUpdate) -> SavesListResponse:
    """Switch the active save.

    Validates the save exists + is configured before persisting.
    Returns 409 with a wizard-pointing detail when the user tries to
    activate a save that hasn't been through the configure form yet —
    the org-scoped pages would render previous-save data on the new
    save and that's worse than blocking.
    """
    available = {s.name for s in list_saves()}
    if body.save_name not in available:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Save '{body.save_name}' not found under {OOTP_SAVED_GAMES}. "
                f"Available: {sorted(available)}"
            ),
        )

    persisted = load_save_config(body.save_name)
    if not persisted.is_configured:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Save '{body.save_name}' has no audit_team_id configured. "
                f"POST to /api/saves/{body.save_name}/config first to pick "
                f"your team — the org-scoped pages (cockpit, roster, "
                f"movements, pressure) won't render meaningful data without "
                f"it."
            ),
        )

    save_active_save_name(body.save_name)
    new_active = build_save_config(body.save_name)
    set_active_save(new_active)

    # Pattern A: best-effort re-point Metabase at the new save's warehouse.
    # Always succeeds the save-switch; Metabase coordination is opt-in
    # and silent on failure (Metabase down, no creds, etc.). See
    # `src/diamond/api/metabase.py` for the contract.
    from diamond.api.metabase import repoint_active_save
    mb_status = repoint_active_save(new_active)
    if mb_status.get("synced"):
        import logging
        logging.getLogger(__name__).info(
            "Save switched to %r; Metabase synced", body.save_name
        )

    return list_saves_endpoint()


# ─────────────────────────────────────────────────────────────────────────────
# Per-save config (D3 v2 — the wizard endpoints)
# ─────────────────────────────────────────────────────────────────────────────


# Smart-default suggestion: explored a few heuristics (most-recent-
# movement team, max-contract-count team, _diamond_settings stash) and
# none reliably surface "the user's org" without false positives —
# trades + waiver claims pollute movement counts, every MLB team has
# ~25 active contracts, and _diamond_settings doesn't carry team_id
# yet. v1 ships with no auto-suggestion: the dropdown is just 30 teams
# alphabetical-by-abbr and the user picks. When the active save is
# already configured we DO preselect that team in the dropdown (via
# the audit_team_id in the response), which covers the common
# "switching back to a save I already set up" case.
def _suggest_team(save_name: str) -> int | None:
    """Reserved for a future smarter heuristic; returns None today."""
    return None


@router.get("/saves/{save_name}/config", response_model=SaveConfigResponse)
def get_save_config_endpoint(save_name: str) -> SaveConfigResponse:
    """Read one save's persisted config + the picker catalog.

    Returns the 30-team static option catalog every time so the UI can
    render the dropdown without a separate fetch. `suggested_team` is
    derived from peeking at the save's warehouse if one exists; null
    otherwise. The user is free to ignore the suggestion.
    """
    available = {s.name for s in list_saves()}
    if save_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Save '{save_name}' not found under {OOTP_SAVED_GAMES}.",
        )

    persisted = load_save_config(save_name)

    suggested_id: int | None = None
    if persisted.audit_team_id is None:
        # Only suggest when not already set — once configured, the
        # user's pick is the source of truth.
        suggested_id = _suggest_team(save_name)

    return SaveConfigResponse(
        save_name=save_name,
        is_configured=persisted.is_configured,
        audit_team_id=persisted.audit_team_id,
        audit_team=(
            _to_team_option(persisted.audit_team_id)
            if persisted.audit_team_id is not None
            else None
        ),
        reference_scope_enabled=persisted.reference_scope_enabled,
        league_ids=list(persisted.league_ids),
        mlb_team_options=_all_team_options(),
        suggested_team=(
            _to_team_option(suggested_id) if suggested_id is not None else None
        ),
    )


@router.post("/saves/{save_name}/config", response_model=SaveConfigResponse)
def set_save_config_endpoint(
    save_name: str, body: SaveConfigUpdate
) -> SaveConfigResponse:
    """Write the user's per-save scope.

    Validates `audit_team_id` is in the standard MLB range (1-30).
    Existing fields not in `body` keep their previous values. If the
    save being configured is the currently-active one, the in-memory
    warehouse singleton is also refreshed so org-scoped pages
    immediately reflect the new audit_team_id.
    """
    available = {s.name for s in list_saves()}
    if save_name not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Save '{save_name}' not found under {OOTP_SAVED_GAMES}.",
        )

    if body.audit_team_id not in MLB_TEAMS_BY_ID:
        raise HTTPException(
            status_code=400,
            detail=(
                f"audit_team_id={body.audit_team_id} is outside the standard "
                f"MLB range (1-30). Hand-edit "
                f"~/.diamond/save_configs.toml if you need a non-MLB team."
            ),
        )

    existing = load_save_config(save_name)
    new_config = PersistedSaveConfig(
        audit_team_id=body.audit_team_id,
        reference_scope_enabled=(
            body.reference_scope_enabled
            if body.reference_scope_enabled is not None
            else existing.reference_scope_enabled
        ),
        league_ids=(
            tuple(body.league_ids)
            if body.league_ids is not None
            else existing.league_ids
        ),
    )
    save_save_config(save_name, new_config)

    # If we just reconfigured the active save, refresh the in-memory
    # SaveConfig so the next request sees the new audit_team_id.
    active = get_active_save()
    if active.save_name == save_name:
        set_active_save(build_save_config(save_name))

    return get_save_config_endpoint(save_name)
