"""DuckDB connection management for the API layer.

The API is read-only (per ``app.py``'s contract). We open one DuckDB
connection per process at first use and hand out cursors per request —
DuckDB connections are not thread-safe, but cursors derived from a
single connection are, so this gives us a cheap pool.

Why not open per request:
- DuckDB connection-open cost is small but non-zero (~10ms cold).
- For small local-first usage that adds up across page loads.
- The `cursor()` pattern is standard DuckDB and survives
  uvicorn's `--workers > 1` because each worker has its own
  process and so its own module-level singleton.

Why not a connection pool:
- Diamond is single-user. A single connection-with-cursors is
  enough for the foreseeable load (page loads from one browser).

Per Decision D2: each save has its own DuckDB at
``<save_root>/diamond/diamond.duckdb``. The API targets the active save
selected by `BUILDING_THE_GREEN_MONSTER` for now; the v2 save-setup
picker (D3) will swap this out for a session-driven choice.
"""

from __future__ import annotations

import threading

import duckdb

from diamond.config import BUILDING_THE_GREEN_MONSTER, SaveConfig
from diamond.schema.build import open_warehouse_db


# Module-level singletons, lazily initialized on first request.
_lock = threading.Lock()
_active_save: SaveConfig = BUILDING_THE_GREEN_MONSTER
_root_con: duckdb.DuckDBPyConnection | None = None


def set_active_save(save: SaveConfig) -> None:
    """Switch the API to a different save's warehouse.

    Closes any open root connection so the next request opens against
    the new save. Test fixtures call this; production usage will too
    once the v2 save picker (D3) lands.
    """
    global _active_save, _root_con
    with _lock:
        if _root_con is not None:
            _root_con.close()
            _root_con = None
        _active_save = save


def get_active_save() -> SaveConfig:
    """Return the currently active SaveConfig.

    Routes that need save-level metadata (e.g. ``audit_team_id`` for
    the user's org) read it via this helper rather than importing the
    module-private ``_active_save`` directly. Once D3's save-picker
    ships, this is the single integration point that needs to change."""
    return _active_save


def _ensure_root() -> duckdb.DuckDBPyConnection:
    """Open the per-process root connection if needed and return it."""
    global _root_con
    if _root_con is None:
        with _lock:
            if _root_con is None:
                _root_con = open_warehouse_db(_active_save)
    return _root_con


def get_cursor() -> duckdb.DuckDBPyConnection:
    """FastAPI dependency: return a per-request cursor.

    Each request gets its own cursor (a `duckdb.DuckDBPyConnection`
    object that shares the underlying DB with the root connection).
    Cursors are thread-safe relative to each other; the root is not.

    Usage in a route::

        @router.get("/players/{player_id}")
        def get_player(
            player_id: int,
            con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
        ) -> PlayerResponse:
            ...
    """
    return _ensure_root().cursor()
