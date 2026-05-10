"""AI settings — load/save user config + keyring-backed API keys.

Storage layout (D14):
- Non-secret settings live in ``~/.diamond/settings.toml``:
  ``provider`` / ``model`` / ``use_level``.
- Secret API keys live in the OS keyring under the service name
  ``"diamond-ai"`` and the account name ``"<provider>-api-key"``
  (e.g., ``anthropic-api-key`` / ``openai-api-key``). Stored separately
  per provider so users can pre-load multiple keys and switch
  providers without re-entering anything.

Convention: settings are a plain dataclass (not Pydantic) since they
don't cross the wire — the API surface returns redacted views with
``has_key`` booleans instead of raw secrets.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import keyring

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────


KEYRING_SERVICE = "diamond-ai"
"""Keyring service identifier — opaque to the user, used by the
keyring backend to namespace credentials. Matches what `diamond ai
settings` writes; if you change it, existing users will see their
saved keys go missing."""

UseLevel = Literal["off", "on_demand", "smart", "always_on"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")
DEFAULT_MODELS: dict[str, str] = {
    # Use the rolling alias rather than a pinned snapshot so we don't
    # bit-rot when Anthropic retires older snapshots (the original
    # D14 default `claude-3-5-haiku-20241022` 404'd starting 2026-05).
    # Users can pin a specific snapshot in /settings/ai if they want
    # determinism.
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
}

# Models we know are retired or otherwise broken — auto-migrated to
# their replacement at settings-load time so existing user configs
# don't keep 404'ing.
RETIRED_MODELS: dict[str, str] = {
    # 3.5 Haiku snapshot retired by Anthropic 2026-05; rolling
    # alias lives on as the canonical Haiku 4.5.
    "claude-3-5-haiku-20241022": "claude-haiku-4-5",
    "claude-3-5-haiku-latest": "claude-haiku-4-5",
}


# ─────────────────────────────────────────────────────────────────────────────
# Settings dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AISettings:
    """User-facing AI configuration.

    `provider` selects which adapter handles requests. `model` is
    provider-specific (e.g., "claude-haiku-4-5" for Anthropic,
    "gpt-4o-mini" for OpenAI). `use_level` reserves the D14
    four-tier API surface; v1 only acts on "off" (gates all calls) vs
    anything else (allows on-demand calls).

    `persona` (D33 follow-up) is a free-form personality / style
    instruction the user can set in the Settings page. If non-empty,
    it gets appended to the chat system prompt verbatim. Lets users
    iterate on tone without code changes — anything from "be terse,
    bullet-list everything" to "respond as a hardboiled scout from
    the 70s".
    """

    provider: str = "anthropic"
    model: str = DEFAULT_MODELS["anthropic"]
    use_level: UseLevel = "on_demand"
    persona: str = ""

    def to_dict(self) -> dict[str, str]:
        """JSON-friendly dict for the API surface (no secrets)."""
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


def _settings_path() -> Path:
    """Resolve ``~/.diamond/settings.toml`` and ensure the parent dir exists."""
    base = Path(os.path.expanduser("~")) / ".diamond"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.toml"


def load_settings() -> AISettings:
    """Read settings from disk, returning defaults if the file is missing
    or malformed.

    Defensive: never raises on parse error — a corrupt settings.toml
    gracefully degrades to defaults rather than blocking the app.
    """
    path = _settings_path()
    if not path.exists():
        return AISettings()
    try:
        with path.open("rb") as f:
            data = tomllib.load(f).get("ai", {})
    except tomllib.TOMLDecodeError:
        return AISettings()

    provider = data.get("provider", "anthropic")
    if provider not in SUPPORTED_PROVIDERS:
        provider = "anthropic"
    model = data.get("model") or DEFAULT_MODELS.get(provider, "")
    # Auto-migrate retired models in-place. We persist the new value
    # so subsequent loads short-circuit. Failures are silent — worst
    # case the API surfaces the upstream 404 again next call.
    if model in RETIRED_MODELS:
        replacement = RETIRED_MODELS[model]
        model = replacement
        try:
            migrated = AISettings(
                provider=provider,
                model=replacement,
                use_level=data.get("use_level", "on_demand"),
            )
            save_settings(migrated)
        except Exception:
            pass
    use_level = data.get("use_level", "on_demand")
    if use_level not in ("off", "on_demand", "smart", "always_on"):
        use_level = "on_demand"
    persona = str(data.get("persona", "") or "")
    return AISettings(
        provider=provider,
        model=model,
        use_level=use_level,
        persona=persona,
    )


def save_settings(settings: AISettings) -> None:
    """Persist non-secret settings to ``~/.diamond/settings.toml``.

    We hand-roll the TOML serialization to avoid pulling in tomli-w
    (Python's stdlib reads but doesn't write TOML).
    """
    if settings.provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider '{settings.provider}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    if settings.use_level not in ("off", "on_demand", "smart", "always_on"):
        raise ValueError(f"Unsupported use_level '{settings.use_level}'")

    # TOML basic-string escapes: backslash, double-quote, and the
    # control chars (newline, carriage return, tab). Persona is free-
    # form and likely multi-line, so we escape newlines as \n rather
    # than switching to TOML multi-line strings — keeps the file
    # diff-friendly.
    persona_escaped = (
        settings.persona
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        if settings.persona
        else ""
    )
    body = (
        "# Diamond AI settings (D14 + D33 persona). API keys live in\n"
        "# the OS keyring, not this file. Edit via the Diamond\n"
        "# Settings page or write directly here — the app reloads on\n"
        "# every API call.\n"
        "[ai]\n"
        f'provider = "{settings.provider}"\n'
        f'model = "{settings.model}"\n'
        f'use_level = "{settings.use_level}"\n'
        f'persona = "{persona_escaped}"\n'
    )
    _settings_path().write_text(body, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Keyring access
# ─────────────────────────────────────────────────────────────────────────────


def keyring_account(provider: str) -> str:
    """Account name for the keyring entry of one provider's key."""
    return f"{provider}-api-key"


def get_api_key(provider: str) -> str | None:
    """Fetch the stored API key for `provider`, or None if not set.

    Failure to access the keyring (e.g., on a headless Linux without a
    Secret Service available) returns None silently — the caller
    raises ``AIConfigError`` upstream so the user sees a useful error.
    """
    try:
        return keyring.get_password(KEYRING_SERVICE, keyring_account(provider))
    except keyring.errors.KeyringError:
        return None


def set_api_key(provider: str, key: str) -> None:
    """Store the API key for `provider` in the OS keyring."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider '{provider}'")
    keyring.set_password(KEYRING_SERVICE, keyring_account(provider), key)


def delete_api_key(provider: str) -> None:
    """Remove the stored key. No-op if there's nothing to delete."""
    try:
        keyring.delete_password(KEYRING_SERVICE, keyring_account(provider))
    except keyring.errors.PasswordDeleteError:
        pass


def has_api_key(provider: str) -> bool:
    """Convenience predicate — true iff the keyring has a key for this provider."""
    return get_api_key(provider) is not None
