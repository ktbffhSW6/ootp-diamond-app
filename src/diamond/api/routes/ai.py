"""AI overlay routes (D14).

Endpoints:
- ``GET /api/ai/settings`` — current settings + per-provider key-set
  status. No secrets in the response.
- ``POST /api/ai/settings`` — update provider / model / use_level
  and/or write an API key to the OS keyring. Empty `api_key` clears
  the stored key for the targeted provider.
- ``POST /api/ai/summarize`` — generate a summary for a "player"
  target. Composes a context block from the warehouse, hits the
  configured provider, returns the generated text.

Errors:
- ``AIConfigError`` -> 400 (no key configured / unsupported provider).
- ``AIClientError`` -> 502 (provider call failed).
- Both surface as plain JSON ``{"detail": "..."}``.

The summarize endpoint never returns the raw prompt or system; it
only returns the assistant text. Logs intentionally don't dump
prompts either — player payloads include name + ratings and we
don't need that in our log files.
"""

from __future__ import annotations

import logging
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from diamond.ai import (
    AIClientError,
    AIConfigError,
    get_active_client,
)
from diamond.ai.settings import (
    AISettings,
    DEFAULT_MODELS,
    SUPPORTED_PROVIDERS,
    delete_api_key,
    has_api_key,
    load_settings,
    save_settings,
    set_api_key,
)
from diamond.api.schemas import (
    AIProviderInfo,
    AISettingsResponse,
    AISettingsUpdate,
    AISummarizeRequest,
    AISummarizeResponse,
)
from diamond.api.warehouse import get_cursor

router = APIRouter()
log = logging.getLogger("diamond.ai")


# ─────────────────────────────────────────────────────────────────────────────
# Settings GET / POST
# ─────────────────────────────────────────────────────────────────────────────


def _settings_response(s: AISettings) -> AISettingsResponse:
    return AISettingsResponse(
        provider=s.provider,
        model=s.model,
        use_level=s.use_level,
        persona=s.persona,
        providers=[
            AIProviderInfo(name=p, has_key=has_api_key(p))
            for p in SUPPORTED_PROVIDERS
        ],
    )


@router.get("/ai/settings", response_model=AISettingsResponse)
def get_ai_settings() -> AISettingsResponse:
    """Read non-secret AI settings + per-provider key-set status."""
    return _settings_response(load_settings())


@router.post("/ai/settings", response_model=AISettingsResponse)
def update_ai_settings(body: AISettingsUpdate) -> AISettingsResponse:
    """Update settings and/or write an API key to the OS keyring.

    Field handling:
    - `provider` switches the active provider; if the user hasn't set a
      model, we default to the new provider's default.
    - `model` overrides the saved model.
    - `use_level` sets the global tier.
    - `api_key`:
      - Non-empty string -> written to keyring under `provider` (or the
        currently-active provider if `provider` isn't in the same body).
      - Empty string ("") -> deletes the keyring entry for that provider.
      - None / omitted -> no change to keyring.
    """
    current = load_settings()
    target_provider = body.provider or current.provider
    if target_provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported provider '{target_provider}'. "
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
            ),
        )

    # Resolve final model
    if body.provider and body.provider != current.provider and body.model is None:
        # Switching provider without explicit model -> use default
        new_model = DEFAULT_MODELS[target_provider]
    else:
        new_model = body.model or current.model or DEFAULT_MODELS[target_provider]

    new_use_level = body.use_level or current.use_level
    # persona: None = leave alone, "" = clear, str = set. Differs from
    # the rest because empty string is a valid clear command.
    new_persona = body.persona if body.persona is not None else current.persona

    new = AISettings(
        provider=target_provider,
        model=new_model,
        use_level=new_use_level,
        persona=new_persona,
    )
    try:
        save_settings(new)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Key write — happens AFTER the settings save so a failure here
    # leaves the user with their old key intact.
    if body.api_key is not None:
        if body.api_key == "":
            delete_api_key(target_provider)
            log.info("AI key for %s deleted", target_provider)
        else:
            try:
                set_api_key(target_provider, body.api_key)
                log.info("AI key for %s updated (%d chars)", target_provider, len(body.api_key))
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to write to OS keyring: {e}",
                ) from e

    return _settings_response(new)


