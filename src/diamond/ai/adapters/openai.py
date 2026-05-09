"""OpenAI Chat Completions API adapter.

Thin httpx wrapper. No SDK dep — keeps the bundle small. Uses the v1
Chat Completions endpoint (broadly supported across compatible
backends — Azure OpenAI, OpenRouter, vLLM all expose this shape).
"""

from __future__ import annotations

import httpx

from diamond.ai.client import AIClient, AIClientError

_API_URL = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class OpenAIClient(AIClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai"

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
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        try:
            with httpx.Client(timeout=_TIMEOUT) as c:
                resp = c.post(_API_URL, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise AIClientError(f"OpenAI network error: {e}") from e

        if resp.status_code != 200:
            try:
                err = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err = resp.text
            raise AIClientError(f"OpenAI {resp.status_code}: {err[:300]}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise AIClientError("OpenAI returned empty choices")
        msg = choices[0].get("message", {})
        text = msg.get("content")
        if not text:
            raise AIClientError("OpenAI returned no content")
        return str(text).strip()
