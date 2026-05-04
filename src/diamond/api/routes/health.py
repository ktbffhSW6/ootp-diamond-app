"""Health-check route. Useful for the dev workflow — `curl
localhost:8000/api/health` confirms the FastAPI process is up before
you debug a frontend fetch error.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    api_version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe. Returns 200 + version string when the process
    is alive — does not touch the warehouse."""
    return HealthResponse(status="ok", api_version="0.1.0")