# ─────────────────────────────────────────────────────────────────────────────
# Summarize endpoint
# ─────────────────────────────────────────────────────────────────────────────


_PLAYER_CONTEXT_SQL = """
WITH bio AS (
    SELECT
        player_id,
        first_name || ' ' || last_name AS name,
        date_of_birth,
        position,
        bats,
        throws
    FROM players_current
    WHERE player_id = ?
),
career_bat AS (
    SELECT player_id,
           SUM(g) AS g, SUM(pa) AS pa, SUM(ab) AS ab, SUM(h) AS h,
           SUM(hr) AS hr, SUM(rbi) AS rbi, SUM(sb) AS sb,
           SUM(bb) AS bb, SUM(k) AS k
    FROM f_player_season_batting
    WHERE split_id = 1 AND player_id = ?
    GROUP BY player_id
),
career_bwar AS (
    SELECT player_id, SUM(b_war) AS b_war
    FROM f_player_season_advanced_batting
    WHERE player_id = ?
    GROUP BY player_id
),
career_pwar AS (
    SELECT player_id, SUM(p_war) AS p_war
    FROM f_player_season_advanced_pitching
    WHERE player_id = ?
    GROUP BY player_id
),
recent AS (
    SELECT year, ops_plus, wrc_plus, b_war
    FROM f_player_season_advanced_batting
    WHERE player_id = ? AND level_id = 1
    ORDER BY year DESC
    LIMIT 3
)
SELECT
    b.name, b.date_of_birth, b.position, b.bats, b.throws,
    cb.g, cb.pa, cb.ab, cb.h, cb.hr, cb.rbi, cb.sb, cb.bb, cb.k,
    cw.b_war, cp.p_war,
    (SELECT STRING_AGG(year || ': OPS+ ' || COALESCE(ops_plus, 0)
                       || ' wRC+ ' || COALESCE(wrc_plus, 0)
                       || ' bWAR ' || COALESCE(ROUND(b_war, 1), 0),
                       ' | ') FROM recent) AS recent_summary
FROM bio b
LEFT JOIN career_bat  cb ON cb.player_id = b.player_id
LEFT JOIN career_bwar cw ON cw.player_id = b.player_id
LEFT JOIN career_pwar cp ON cp.player_id = b.player_id
"""


_POSITION_NAMES = {
    1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS",
    7: "LF", 8: "CF", 9: "RF", 10: "DH",
}
_BATS = {1: "R", 2: "L", 3: "S"}


def _build_player_prompt(con: duckdb.DuckDBPyConnection, player_id: int, context: str | None) -> tuple[str, str]:
    """Compose (system, prompt) for a player summary."""
    row = con.execute(
        _PLAYER_CONTEXT_SQL,
        [player_id, player_id, player_id, player_id, player_id],
    ).fetchone()
    if row is None or row[0] is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    (
        name, dob, position, bats, throws,
        g, pa, ab, h, hr, rbi, sb, bb, k,
        b_war, p_war, recent_summary,
    ) = row

    pos_label = _POSITION_NAMES.get(int(position), "?") if position is not None else "?"
    bats_label = _BATS.get(int(bats), "?") if bats is not None else "?"

    facts: list[str] = [
        f"Name: {name}",
        f"Position: {pos_label}",
        f"Bats: {bats_label}",
        f"DOB: {dob}",
    ]
    if g and pa:
        facts.append(
            f"Career batting (overall split): {g} G, {pa} PA, {ab} AB, "
            f"{h} H, {hr} HR, {rbi} RBI, {sb} SB, {bb} BB, {k} K."
        )
    if b_war:
        facts.append(f"Career bWAR (OOTP-canonical): {b_war:.1f}.")
    if p_war:
        facts.append(f"Career pWAR (FIP-WAR with leverage): {p_war:.1f}.")
    if recent_summary:
        facts.append(f"Recent MLB seasons: {recent_summary}")

    if context:
        facts.append(f"User context: {context}")

    system = (
        "You are a baseball analyst summarizing a player's career for a "
        "sabermetrics-literate fan. Be concise (2-3 short paragraphs max), "
        "concrete, and avoid clichés. If the data shows a clear strength "
        "or weakness, name it. Use plain English; assume the reader knows "
        "OPS+ / wRC+ / WAR."
    )
    prompt = (
        "Summarize this player based on the warehouse-derived facts below. "
        "Don't invent numbers not in the data.\n\n"
        + "\n".join(f"- {f}" for f in facts)
    )
    return system, prompt


