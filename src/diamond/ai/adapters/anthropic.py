"""Anthropic Messages API adapter.

Thin httpx wrapper over the v1 Messages endpoint. No SDK dep — keeps
the bundle small and the surface portable. We use ``anthropic-version``
header pinned to ``2023-06-01`` (the stable, currently-supported spec).
"""

from __future__ import annotations

import httpx

from diamond.ai.client import AIClient, AIClientError

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class AnthropicClient(AIClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 600,
    ) -> str:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        try:
            with httpx.Client(timeout=_TIMEOUT) as c:
                resp = c.post(_API_URL, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise AIClientError(f"Anthropic network error: {e}") from e

        if resp.status_code != 200:
            try:
                err = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err = resp.text
            raise AIClientError(f"Anthropic {resp.status_code}: {err[:300]}")

        data = resp.json()
        content = data.get("content", [])
        if not content:
            raise AIClientError("Anthropic returned empty content")
        # Messages API content is a list of blocks; we want the first
        # text block. Future tool-use blocks will need richer parsing.
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", "")).strip()
        raise AIClientError("Anthropic returned no text block")
