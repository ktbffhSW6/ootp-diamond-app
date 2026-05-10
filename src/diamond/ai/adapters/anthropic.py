"""Anthropic Messages API adapter.

Thin httpx wrapper over the v1 Messages endpoint. No SDK dep — keeps
the bundle small and the surface portable. We use ``anthropic-version``
header pinned to ``2023-06-01`` (the stable, currently-supported spec).
"""

from __future__ import annotations

import json
from typing import Iterator

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

    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> dict:
        """Multi-turn chat with optional tool use (D33).

        Anthropic's Messages API natively supports the tool-use loop:
        the response's ``stop_reason`` is ``tool_use`` when the model
        wants to call tools, ``end_turn`` when it's done. We pass
        through both fields so the route layer can drive the loop.
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if tools:
            # Anthropic's tool format matches our internal Tool shape
            # exactly (name + description + input_schema).
            body["tools"] = tools

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
        return {
            "stop_reason": data.get("stop_reason", "end_turn"),
            "content": data.get("content", []),
        }

    def chat_stream(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 1500,
    ) -> Iterator[dict]:
        """Streaming chat (D35 Tier C) — Anthropic SSE.

        Anthropic Messages API streaming emits these SSE events
        (https://docs.anthropic.com/en/api/messages-streaming):

          - message_start
          - content_block_start (text or tool_use)
          - content_block_delta (text_delta or input_json_delta)
          - content_block_stop
          - message_delta (final stop_reason + usage)
          - message_stop

        We re-emit a small provider-agnostic stream:
          {"type": "text_delta", "text": "..."}
          {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
          {"type": "done", "stop_reason": "..."}

        Tool-use blocks come as a `content_block_start` (with empty
        input) followed by `input_json_delta` chunks containing the
        partial JSON of the input object. We accumulate those chunks
        per block index and emit one `tool_use` event when the block
        stops.
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
            "stream": True,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        # Per-block accumulators keyed by content block index.
        block_kinds: dict[int, str] = {}      # idx -> "text" | "tool_use"
        block_tool_meta: dict[int, dict] = {} # idx -> {id, name}
        block_tool_input: dict[int, str] = {} # idx -> partial JSON string
        stop_reason = "end_turn"

        try:
            with httpx.Client(timeout=_TIMEOUT) as c:
                with c.stream("POST", _API_URL, headers=headers, json=body) as resp:
                    if resp.status_code != 200:
                        # Read the error body off the stream + raise.
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
                            f"Anthropic {resp.status_code}: {str(err_msg)[:300]}"
                        )

                    event_type = ""
                    for raw in resp.iter_lines():
                        # Anthropic SSE: blank line separates events;
                        # `event: <name>` then `data: <json>` lines.
                        if not raw:
                            event_type = ""
                            continue
                        if raw.startswith("event:"):
                            event_type = raw[len("event:"):].strip()
                            continue
                        if not raw.startswith("data:"):
                            continue
                        data_str = raw[len("data:"):].strip()
                        if not data_str:
                            continue
                        try:
                            payload = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if event_type == "content_block_start":
                            idx = payload.get("index", 0)
                            block = payload.get("content_block", {})
                            kind = block.get("type", "")
                            block_kinds[idx] = kind
                            if kind == "tool_use":
                                block_tool_meta[idx] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                }
                                block_tool_input[idx] = ""
                        elif event_type == "content_block_delta":
                            idx = payload.get("index", 0)
                            delta = payload.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "text_delta":
                                txt = delta.get("text", "")
                                if txt:
                                    yield {"type": "text_delta", "text": txt}
                            elif dtype == "input_json_delta":
                                # Accumulate partial JSON; we emit on
                                # content_block_stop when complete.
                                block_tool_input[idx] = (
                                    block_tool_input.get(idx, "")
                                    + delta.get("partial_json", "")
                                )
                        elif event_type == "content_block_stop":
                            idx = payload.get("index", 0)
                            if block_kinds.get(idx) == "tool_use":
                                meta = block_tool_meta.get(idx, {})
                                raw_input = block_tool_input.get(idx, "")
                                try:
                                    inp = json.loads(raw_input) if raw_input else {}
                                except json.JSONDecodeError:
                                    inp = {}
                                yield {
                                    "type": "tool_use",
                                    "id": meta.get("id", ""),
                                    "name": meta.get("name", ""),
                                    "input": inp,
                                }
                        elif event_type == "message_delta":
                            delta = payload.get("delta", {})
                            sr = delta.get("stop_reason")
                            if sr:
                                stop_reason = sr
                        elif event_type == "message_stop":
                            # Final event — defer the done emit until
                            # we've left the stream context.
                            pass
                        elif event_type == "error":
                            err = payload.get("error", {})
                            msg = err.get("message", "stream error")
                            raise AIClientError(f"Anthropic stream: {msg}")
        except httpx.HTTPError as e:
            raise AIClientError(f"Anthropic network error: {e}") from e

        yield {"type": "done", "stop_reason": stop_reason}
