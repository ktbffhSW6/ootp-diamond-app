"""Pydantic schemas for the admin endpoints.

Backs three admin surfaces:
- ``POST /api/admin/shutdown``   — no payload, no schema
- ``GET  /api/admin/dump-status`` — counts + pending dump list (this file)
- ``POST /api/admin/ingest``      — ingest result summary (this file)
"""

from __future__ import annotations

from pydantic import BaseModel


class DumpStatusResponse(BaseModel):
    """Read-only snapshot of ingest gap: what's on disk vs what's been
    processed into the warehouse.

    `pending_dumps` is a (truncated) list of dump folder names that
    OOTP has written but Diamond hasn't ingested yet. The frontend
    surfaces a badge when ``pending_count > 0`` and a "Refresh" button
    that triggers ``POST /api/admin/ingest``.
    """

    save_name: str
    has_warehouse: bool
    on_disk_count: int
    ingested_count: int
    pending_count: int
    pending_dumps: list[str]
    latest_ingested_dump: str | None
    latest_ingested_at: str | None  # ISO timestamp


class IngestRunResponse(BaseModel):
    """Result of a ``POST /api/admin/ingest`` invocation.

    `ingested` and `skipped` are dump-folder-name lists. `elapsed_seconds`
    is wall-clock for the whole orchestration (L0 + L1 + L2 + L3
    rebuild). The frontend shows a toast/banner with these counts +
    triggers a router refresh so server-rendered pages re-fetch.
    """

    save_name: str
    ingested: list[str]
    skipped: list[str]
    elapsed_seconds: float
