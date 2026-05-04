"""FastAPI app factory and root configuration.

Per Decision D16: this is the backend half of the Diamond UI. Talks
directly to the per-save DuckDB warehouse via the existing Python
modules; serves typed JSON to the Next.js frontend at ``web/``.

Conventions:
- Every route module lives in ``diamond/api/routes/`` and exports a
  ``router`` of type ``fastapi.APIRouter``. ``app.py`` includes them
  with a ``/api`` prefix.
- Every response shape is a Pydantic model in
  ``diamond/api/schemas/``. Schemas are the single source of truth
  for the API contract; ``make types`` regenerates the TS interfaces
  in ``web/lib/types/api.ts`` from them.
- Read-only by default. The API never writes to the warehouse —
  ingest stays a CLI operation (per D2's per-save-DB model and the
  setup-wizard plan in UI_DESIGN.md).
- CORS allows ``localhost:3000`` (Next.js dev) only. Production
  deployment is out of scope per D16's "local-first" commitment.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from diamond.api.routes import glossary, health, players


# CORS allowlist — Next.js dev server runs on :3000 by default.
# When the frontend dev server moves (rare) or production hosting
# happens (Phase 4+), extend this list.
DEV_FRONTEND_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def create_app() -> FastAPI:
    """Build the FastAPI app. Factory shape supports test fixtures
    that need a fresh app per test.
    """
    app = FastAPI(
        title="Diamond API",
        description=(
            "OOTP 27 monthly-dump warehouse + analytics, served as a "
            "typed HTTP API. See `docs/DECISIONS.md` D16 for the stack "
            "decision and `docs/UI_DESIGN.md` for the consuming frontend."
        ),
        version="0.1.0",
        # Disable the default redoc; FastAPI's swagger at /docs is
        # plenty for local dev and we don't ship hosted docs in v1.
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_FRONTEND_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(glossary.router, prefix="/api", tags=["glossary"])
    app.include_router(players.router, prefix="/api", tags=["players"])

    return app


app: FastAPI = create_app()
