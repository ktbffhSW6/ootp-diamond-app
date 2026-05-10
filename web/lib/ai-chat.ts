// AI sidebar chat client (D33). Separate file from `lib/api.ts` to
// keep the heavyweight client-only fetch logic out of server-component
// import paths.

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
