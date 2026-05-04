"""Diamond HTTP API — FastAPI backend per Decision D16.

The API surfaces typed endpoints over the per-save DuckDB warehouse
and the Python analytical modules (records / awards / hof / streaks /
glossary / advanced). The Next.js frontend at ``web/`` consumes this
via auto-generated TypeScript types derived from the Pydantic schemas
in ``src/diamond/api/schemas/``.

Boot:
    uvicorn diamond.api.app:app --reload --port 8000

The ``app`` import below is the conventional uvicorn entry point;
keeping it on the package re-exports it as ``diamond.api:app`` too,
which is the path used by the make targets.
"""

from diamond.api.app import app  # noqa: F401  (re-export)

__all__ = ["app"]
