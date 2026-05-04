"""Health endpoint Pydantic schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness-probe envelope. Returned by ``GET /api/health``.

    `status` is a fixed-vocabulary string ("ok" today; future values
    might include "degraded" / "warehouse_missing" once we surface
    warehouse-connectivity probes).
    """

    model_config = ConfigDict(frozen=True)

    status: str
    api_version: str
