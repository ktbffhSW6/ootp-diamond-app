// AI sidebar chat client (D33 → D35).
//
// Two transports:
//
//   - sendChat(req): synchronous round-trip. Used as a fallback and
//     exposed for tests / non-streaming callers. Returns the full
//     ChatResponse all at once.
//
//   - streamChat(req, handlers): SSE streaming (D35 Tier C). Calls
//     POST /api/ai/chat/stream and dispatches incremental events to
//     the supplied handlers. The frontend appends text deltas into
//     the in-progress assistant turn so the user sees the model
//     write in real time.
//
// SSE frame shape (matches src/diamond/api/routes/ai.py):
//
//   event: text_delta\ndata: {"text": "..."}\n\n
//   event: tool_use\ndata: {"id": "...", "name": "...", "input": {...}}\n\n
//   event: tool_result\ndata: {"tool_use_id": "...", "content": ..., "is_error": false}\n\n
//   event: iteration\ndata: {"n": 2}\n\n
//   event: error\ndata: {"detail": "..."}\n\n
//   event: done\ndata: {"stop_reason": "end_turn"}\n\n

import type { ChatRequest, ChatResponse } from "@/lib/types/api";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/api/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j?.detail ?? "";
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(
      `Chat API ${res.status}: ${detail || res.statusText}`,
    );
  }
  return (await res.json()) as ChatResponse;
}

// ────────────────────────────────────────────────────────────────────
// Streaming
// ────────────────────────────────────────────────────────────────────

export type StreamEvent =
  | { type: "text_delta"; text: string }
  | {
      type: "tool_use";
      id: string;
      name: string;
      input: Record<string, unknown>;
    }
  | {
      type: "tool_result";
      tool_use_id: string;
      content: unknown;
      is_error: boolean;
    }
  | { type: "iteration"; n: number }
  | { type: "error"; detail: string }
  | { type: "done"; stop_reason: string };

export interface StreamHandlers {
  onEvent: (ev: StreamEvent) => void;
  signal?: AbortSignal;
}

export async function streamChat(
  req: ChatRequest,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/ai/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(req),
    cache: "no-store",
    signal: handlers.signal,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j?.detail ?? "";
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(
      `Chat stream API ${res.status}: ${detail || res.statusText}`,
    );
  }
  if (!res.body) {
    throw new Error("Chat stream API: no response body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  // SSE frames are separated by a blank line. We accumulate into
  // `buffer` and split on \n\n; everything before the last separator
  // is one or more complete frames, the rest stays for the next
  // chunk.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const ev = parseFrame(frame);
      if (ev) handlers.onEvent(ev);
      sep = buffer.indexOf("\n\n");
    }
  }
  // Flush any trailing frame without a final \n\n.
  if (buffer.trim()) {
    const ev = parseFrame(buffer);
    if (ev) handlers.onEvent(ev);
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // Multiple data lines concatenate per SSE spec.
      data += line.slice(5).trim();
    }
  }
  if (!data) return null;
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  switch (event) {
    case "text_delta":
      return { type: "text_delta", text: String(payload.text ?? "") };
    case "tool_use":
      return {
        type: "tool_use",
        id: String(payload.id ?? ""),
        name: String(payload.name ?? ""),
        input: (payload.input as Record<string, unknown>) ?? {},
      };
    case "tool_result":
      return {
        type: "tool_result",
        tool_use_id: String(payload.tool_use_id ?? ""),
        content: payload.content,
        is_error: Boolean(payload.is_error),
      };
    case "iteration":
      return { type: "iteration", n: Number(payload.n ?? 0) };
    case "error":
      return { type: "error", detail: String(payload.detail ?? "Stream error") };
    case "done":
      return {
        type: "done",
        stop_reason: String(payload.stop_reason ?? "end_turn"),
      };
    default:
      return null;
  }
}
