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
from typing import Iterator

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
    """Provider-agnostic completion + chat-with-tools interface."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 600,
    ) -> str:
        """Generate a completion. Returns the assistant text.

        Single-turn, no tools. Used by the legacy /api/ai/summarize
        endpoint. New code should prefer ``chat`` for multi-turn or
        tool-using conversations.
        """

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> dict:
        """One round-trip in a multi-turn chat with optional tools.

        Args:
            messages: provider-native message list. Each element has
                ``role`` (``user`` / ``assistant``) and ``content``.
                Anthropic content can be a string or a list of typed
                blocks (text / tool_use / tool_result).
            system: optional system prompt.
            tools: provider-native tool declaration list. Each tool
                has ``name``, ``description``, ``input_schema``.
            max_tokens: cap on response.

        Returns a dict with:
            stop_reason (str): 'end_turn' | 'tool_use' | 'max_tokens'
            content (list[dict]): provider-native content blocks.
                Each block has ``type`` (``text`` or ``tool_use``)
                plus type-specific fields. ``tool_use`` blocks include
                ``id``, ``name``, ``input``.

        The route layer drives the loop: while stop_reason ==
        'tool_use', execute each tool_use block, append the
        assistant message + a user message with tool_result blocks,
        and call chat() again.
        """

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> Iterator[dict]:
        """Streaming variant of ``chat`` (D35 Tier C).

        Yields a sequence of provider-agnostic events:

            {"type": "text_delta", "text": "...chunk..."}
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
            {"type": "done", "stop_reason": "end_turn" | "tool_use" | ...}

        Adapters that don't support native streaming may degrade to
        a synchronous round-trip and emit the full text as a single
        text_delta event (the default fallback below). Adapters that
        do support streaming override this method to yield deltas as
        the provider produces them.
        """
        # Default fallback: call non-streaming chat() and re-emit as
        # a single text_delta + tool_use events + done. Concrete
        # adapters override this for true streaming.
        result = self.chat(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
        )
        for block in result.get("content", []):
            if not isinstance(block, dict):
                continue
            t = block.get("type")
            if t == "text":
                txt = block.get("text", "")
                if txt:
                    yield {"type": "text_delta", "text": txt}
            elif t == "tool_use":
                yield {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input") or {},
                }
        yield {
            "type": "done",
            "stop_reason": result.get("stop_reason", "end_turn"),
        }

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
