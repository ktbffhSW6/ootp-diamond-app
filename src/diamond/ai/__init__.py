"""AI overlay subsystem (D14).

Public surface:

- ``settings.AISettings`` — load/save user-facing AI config.
  Persists non-secret fields to ``~/.diamond/settings.toml`` and
  routes API-key storage through the OS keyring.
- ``client.AIClient`` — thin provider-agnostic interface (`complete`).
  Concrete adapters live under ``adapters/`` (Anthropic, OpenAI).
- ``client.get_active_client(settings)`` — factory that resolves a
  configured client given current settings; raises ``AIConfigError``
  if the user hasn't configured a key yet.

This is a v1-viable subset of D14: keyring storage + two providers
(Anthropic, OpenAI) + on-demand use level. Pricing fetcher / daily
cap / smart auto-runs are deferred to a follow-on slice — the
``AISettings.use_level`` field reserves the API surface.
"""

from diamond.ai.client import AIClient, AIClientError, AIConfigError, get_active_client
from diamond.ai.settings import AISettings, load_settings, save_settings

__all__ = [
    "AIClient",
    "AIClientError",
    "AIConfigError",
    "AISettings",
    "get_active_client",
    "load_settings",
    "save_settings",
]
