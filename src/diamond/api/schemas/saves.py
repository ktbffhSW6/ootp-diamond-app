"""Pydantic schemas for save discovery + switching."""

from __future__ import annotations

from pydantic import BaseModel


class SaveSummaryDto(BaseModel):
    """One save under the OOTP saves root.

    `name` is the canonical save_name (directory name including the
    ``.lg`` suffix). `has_warehouse` is true iff the save's
    ``diamond/diamond.duckdb`` exists — drives the picker's
    "ingest first" hint. `last_modified` is epoch seconds, may be null
    on permission errors.
    """

    name: str
    path: str
    has_warehouse: bool
    last_modified: float | None
    is_active: bool


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
