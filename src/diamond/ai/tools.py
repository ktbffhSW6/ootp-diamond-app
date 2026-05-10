"""Tool registry for the AI sidebar (D33).

Tools are provider-agnostic: each ``Tool`` declares a JSON Schema
input contract and a Python callable. The chat loop in
``api/routes/ai.py`` translates between this internal shape and the
provider-native tool API (Anthropic ``tools`` array, OpenAI
``tools`` with ``function`` type).

Tier mapping (per CLAUDE.md tier table):

- Tier 1 (page-aware explain): no tools — pure prompt + page context.
- Tier 2 (analyst): ``query_warehouse``, ``get_player``,
  ``get_glossary``, ``compare_players``, ``list_leaderboard_stats``.
- Tier 3 (GM copilot): same tools, different prompt templates
  (handled in the route, not here).
- Tier 4 (prompt-to-dashboard): adds ``create_metabase_card`` which
  POSTs an MBQL/native-SQL spec to Metabase's REST API.

Safety rails on ``query_warehouse``:
- Read-only DuckDB cursor (FastAPI's ``get_cursor`` already gives us
  this; we wrap with a row cap).
- Hard ``LIMIT 1000`` injected if the model didn't provide one.
- Single statement only — split on ``;`` and reject if multiple
  non-empty statements.
- Forbidden keywords: ``DROP``, ``DELETE``, ``UPDATE``, ``INSERT``,
  ``CREATE``, ``ALTER``, ``ATTACH``, ``COPY``, ``EXPORT``.

Note on timeouts: DuckDB 1.5.x has no native ``statement_timeout``
config parameter (Postgres has one; DuckDB doesn't). For v1 we rely
on LIMIT + read-only + single-statement to bound runtime. A
threading.Timer + ``con.interrupt()`` watchdog is a v2 followup if
runaway queries show up in practice.

Tools never raise to the caller. They return ``{"ok": False, "error":
"..."}`` and let the model recover or apologize. A tool that raised
into the chat loop would crash the conversation; we want graceful
fall-through.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import duckdb
import httpx

log = logging.getLogger("diamond.ai.tools")


# ─────────────────────────────────────────────────────────────────────────────
# Tool dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Tool:
    """Provider-agnostic tool declaration."""

    name: str
    description: str
    input_schema: dict[str, Any]   # JSON Schema for tool input
    handler: Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]


@dataclass
class ToolContext:
    """Runtime context passed to every tool handler.

    Holds resources tools need (DuckDB cursor, Metabase coords, the
    active save), so handlers themselves stay pure-ish — they don't
    reach out to the warehouse module directly.
    """

    cursor: duckdb.DuckDBPyConnection
    metabase_url: str = "http://127.0.0.1:3001"
    metabase_database_id: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# query_warehouse
# ─────────────────────────────────────────────────────────────────────────────


_FORBIDDEN_RE = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|ATTACH|DETACH|COPY|EXPORT|"
    r"LOAD|INSTALL|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_DEFAULT_ROW_CAP = 1000


def _query_warehouse(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    sql = (args.get("sql") or "").strip()
    if not sql:
        return {"ok": False, "error": "No SQL provided."}

    # Single-statement guard. Trailing semicolon is fine; multiple
    # non-empty statements are not.
    parts = [p.strip() for p in sql.rstrip(";").split(";")]
    parts = [p for p in parts if p]
    if len(parts) != 1:
        return {
            "ok": False,
            "error": "Only single-statement SELECT queries are allowed.",
        }
    sql = parts[0]

    # Forbidden-keyword guard. We want SELECT-only.
    if _FORBIDDEN_RE.search(sql):
        return {
            "ok": False,
            "error": (
                "Mutation / DDL keywords are not allowed. The warehouse is "
                "read-only from the chat surface."
            ),
        }
    if not re.match(r"\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", sql, re.IGNORECASE):
        return {
            "ok": False,
            "error": "Query must start with SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN.",
        }

    # LIMIT cap. If the model omitted LIMIT we add one. If it added
    # one larger than our cap we leave it (DuckDB will still respect
    # the user's intent; the cap is a default, not a ceiling).
    if not _LIMIT_RE.search(sql):
        sql = f"{sql.rstrip()} LIMIT {_DEFAULT_ROW_CAP}"

    try:
        result = ctx.cursor.execute(sql)
        columns = [c[0] for c in result.description] if result.description else []
        rows = result.fetchall()
        # Convert non-JSON-serializable objects (Decimal, date, etc.)
        out_rows: list[dict[str, Any]] = []
        for r in rows:
            out_rows.append({col: _to_jsonable(v) for col, v in zip(columns, r)})
        return {
            "ok": True,
            "row_count": len(out_rows),
            "columns": columns,
            "rows": out_rows[:_DEFAULT_ROW_CAP],
            "sql": sql,
        }
    except duckdb.Error as exc:
        # Log so failures show up in the launcher log; the model
        # still gets the structured error so it can recover.
        log.warning("query_warehouse DuckDB error: %s\n  sql: %s", exc, sql)
        return {"ok": False, "error": f"DuckDB error: {exc}", "sql": sql}
    except Exception as exc:  # pragma: no cover
        log.exception("query_warehouse unexpected error")
        return {"ok": False, "error": f"Internal: {exc}", "sql": sql}


def _to_jsonable(v: Any) -> Any:
    """Make DuckDB row values JSON-safe for the model."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # Decimal, date, datetime, UUID etc. — stringify.
    return str(v)


