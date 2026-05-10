"""OpenAI Chat Completions API adapter.

Thin httpx wrapper. No SDK dep — keeps the bundle small. Uses the v1
Chat Completions endpoint (broadly supported across compatible
backends — Azure OpenAI, OpenRouter, vLLM all expose this shape).
"""

from __future__ import annotations

import json
from typing import Iterator

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

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> Iterator[dict]:
        """Streaming chat (D35 Tier C) — OpenAI SSE.

        OpenAI's streaming Chat Completions emits ``data: {...}\\n\\n``
        SSE chunks with one ``choices[0].delta`` per chunk. The delta
        carries either incremental content (text) or tool_calls
        (with function.arguments accumulating piece by piece per
        ``index``). We re-emit the same provider-agnostic event
        stream as the Anthropic adapter:

            {"type": "text_delta", "text": "..."}
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
            {"type": "done", "stop_reason": "..."}
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_openai_messages(messages))

        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
            "stream": True,
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

        # tool_calls accumulator keyed by `index` (OpenAI streams
        # tool calls in pieces, identifying them only by index).
        tool_acc: dict[int, dict] = {}
        finish_reason = "stop"

        try:
            with httpx.Client(timeout=_TIMEOUT) as c:
                with c.stream("POST", _API_URL, headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        try:
                            err_bytes = resp.read()
                            err_text = err_bytes.decode("utf-8", "replace")
                        except Exception:
                            err_text = ""
                        try:
                            err_msg = json.loads(err_text).get("error", {}).get("message", err_text)
                        except Exception:
                            err_msg = err_text
                        raise AIClientError(
                            f"OpenAI {resp.status_code}: {str(err_msg)[:300]}"
                        )

                    for raw in resp.iter_lines():
                        if not raw or not raw.startswith("data:"):
                            continue
                        data_str = raw[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            payload = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        ch = choices[0]
                        delta = ch.get("delta") or {}
                        fr = ch.get("finish_reason")
                        if fr:
                            finish_reason = fr
                        # text delta
                        text_chunk = delta.get("content")
                        if text_chunk:
                            yield {"type": "text_delta", "text": text_chunk}
                        # tool_calls delta — OpenAI streams them in pieces
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = tool_acc.setdefault(
                                idx,
                                {"id": "", "name": "", "args": ""},
                            )
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            args_chunk = fn.get("arguments") or ""
                            if args_chunk:
                                slot["args"] += args_chunk
        except httpx.HTTPError as e:
            raise AIClientError(f"OpenAI network error: {e}") from e

        # Emit assembled tool_use events after the stream closes.
        for idx in sorted(tool_acc.keys()):
            slot = tool_acc[idx]
            try:
                inp = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                inp = {}
            yield {
                "type": "tool_use",
                "id": slot["id"] or f"tc_{idx}",
                "name": slot["name"],
                "input": inp,
            }

        stop_reason = {
            "tool_calls": "tool_use",
            "length": "max_tokens",
        }.get(finish_reason, "end_turn")
        yield {"type": "done", "stop_reason": stop_reason}


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
