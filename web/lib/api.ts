// Typed fetch helpers for the Diamond FastAPI backend.
//
// Per D16: the API URL is read from NEXT_PUBLIC_API_URL with a sane
// localhost default. Server components fetching at request time hit
// this URL directly — no client-side proxy needed.
//
// Conventions:
// - One typed helper per endpoint; throw on non-2xx so server
//   components surface errors as Next.js error boundaries.
// - Server-component fetches use Next's default cache behavior;
//   when we hit endpoints that need fresh data, pass
//   `{ cache: 'no-store' }` per call — don't disable caching globally.
// - All response types are imported from `lib/types/api.ts`, which
//   is auto-generated from the Pydantic schemas (see that file).

import type {
  GlossaryEntry,
  GlossaryListResponse,
  HealthResponse,
  PlayerResponse,
} from "@/lib/types/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `API ${res.status} ${res.statusText} on ${path}: ${body.slice(0, 200)}`,
    );
  }
  return (await res.json()) as T;
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/api/health");
}

export async function getGlossary(): Promise<GlossaryListResponse> {
  return fetchJson<GlossaryListResponse>("/api/glossary");
}

export async function getGlossaryEntry(
  id: string,
): Promise<GlossaryEntry> {
  return fetchJson<GlossaryEntry>(
    `/api/glossary/${encodeURIComponent(id)}`,
  );
}

// Player page payload — bio + per-season batting/pitching + career totals.
// 404 surfaces as a thrown Error containing "404"; the page handler
// converts that to Next.js notFound().
export async function getPlayer(playerId: number): Promise<PlayerResponse> {
  return fetchJson<PlayerResponse>(`/api/players/${playerId}`);
}