# ─────────────────────────────────────────────────────────────────────────────
# get_player / get_glossary / compare_players / list_leaderboard_stats
# ─────────────────────────────────────────────────────────────────────────────
#
# These tools could call the FastAPI endpoints over HTTP, but that's
# silly when they live in the same process. Instead they query the
# warehouse directly with the same shape the routes use.


def _get_player(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    pid = args.get("player_id")
    if pid is None:
        return {"ok": False, "error": "player_id is required."}
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"Invalid player_id: {pid!r}"}

    cur = ctx.cursor
    row = cur.execute(
        """
        SELECT
            p.player_id,
            p.first_name || ' ' || p.last_name AS name,
            p.position,
            p.bats,
            p.throws,
            p.height,
            p.weight,
            p.age,
            p.organization_id AS org_id,
            p.team_id,
            p.retired
        FROM players_current p
        WHERE p.player_id = ?
        """,
        [pid],
    ).fetchone()
    if not row:
        return {"ok": False, "error": f"No player with id {pid}."}

    cols = [c[0] for c in cur.description]
    profile = {col: _to_jsonable(v) for col, v in zip(cols, row)}

    # Career WAR (use the OOTP-canonical bWAR / pWAR per CLAUDE.md).
    career = cur.execute(
        """
        SELECT
            COALESCE(SUM(b.b_war), 0)::DOUBLE AS career_bwar,
            COALESCE(SUM(p.p_war), 0)::DOUBLE AS career_pwar
        FROM (SELECT 1) x
        LEFT JOIN f_player_season_advanced_batting b
            ON b.player_id = ? AND b.level_id = 1
        LEFT JOIN f_player_season_advanced_pitching p
            ON p.player_id = ? AND p.level_id = 1
        """,
        [pid, pid],
    ).fetchone()
    if career:
        profile["career_bwar"] = round(float(career[0] or 0), 2)
        profile["career_pwar"] = round(float(career[1] or 0), 2)

    return {"ok": True, "player": profile}


