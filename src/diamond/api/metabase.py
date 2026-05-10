"""Metabase coordination — Pattern A (single Database, save-aware).

Diamond and Metabase run as cooperating local processes. Metabase has
exactly **one** Database connection (id=1) configured against the
*active save's* DuckDB warehouse. When the user switches saves in
Diamond, this module repoints Metabase's connection to the new save's
file and triggers a schema re-sync. Same Metabase metadata DB (cards,
dashboards, field IDs); just the underlying data flips.

Why Pattern A vs Pattern B (multiple Databases registered):
- Solo workflow with one save active at a time → Pattern A (this).
- Side-by-side comparison of two saves → opt-in Pattern B (manually
  register a second Database in Metabase admin UI).

Schema stability is the load-bearing assumption: every Diamond save
has the same warehouse schema (L0 → L_REF identical), so Metabase's
field IDs (which key on `(database_id, table_id, name)`) stay valid
across save swaps. Re-sync just refreshes row counts + fingerprints.

This module is **best-effort**. If Metabase isn't running, save
switches still succeed; we just log a warning and move on. The
contract is "save switching always works in Diamond; Metabase is
synced if available."

Authentication:
    Reuses a long-lived session token cached at
    ``~/.diamond/metabase_session.txt``. Token TTL is 14 days by
    default; we refresh on 401. Credentials live in
    ``~/.diamond/metabase_credentials.toml`` (user-editable).

Failure modes (all silent — saves succeed regardless):
    - Metabase down (connection refused) → log + skip
    - Auth failure (bad creds, deleted user) → log + skip
    - Metabase responds with 4xx/5xx → log + skip
    - Network slow → 5s timeout → skip
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from diamond.config import OOTP_SAVED_GAMES, SaveConfig

log = logging.getLogger(__name__)


METABASE_URL = "http://127.0.0.1:3001"
METABASE_DATABASE_ID = 1  # Pattern A — single Database connection
METABASE_TIMEOUT = 5.0    # seconds; save switch shouldn't hang on Metabase

DIAMOND_CONFIG_DIR = Path.home() / ".diamond"
SESSION_CACHE = DIAMOND_CONFIG_DIR / "metabase_session.txt"
CREDS_FILE = DIAMOND_CONFIG_DIR / "metabase_credentials.toml"


def _load_credentials() -> tuple[str, str] | None:
    """Read (email, password) from the credentials file.

    Returns None if the file doesn't exist — Metabase integration is
    opt-in. Without credentials, all coordination calls no-op silently.

    Format (TOML):
        email = "diamond@local.test"
        password = "your-password-here"
    """
    if not CREDS_FILE.is_file():
        return None
    try:
        import tomllib
        data = tomllib.loads(CREDS_FILE.read_text(encoding="utf-8"))
        email = data.get("email")
        password = data.get("password")
        if email and password:
            return (email, password)
    except (OSError, ValueError) as exc:
        log.warning("Metabase credentials file unreadable: %s", exc)
    return None


def _read_cached_session() -> str | None:
    """Return the cached session token if present, else None."""
    if SESSION_CACHE.is_file():
        try:
            token = SESSION_CACHE.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            pass
    return None


def _cache_session(token: str) -> None:
    """Write the session token to disk for reuse across requests."""
    DIAMOND_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SESSION_CACHE.write_text(token, encoding="utf-8")
    except OSError as exc:
        log.warning("Could not cache Metabase session: %s", exc)


def _login() -> str | None:
    """Authenticate against Metabase with cached credentials.

    Returns the session token on success, None on any failure path.
    Does NOT raise — this module is best-effort.
    """
    creds = _load_credentials()
    if creds is None:
        return None
    email, password = creds
    try:
        resp = httpx.post(
            f"{METABASE_URL}/api/session",
            json={"username": email, "password": password},
            timeout=METABASE_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning(
                "Metabase auth failed: %s %s", resp.status_code, resp.text[:200]
            )
            return None
        token = resp.json().get("id")
        if token:
            _cache_session(token)
            return token
    except httpx.HTTPError as exc:
        log.warning("Metabase auth network error: %s", exc)
    return None


def _get_session() -> str | None:
    """Return a valid session token (cached or freshly minted), or None."""
    cached = _read_cached_session()
    if cached:
        # Cheap probe — does it still work?
        try:
            resp = httpx.get(
                f"{METABASE_URL}/api/user/current",
                headers={"X-Metabase-Session": cached},
                timeout=METABASE_TIMEOUT,
            )
            if resp.status_code == 200:
                return cached
        except httpx.HTTPError:
            return None
    return _login()


def _is_metabase_reachable() -> bool:
    """Quick liveness check; suppresses connection errors."""
    try:
        resp = httpx.get(
            f"{METABASE_URL}/api/health", timeout=2.0
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def warehouse_path(save: SaveConfig) -> Path:
    """Return the absolute path to a save's DuckDB warehouse."""
    return OOTP_SAVED_GAMES / save.save_name / "diamond" / "diamond.duckdb"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def repoint_active_save(save: SaveConfig) -> dict[str, Any]:
    """Update Metabase's Database #1 to point at this save's warehouse.

    Returns a status dict describing what happened, for logging /
    surfacing back to the UI:
        {
            "metabase_running": bool,
            "configured": bool,
            "repointed": bool,
            "synced": bool,
            "message": str,
        }

    Safe to call from a request handler — completes in < 5s even on
    failure paths. Never raises.
    """
    status = {
        "metabase_running": False,
        "configured": False,
        "repointed": False,
        "synced": False,
        "message": "",
    }

    if not _is_metabase_reachable():
        status["message"] = "Metabase not running — skipped"
        return status
    status["metabase_running"] = True

    session = _get_session()
    if session is None:
        status["message"] = (
            "Metabase running but credentials missing or invalid; create "
            f"{CREDS_FILE} with email + password to enable save-aware sync"
        )
        return status
    status["configured"] = True

    new_path = str(warehouse_path(save))
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    # ── 1. Repoint the connection ────────────────────────────────────────
    try:
        resp = httpx.put(
            f"{METABASE_URL}/api/database/{METABASE_DATABASE_ID}",
            json={
                "details": {
                    "database_file": new_path,
                    "read_only": True,
                    "old_implicit_casting": True,
                    "allow_unsigned_extensions": False,
                },
                "engine": "duckdb",
            },
            headers=headers,
            timeout=METABASE_TIMEOUT,
        )
        if resp.status_code != 200:
            status["message"] = (
                f"Metabase repoint failed: {resp.status_code} "
                f"{resp.text[:200]}"
            )
            return status
        status["repointed"] = True
    except httpx.HTTPError as exc:
        status["message"] = f"Metabase repoint error: {exc}"
        return status

    # ── 2. Trigger schema re-sync ────────────────────────────────────────
    # Async on Metabase's side — we fire-and-forget. Re-sync is fast
    # because the schema is stable across saves; only fingerprints
    # need refreshing.
    try:
        httpx.post(
            f"{METABASE_URL}/api/database/{METABASE_DATABASE_ID}/sync_schema",
            headers=headers,
            timeout=METABASE_TIMEOUT,
        )
        status["synced"] = True
        status["message"] = (
            f"Metabase repointed at '{save.save_name}' + sync triggered"
        )
    except httpx.HTTPError as exc:
        status["message"] = f"Metabase sync trigger error: {exc}"

    return status
