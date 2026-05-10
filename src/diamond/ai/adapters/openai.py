"""OpenAI Chat Completions API adapter.

Thin httpx wrapper. No SDK dep — keeps the bundle small. Uses the v1
Chat Completions endpoint (broadly supported across compatible
backends — Azure OpenAI, OpenRouter, vLLM all expose this shape).
"""

from __future__ import annotations

import json

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

    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> dict:
        """Multi-turn chat with optional tool use (D33).

        The route layer speaks Anthropic-shaped messages
        (content-block lists with text / tool_use / tool_result types).
        This adapter translates in both directions to OpenAI's chat
        completions API:

        - Anthropic ``tool_use`` block in an assistant turn
          → OpenAI ``tool_calls`` field on an assistant message.
        - Anthropic ``tool_result`` block in a user turn
          → OpenAI ``role: 'tool'`` message with ``tool_call_id``.

        And inversely on response. The route layer never sees
        OpenAI-specific shapes.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_openai_messages(messages))

        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

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
        first = choices[0]
        msg = first.get("message", {})
        finish = first.get("finish_reason", "stop")

        # Build Anthropic-shaped content blocks.
        blocks: list[dict] = []
        text = msg.get("content")
        if text:
            blocks.append({"type": "text", "text": str(text).strip()})

        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            try:
                inp = json.loads(fn.get("arguments", "{}"))
            except Exception:
                inp = {}
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id", "tc_unknown"),
                "name": fn.get("name", ""),
                "input": inp,
            })

        # Map finish_reason to our internal stop_reason vocabulary.
        stop_reason = {
            "tool_calls": "tool_use",
            "length": "max_tokens",
        }.get(finish, "end_turn")

        return {"stop_reason": stop_reason, "content": blocks}


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Translate Anthropic-style messages to OpenAI shape."""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            # Content is a list of blocks. user-side blocks are
            # either text or tool_result (model returning a tool's
            # output to the next turn).
            tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if tool_results:
                # OpenAI uses one role:tool message per tool result.
                for tr in tool_results:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": _stringify(tr.get("content")),
                    })
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
        elif role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue
            # Split text vs tool_use blocks.
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            assistant_msg: dict = {"role": "assistant"}
            assistant_msg["content"] = "\n".join(text_parts) if text_parts else None
            if tool_uses:
                assistant_msg["tool_calls"] = [
                    {
                        "id": b.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": b.get("name", ""),
                            "arguments": json.dumps(b.get("input", {})),
                        },
                    }
                    for b in tool_uses
                ]
            out.append(assistant_msg)
    return out


def _stringify(v) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    try:
        return json.dumps(v)
    except Exception:
        return str(v)