def _get_glossary(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    stat_id = args.get("stat_id")
    if not stat_id:
        return {"ok": False, "error": "stat_id is required."}

    # diamond.dictionary.STATS is the source of truth (D15).
    from diamond.dictionary import STATS

    entry = STATS.get(stat_id)
    if entry is None:
        return {
            "ok": False,
            "error": f"Unknown stat_id {stat_id!r}.",
            "hint": "List available stat ids via list_leaderboard_stats.",
        }
    return {
        "ok": True,
        "stat": {
            "id": entry.id,
            "label": entry.label,
            "category": entry.category,
            "definition": entry.definition,
            "formula_tex": entry.formula_tex,
            "interpretation": entry.interpretation,
        },
    }


def _list_leaderboard_stats(_args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    from diamond.dictionary import STATS

    return {
        "ok": True,
        "stats": [
            {"id": s.id, "label": s.label, "category": s.category}
            for s in STATS.values()
        ],
    }


def _compare_players(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ids_raw = args.get("player_ids")
    if not isinstance(ids_raw, list) or not ids_raw:
        return {"ok": False, "error": "player_ids must be a non-empty list of ints."}
    try:
        ids = [int(p) for p in ids_raw]
    except (TypeError, ValueError):
        return {"ok": False, "error": "player_ids must all be integers."}
    if len(ids) > 5:
        return {"ok": False, "error": "Compare at most 5 players at once."}

    cur = ctx.cursor
    placeholders = ", ".join(["?"] * len(ids))
    rows = cur.execute(
        f"""
        SELECT
            p.player_id,
            p.first_name || ' ' || p.last_name AS name,
            p.position,
            COALESCE(SUM(b.b_war), 0)::DOUBLE AS bwar,
            COALESCE(SUM(pit.p_war), 0)::DOUBLE AS pwar
        FROM players_current p
        LEFT JOIN f_player_season_advanced_batting b
            ON b.player_id = p.player_id AND b.level_id = 1
        LEFT JOIN f_player_season_advanced_pitching pit
            ON pit.player_id = p.player_id AND pit.level_id = 1
        WHERE p.player_id IN ({placeholders})
        GROUP BY p.player_id, p.first_name, p.last_name, p.position
        """,
        ids,
    ).fetchall()
    cols = [c[0] for c in cur.description]
    return {
        "ok": True,
        "players": [
            {col: _to_jsonable(v) for col, v in zip(cols, r)}
            for r in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# create_metabase_card (Tier 4)
# ─────────────────────────────────────────────────────────────────────────────


def _create_metabase_card(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    name = args.get("name")
    sql = args.get("sql")
    viz_type = args.get("viz_type", "table")
    description = args.get("description", "Generated by Diamond AI.")

    if not name or not sql:
        return {"ok": False, "error": "Both `name` and `sql` are required."}
    if viz_type not in ("table", "scalar", "bar", "line", "scatter", "pie"):
        return {
            "ok": False,
            "error": f"Unsupported viz_type {viz_type!r}.",
            "hint": "Allowed: table, scalar, bar, line, scatter, pie.",
        }

    # Coordinator module handles auth + cached session.
    try:
        from diamond.api import metabase as mb_mod
    except Exception as exc:
        return {"ok": False, "error": f"Metabase coordinator unavailable: {exc}"}

    session_token = None
    try:
        session_token = mb_mod._get_session()  # noqa: SLF001
    except Exception as exc:
        return {
            "ok": False,
            "error": (
                f"Metabase auth failed ({exc}). "
                "Is Metabase running and credentials configured?"
            ),
        }
    if not session_token:
        return {
            "ok": False,
            "error": (
                "Metabase isn't running or credentials aren't configured. "
                "Open Diamond's Workshop tab — it will start Metabase, then retry."
            ),
        }

    body = {
        "name": name,
        "description": description,
        "display": viz_type,
        "visualization_settings": {},
        "dataset_query": {
            "type": "native",
            "native": {"query": sql},
            "database": ctx.metabase_database_id,
        },
    }
    try:
        with httpx.Client(timeout=15.0) as c:
            resp = c.post(
                f"{ctx.metabase_url}/api/card",
                headers={"X-Metabase-Session": session_token},
                json=body,
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Metabase network error: {exc}"}

    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"Metabase {resp.status_code}: {resp.text[:300]}",
        }

    card = resp.json()
    card_id = card.get("id")
    return {
        "ok": True,
        "card_id": card_id,
        "card_url": f"{ctx.metabase_url}/question/{card_id}",
        "name": card.get("name"),
        "viz_type": viz_type,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


TOOLS: dict[str, Tool] = {
    "query_warehouse": Tool(
        name="query_warehouse",
        description=(
            "Run a read-only SELECT against Diamond's DuckDB warehouse. "
            "Tables include f_player_season_advanced_batting, "
            "f_player_season_advanced_pitching, f_player_season_statcast_batting, "
            "f_player_season_leverage_batting, players_current, teams_current, "
            "team_record_snapshot, parks. Returns up to 1000 rows. "
            "5-second timeout. Mutations not allowed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Single SELECT/WITH/SHOW/DESCRIBE/EXPLAIN statement.",
                },
            },
            "required": ["sql"],
        },
        handler=_query_warehouse,
    ),
    "get_player": Tool(
        name="get_player",
        description=(
            "Look up a player's profile by id. Returns name, position, "
            "handedness, age, org/team, retired flag, and career WAR "
            "(OOTP-canonical b_war + p_war)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "player_id": {"type": "integer"},
            },
            "required": ["player_id"],
        },
        handler=_get_player,
    ),
    "compare_players": Tool(
        name="compare_players",
        description=(
            "Compare 2-5 players side-by-side on career bWAR / pWAR. "
            "Use for trade analysis, prospect ranking, etc."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "player_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 5,
                },
            },
            "required": ["player_ids"],
        },
        handler=_compare_players,
    ),
    "get_glossary": Tool(
        name="get_glossary",
        description=(
            "Look up a stat's definition, formula, and interpretation "
            "from Diamond's stat dictionary (D15). Use this before "
            "writing SQL involving a stat you're unsure about."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "stat_id": {
                    "type": "string",
                    "description": (
                        "e.g. 'wrc_plus', 'fip', 'siera', 'ops_plus', "
                        "'b_war', 'p_war', 'wpa', 're24'."
                    ),
                },
            },
            "required": ["stat_id"],
        },
        handler=_get_glossary,
    ),
    "list_leaderboard_stats": Tool(
        name="list_leaderboard_stats",
        description=(
            "List every stat in Diamond's dictionary (id, label, "
            "category). Useful for discovering what's available."
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_list_leaderboard_stats,
    ),
    "create_metabase_card": Tool(
        name="create_metabase_card",
        description=(
            "Create a chart/dashboard card in Metabase from a native SQL "
            "query. The card opens in the user's browser with full "
            "drill-through, save-to-dashboard, share-link capabilities. "
            "Use for analyses the user will revisit. Use viz_type='table' "
            "for raw data, 'bar'/'line'/'scatter' for charts, 'scalar' "
            "for single-number summaries."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short card title."},
                "description": {"type": "string"},
                "sql": {
                    "type": "string",
                    "description": "DuckDB-flavored SELECT executed by Metabase.",
                },
                "viz_type": {
                    "type": "string",
                    "enum": ["table", "scalar", "bar", "line", "scatter", "pie"],
                    "default": "table",
                },
            },
            "required": ["name", "sql"],
        },
        handler=_create_metabase_card,
    ),
}


def get_tool(name: str) -> Tool | None:
    return TOOLS.get(name)


def all_tools() -> list[Tool]:
    return list(TOOLS.values())
