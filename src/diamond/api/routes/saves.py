"""Save-switcher endpoints (D3 v2 / setup wizard).

Endpoints:
- ``GET /api/saves`` — discover all saves under the OOTP saves root,
  flagging which one is currently active. Includes `has_warehouse`
  per save so the picker knows whether the save needs ingesting first.
- ``POST /api/saves/active`` — switch the active save. Persists the
  choice to ``~/.diamond/active_save.toml`` and updates the in-memory
  warehouse singleton so subsequent requests hit the new save's DB.

Constraints:
- Switching a save with no warehouse is allowed in v1 (the user can
  decide); subsequent reads will fail until they `diamond ingest`.
  Future: gate this with a "this save needs ingesting first — run X
  in your terminal" 409 response.
- League-scope (the SaveConfig.league_ids tuple) is copied from the
  current default — switching across team org-trees is v2.1.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException

from diamond.api.schemas import (
    ActiveSaveUpdate,
    SavesListResponse,
    SaveSummaryDto,
)
from diamond.api.warehouse import get_active_save, set_active_save
from diamond.config import OOTP_SAVED_GAMES
from diamond.saves import (
    list_saves,
    save_active_save_name,
)

router = APIRouter()


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
            )
            for s in saves
        ],
    )


@router.post("/saves/active", response_model=SavesListResponse)
def set_active_save_endpoint(body: ActiveSaveUpdate) -> SavesListResponse:
    """Switch the active save.

    Validates the requested save_name exists under the OOTP saves
    root, persists the choice, and swaps the API's in-memory
    warehouse singleton. Future requests transparently use the new
    save's DB.
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

    save_active_save_name(body.save_name)

    # Swap the in-memory active save. League-scope + audit_team_id are
    # copied from the current SaveConfig — explicit per-save scope
    # editing is a v2.1 follow-on.
    current = get_active_save()
    new_save = replace(current, save_name=body.save_name)
    set_active_save(new_save)

    return list_saves_endpoint()
