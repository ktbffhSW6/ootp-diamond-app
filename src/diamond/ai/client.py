"""AIClient interface — provider-agnostic shell over LLM HTTP APIs.

Concrete adapters live under ``adapters/``. The interface is
intentionally minimal in v1 — a single `complete(prompt, system,
max_tokens) -> str` synchronous call. No streaming, no tool use, no
multi-turn history. The route layer composes the prompt; the client
just executes.

Errors:
- ``AIConfigError`` — user-facing, before any HTTP call (no key set,
  unsupported provider, etc.). Surfaces as 400 in the API.
- ``AIClientError`` — wrap any provider-side error (auth, network,
  schema). Surfaces as 502 in the API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from diamond.ai.settings import AISettings, get_api_key


class AIConfigError(Exception):
    """Raised when the AI subsystem isn't configured for a request.

    Examples: no API key set, provider unsupported, settings file
    corrupted. The route maps this to HTTP 400.
    """


class AIClientError(Exception):
    """Raised when a provider call fails (auth, network, schema mismatch).

    The route maps this to HTTP 502.
    """


class AIClient(ABC):
    """Provider-agnostic completion interface."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 600,
    ) -> str:
        """Generate a completion. Returns the assistant text."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Lowercase provider identifier for logging."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Currently-configured model id."""


def get_active_client(settings: AISettings) -> AIClient:
    """Resolve a configured client for the current settings.

    Raises ``AIConfigError`` if the user hasn't set a key yet, or if
    the provider is unsupported.
    """
    if settings.provider == "anthropic":
        from diamond.ai.adapters.anthropic import AnthropicClient

        key = get_api_key("anthropic")
        if not key:
            raise AIConfigError(
                "No Anthropic API key set. Visit /settings/ai to add one."
            )
        return AnthropicClient(api_key=key, model=settings.model)
    if settings.provider == "openai":
        from diamond.ai.adapters.openai import OpenAIClient

        key = get_api_key("openai")
        if not key:
            raise AIConfigError(
                "No OpenAI API key set. Visit /settings/ai to add one."
            )
        return OpenAIClient(api_key=key, model=settings.model)
    raise AIConfigError(f"Unsupported provider '{settings.provider}'")
