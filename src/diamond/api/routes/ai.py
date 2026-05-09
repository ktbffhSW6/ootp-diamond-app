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

    new = AISettings(
        provider=target_provider, model=new_model, use_level=new_use_level
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