@router.post("/ai/summarize", response_model=AISummarizeResponse)
def ai_summarize(
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
    body: AISummarizeRequest,
) -> AISummarizeResponse:
    """Generate an AI summary for the requested target.

    v1: only `kind="player"` supported. The router gates on
    ``settings.use_level != "off"`` — when AI is fully off, the
    request returns 400 explaining the user opted out.
    """
    settings = load_settings()
    if settings.use_level == "off":
        raise HTTPException(
            status_code=400,
            detail="AI is set to Off. Change use_level in /settings/ai to enable.",
        )
    try:
        client = get_active_client(settings)
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if body.kind == "player":
        system, prompt = _build_player_prompt(cursor, body.target_id, body.context)
    else:
        # The Literal["player"] in AISummarizeRequest already gates this;
        # the branch is defensive for when we add other kinds.
        raise HTTPException(status_code=400, detail=f"Unsupported kind '{body.kind}'")

    try:
        text = client.complete(prompt, system=system, max_tokens=600)
    except AIClientError as e:
        log.warning("AI provider error (%s/%s): %s", client.provider_name, client.model, e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    return AISummarizeResponse(
        text=text,
        provider=client.provider_name,
        model=client.model,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chat endpoint (D33) — full AI sidebar with page context + tools
# ─────────────────────────────────────────────────────────────────────────────


import json as _json  # noqa: E402

from diamond.ai.tools import TOOLS, ToolContext, all_tools  # noqa: E402
from diamond.api.schemas import (  # noqa: E402
    ChatContentBlock,
    ChatRequest,
    ChatResponse,
    ChatTurn,
)


# Tier 3 prompt templates. The route prepends one of these to the
# user's input when ``mode != "chat"``. Keeping them in one place
# makes the GM-copilot UI a thin wrapper — the frontend just sends a
# mode string + free-form input.
_MODE_PROMPTS: dict[str, str] = {
    "callup": (
        "You are advising the GM on a roster move. Use the warehouse "
        "to compare promotion candidates against their potential MLB "
        "replacements. Cite OPS+ / wRC+ for batters, ERA+ / FIP for "
        "pitchers, plus career trajectory. Recommend a specific move."
    ),
    "trade": (
        "You are evaluating a trade idea. Use compare_players + "
        "query_warehouse to assess each side's WAR contribution, "
        "contract status, age curve, and positional fit. State which "
        "side wins and why."
    ),
    "draft": (
        "You are reviewing a draft class outcome. Pull from "
        "draft_class + f_player_season_advanced_* to find hits, "
        "misses, and best-pick patterns. Quantify with WAR per pick."
    ),
}


def _build_system_prompt(
    mode: str,
    page_context: dict | None,
    persona: str = "",
) -> str:
    base = (
        "You are Diamond's analytical co-pilot — a sabermetrics-fluent "
        "assistant for an OOTP 27 dynasty. The user is the GM of the "
        "Boston Red Sox (organization_id=4, MLB league_id=203) in the "
        "'Building the Green Monster' save. Current season is 2029; "
        "data covers 2026-2029 plus pre-2026 real-history baselines.\n\n"
        "**Default to ACTING, not asking.** When the user asks a "
        "concrete question, your first instinct should be to query "
        "the warehouse and return a specific answer with numbers. "
        "Do NOT ask clarifying questions like 'which position?' or "
        "'do you mean MLB or AAA?' unless you've already tried to "
        "find the answer and genuinely couldn't. The user has the "
        "data and the question — they want the analysis, not a "
        "back-and-forth.\n\n"
        "**Cite tool sources for every specific number.** When you "
        "state a stat, age, year, or rank in your final answer, that "
        "number must come from a tool call you actually made in this "
        "conversation. Do NOT cite numbers from training-data memory "
        "(career WARs, birth years, peak season totals, etc.) — they "
        "are frequently wrong and you have no way to know when. If "
        "you don't have a tool result backing a number, either run "
        "the relevant tool first or omit the number.\n\n"
        "**Always use `get_career_arc` for age-related questions.** "
        "Computing 'in year X, player Y was age Z' from training "
        "data is a recurring failure mode. The tool returns "
        "deterministically-computed age per season + warehouse-"
        "aggregated career WAR totals, all from the same payload — "
        "you cite from one source, no math errors, no hallucinations.\n\n"
        "You have read-only access to a DuckDB warehouse via the "
        "`query_warehouse` tool. Key tables: "
        "`players_current` (uses `first_name` + `last_name` — there's "
        "no `name` column), `f_player_season_advanced_batting` (wOBA, "
        "wRC+, OPS+, b_war), `f_player_season_advanced_pitching` (FIP, "
        "ERA+, p_war), `f_player_season_statcast_batting` (EV, "
        "barrel%), `f_player_season_leverage_batting` (WPA, RE24, "
        "Clutch), `team_record_snapshot`, `parks`. **Call "
        "`describe_table` first** when you're not sure what columns "
        "exist — guessing column names produces Binder Errors. Use "
        "`get_glossary` if you're unsure what a stat means.\n\n"
        "Org structure (use these directly, no need to look up): "
        "Sox MLB team_id=4 (level_id=1). AAA Worcester Red Sox "
        "(level_id=2), AA Portland Sea Dogs (level_id=3), High-A "
        "Greenville Drive (level_id=4), A Salem Red Sox (level_id=5). "
        "Filter by `organization_id=4` to get the whole pyramid; "
        "`team_id=4` for MLB only.\n\n"
        "Be direct and quantitative. Cite specific numbers from the "
        "warehouse, not vibes. When you produce a recommendation, "
        "state it plainly with names + stats backing it.\n\n"
        "Stat conventions: OPS+/wRC+/ERA+ are 100-relative (>100 is "
        "above average). WAR is OOTP-canonical (b_war for batters, "
        "p_war for pitchers — IE-A-tier reconciled). League scope is "
        "MLB + affiliated minors + DSL + AFL. Pre-2026 player-seasons "
        "have real-history baselines from L_REF (D29).\n\n"
        "When the user might want to revisit an analysis, offer to "
        "create a Metabase card via `create_metabase_card` — those "
        "live in the user's Workshop tab and can be saved to "
        "dashboards."
    )
    if mode in _MODE_PROMPTS:
        base = base + "\n\nMode-specific guidance: " + _MODE_PROMPTS[mode]

    persona_clean = (persona or "").strip()
    if persona_clean:
        base += (
            "\n\nUser-set personality / style preferences (these "
            "override defaults where they conflict):\n"
            + persona_clean
        )

    if page_context:
        path = page_context.get("pathname")
        payload = page_context.get("payload")
        page_block = f"\n\nThe user is currently on page: {path}"
        if payload:
            try:
                serialized = _json.dumps(payload, default=str, indent=2)
                if len(serialized) > 4000:
                    serialized = serialized[:4000] + "\n... (truncated)"
                page_block += (
                    f"\nPage data:\n```json\n{serialized}\n```\n"
                    "Use this as default context — the user is asking "
                    "about what's on this page unless they say otherwise."
                )
            except Exception:
                pass
        base += page_block

    return base


def _to_provider_messages(turns: list[ChatTurn]) -> list[dict]:
    """Translate frontend ChatTurn list to provider-native messages.

    The provider adapters speak Anthropic-shaped messages (which our
    ChatTurn mirrors), so this is mostly a structural copy.
    """
    out: list[dict] = []
    for t in turns:
        blocks: list[dict] = []
        for b in t.content:
            block: dict = {"type": b.type}
            if b.type == "text" and b.text is not None:
                block["text"] = b.text
            elif b.type == "tool_use":
                block["id"] = b.id
                block["name"] = b.name
                block["input"] = b.input or {}
            elif b.type == "tool_result":
                block["tool_use_id"] = b.tool_use_id
                block["content"] = (
                    b.content
                    if isinstance(b.content, str)
                    else _json.dumps(b.content, default=str)
                )
                if b.is_error:
                    block["is_error"] = True
            blocks.append(block)
        out.append({"role": t.role, "content": blocks})
    return out


def _from_provider_blocks(blocks: list[dict]) -> list[ChatContentBlock]:
    out: list[ChatContentBlock] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            out.append(ChatContentBlock(type="text", text=b.get("text", "")))
        elif t == "tool_use":
            out.append(ChatContentBlock(
                type="tool_use",
                id=b.get("id"),
                name=b.get("name"),
                input=b.get("input") or {},
            ))
    return out


_MAX_ITERATIONS = 6  # cap on tool round-trips per request


@router.post("/ai/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    cursor: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> ChatResponse:
    """Multi-turn chat with optional tool use (D33).

    The route drives the tool loop: model emits tool_use blocks, we
    execute them server-side, append tool_result blocks, call the
    model again. ``_MAX_ITERATIONS`` caps the loop to avoid runaway
    behavior.

    Returns every turn produced this request (one assistant turn per
    iteration, plus user turns carrying tool_result blocks). The
    frontend appends these to its existing thread.
    """
    try:
        settings = load_settings()
        client = get_active_client(settings)
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Build the working message list: existing thread + new user input.
    working: list[dict] = _to_provider_messages(body.messages)
    working.append({"role": "user", "content": body.user_input})

    system = _build_system_prompt(
        body.mode,
        body.page_context.model_dump() if body.page_context else None,
        persona=settings.persona,
    )

    tools_native = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in all_tools()
    ]

    ctx = ToolContext(cursor=cursor)
    appended: list[ChatTurn] = []
    iterations = 0
    stop_reason = "end_turn"

    while iterations < _MAX_ITERATIONS:
        iterations += 1
        try:
            response = client.chat(
                working,
                system=system,
                tools=tools_native,
                max_tokens=1500,
            )
        except AIClientError as e:
            log.warning("AI chat provider error: %s", e)
            raise HTTPException(status_code=502, detail=str(e)) from e

        stop_reason = response.get("stop_reason", "end_turn")
        content_blocks = response.get("content", [])

        # Surface the assistant turn (text + tool_use, both visible
        # in the UI so users can see what the model called).
        assistant_turn = ChatTurn(
            role="assistant",
            content=_from_provider_blocks(content_blocks),
        )
        appended.append(assistant_turn)
        working.append({"role": "assistant", "content": content_blocks})

        if stop_reason != "tool_use":
            break

        # Run every tool_use block; emit a single user turn carrying
        # all tool_result blocks (Anthropic-native shape).
        tool_results: list[dict] = []
        ui_results: list[ChatContentBlock] = []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            tool = TOOLS.get(name)
            if tool is None:
                payload = {"ok": False, "error": f"Unknown tool {name!r}."}
            else:
                try:
                    payload = tool.handler(block.get("input") or {}, ctx)
                except Exception as exc:  # pragma: no cover
                    log.exception("tool %s raised", name)
                    payload = {"ok": False, "error": f"Tool internal error: {exc}"}

            is_error = isinstance(payload, dict) and payload.get("ok") is False
            tool_use_id = block.get("id", "")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": _json.dumps(payload, default=str),
                "is_error": is_error,
            })
            ui_results.append(ChatContentBlock(
                type="tool_result",
                tool_use_id=tool_use_id,
                content=payload,
                is_error=is_error,
            ))

        appended.append(ChatTurn(role="user", content=ui_results))
        working.append({"role": "user", "content": tool_results})

    if iterations >= _MAX_ITERATIONS and stop_reason == "tool_use":
        # Truncate gracefully — emit a final assistant text saying we
        # capped iterations rather than spinning forever.
        appended.append(ChatTurn(
            role="assistant",
            content=[ChatContentBlock(
                type="text",
                text=(
                    "I've used the maximum number of tool calls for this "
                    "turn. Let me know if you'd like me to keep going."
                ),
            )],
        ))
        stop_reason = "end_turn"

    return ChatResponse(
        appended=appended,
        stop_reason=stop_reason,
        iterations=iterations,
    )
