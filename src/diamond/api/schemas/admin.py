"""Pydantic schemas for the admin endpoints.

Backs the typed admin surfaces:
- ``GET  /api/admin/dump-status``     — counts + pending dump list (this file)
- ``POST /api/admin/ingest``          — ingest result summary (this file)
- ``GET  /api/admin/metabase-status`` — untyped dict response (D31)
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


# ─────────────────────────────────────────────────────────────────────────────
# D40 invariants watchdog
# ─────────────────────────────────────────────────────────────────────────────


class InvariantMetricSummary(BaseModel):
    """Per-metric tally for the invariants summary endpoint."""

    metric: str
    green: int
    amber: int
    red: int
    total: int


class InvariantOverall(BaseModel):
    """Roll-up across all metrics."""

    green: int
    amber: int
    red: int
    total: int
    pass_rate: float                 # 0..100 pct of green
    status: str                      # 'green' | 'amber' | 'red'  (worst metric wins)


class InvariantFailure(BaseModel):
    """A single drift event for the admin / debug surface.

    `delta = dump_value - derived_value`; `status` is `red` (clear bug,
    |delta| > 2·tolerance) or `amber` (drift starting, tolerance < |delta|
    ≤ 2·tolerance).
    """

    dump_date: str | None            # ISO date
    scope_type: str
    scope_id: int | None
    year: int | None
    level_id: int | None
    metric: str
    dump_value: float | None
    derived_value: float | None
    delta: float | None
    tolerance: float
    status: str
    note: str | None


class InvariantsResponse(BaseModel):
    """``GET /api/admin/invariants`` response.

    Reflects the latest watchdog run (computed at end of every
    `rebuild_l1_l2`). Frontend cockpit pill consumes ``overall.status``
    + ``overall.pass_rate``; the admin debug page consumes the
    per-metric `metrics[]` + top-N `failures[]`.

    Returns ``last_run_dump_date = None`` if the watchdog has never
    run (e.g. warehouse predates D40 wiring).
    """

    last_run_dump_date: str | None
    overall: InvariantOverall | None
    metrics: list[InvariantMetricSummary]
    failures: list[InvariantFailure]
