"""Pydantic schemas for save discovery + switching + per-save config (D3 v2)."""

from __future__ import annotations

from pydantic import BaseModel


class SaveSummaryDto(BaseModel):
    """One save under the OOTP saves root.

    `name` is the canonical save_name (directory name including the
    ``.lg`` suffix). `has_warehouse` is true iff the save's
    ``diamond/diamond.duckdb`` exists — drives the picker's
    "ingest first" hint. `last_modified` is epoch seconds, may be null
    on permission errors. `is_configured` is true iff the save has a
    persisted ``audit_team_id`` (i.e., the user has run the configure
    wizard at least once).
    """

    name: str
    path: str
    has_warehouse: bool
    last_modified: float | None
    is_active: bool
    is_configured: bool


class SavesListResponse(BaseModel):
    """All saves under the configured OOTP saves root.

    `saves_root` is included so the UI can surface "looking in {root}"
    text without requiring a separate endpoint. `active_save_name` is
    redundant with the `is_active` flag on each row but cheaper for
    the UI to read directly.
    """

    saves_root: str
    active_save_name: str
    saves: list[SaveSummaryDto]


class ActiveSaveUpdate(BaseModel):
    """POST body for /api/saves/active.

    `save_name` must be the directory name including the ``.lg``
    suffix and must match an entry returned by GET /api/saves.
    """

    save_name: str


# ─────────────────────────────────────────────────────────────────────────────
# Per-save config (D3 v2 — the wizard payload)
# ─────────────────────────────────────────────────────────────────────────────


class MlbTeamOption(BaseModel):
    """One option in the team-picker dropdown.

    Mirrors ``mlb_teams.MlbTeam`` — surfaces enough to render
    `BOS · Red Sox · Boston · AL East` lines without per-row lookups.
    """

    team_id: int
    abbr: str
    name: str
    city: str
    division: str


class SaveConfigResponse(BaseModel):
    """One save's persisted scope + identity, plus pickable options.

    `audit_team_id` is None when the save has never been configured —
    the UI surfaces this as "needs configure." `audit_team` resolves
    the id to a friendly tuple when set; null otherwise.
    `mlb_teams_options` is the static 30-team catalog for the picker.
    `suggested_team` is a smart-default suggestion derived from
    peeking at the save's warehouse (e.g., the team_id with the
    most recent ingest activity); null when no warehouse / no signal.
    """

    save_name: str
    is_configured: bool
    audit_team_id: int | None
    audit_team: MlbTeamOption | None
    reference_scope_enabled: bool
    league_ids: list[int]
    mlb_team_options: list[MlbTeamOption]
    suggested_team: MlbTeamOption | None


class SaveConfigUpdate(BaseModel):
    """POST body for /api/saves/{name}/config.

    `audit_team_id` is required (the wizard's primary purpose).
    `reference_scope_enabled` and `league_ids` default to whatever's
    already persisted; pass them only when overriding.
    """

    audit_team_id: int
    reference_scope_enabled: bool | None = None
    league_ids: list[int] | None = None
