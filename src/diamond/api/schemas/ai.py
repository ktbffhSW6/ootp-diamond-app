"""Pydantic schemas for the AI overlay (D14).

The API never echoes raw API keys — settings GET returns a
``has_key`` boolean per provider; settings POST accepts an
``api_key`` field that gets immediately written to the OS keyring
and dropped from memory.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


UseLevel = Literal["off", "on_demand", "smart", "always_on"]


class AIProviderInfo(BaseModel):
    """Per-provider metadata — name + key-presence flag.

    Listed for every supported provider so the settings UI can show
    "key set" / "key missing" indicators without needing a separate
    has-key endpoint per provider.
    """

    name: str
    has_key: bool


class AISettingsResponse(BaseModel):
    """Current AI settings — non-secret view.

    `provider` / `model` / `use_level` mirror the on-disk settings;
    `providers` lists all supported providers + their key-set state
    for the picker UI.
    """

    provider: str
    model: str
    use_level: UseLevel
    providers: list[AIProviderInfo]


class AISettingsUpdate(BaseModel):
    """POST body for updating AI settings.

    Any subset of fields is allowed. `api_key` is write-only — it's
    stored in the OS keyring under the matching `provider` and never
    returned. To clear a key, send `api_key=""` and the route deletes
    the keyring entry.
    """

    provider: str | None = None
    model: str | None = None
    use_level: UseLevel | None = None
    api_key: str | None = Field(default=None, description="API key (write-only; stored in OS keyring)")


class AISummarizeRequest(BaseModel):
    """POST body for the summarize endpoint.

    `kind` selects the prompt template — only "player" in v1. `target_id`
    is the player_id (or future team_id / etc.). `context` is an
    optional free-form addendum the frontend can pass (e.g., "compare
    to last year").
    """

    kind: Literal["player"]
    target_id: int
    context: str | None = None


class AISummarizeResponse(BaseModel):
    """Generated summary — plain markdown text.

    `provider` + `model` are echoed so the UI can show a "Generated
    by claude-3-5-haiku" footer on the result.
    """

    text: str
    provider: str
    model: str
