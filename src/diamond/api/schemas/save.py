"""Save-metadata Pydantic schema — backs the landing page header.

Returned by ``GET /api/save``. Identifies which save the active
warehouse points at, surfaces ingest health (latest dump, dump count),
and exposes the audit-team identity so the landing page can show
"Boston Red Sox · 2029 season" in its header rather than a generic
"Diamond" placeholder.

Per D3, this becomes the integration point when the v2 save-picker
ships — the front end will call this endpoint after each picker
selection to refresh the landing context.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class SaveResponse(BaseModel):
    """Active-save identity + ingest health + scope counts."""

    model_config = ConfigDict(frozen=True)

    # ── Save identity ──
    save_name: str
    """Folder name of the save under the OOTP saved_games root,
    e.g. ``Building the Green Monster.lg``. Source of truth for
    persisted data per D2."""

    # ── Org identity (derived from SaveConfig.audit_team_id) ──
    org_team_id: int
    org_team_abbr: str | None
    org_team_nickname: str | None

    # ── Warehouse / ingest status ──
    dump_count: int
    """Total number of dumps successfully ingested into this save's
    warehouse. From `_diamond_ingests` (status='success')."""

    latest_dump_date: date | None
    """Date of the latest dump (e.g. 2029-11-01 for the EOS Nov dump).
    None when the warehouse has no successful ingests yet."""

    latest_dump_name: str | None
    """Folder name of the latest dump, e.g. ``dump_2029_11``."""

    latest_season: int | None
    """Year of the latest dump — the season the user is currently
    living in. Drives default-season picks on tools like
    ``/movements``."""

    earliest_season: int | None
    """Earliest year with any player-season data (often pre-save real
    history at year 1871). Useful for context but not for default
    season picks."""

    # ── Scope counts ──
    scoped_player_count: int
    """Players in scope per D13 (org tier UNION reference tier when
    enabled). Surfaced as a quick health-check number on the landing
    page."""

    scoped_team_count: int
    """Teams in scope (org affiliates plus any reference teams)."""
