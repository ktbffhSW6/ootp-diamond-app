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
  MovementsResponse,
  PlayerResponse,
  RosterResponse,
  SaveResponse,
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

// Active save metadata — backs the landing-page header.
export async function getSave(): Promise<SaveResponse> {
  return fetchJson<SaveResponse>("/api/save");
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

// Movement-ledger payload for the user-team org for one season.
// `year` is optional — backend defaults to the latest season with
// movements when omitted.
export async function getMovements(
  year?: number,
): Promise<MovementsResponse> {
  const qs = year !== undefined ? `?year=${year}` : "";
  return fetchJson<MovementsResponse>(`/api/movements${qs}`);
}

// Active org-tree roster — every active player grouped by current
// level. The whole payload is one round-trip; client-side filters
// (level pills, role pills, basic/advanced toggle) operate over the
// in-memory result.
export async function getRoster(): Promise<RosterResponse> {
  return fetchJson<RosterResponse>("/api/roster");
}

// Trigger a one-click shutdown of both dev servers (Next.js :3000 and
// FastAPI :8000). Returns immediately; the actual kill happens ~1s
// later in a detached subprocess so this response gets to flush first.
// Windows-only — see `src/diamond/api/routes/admin.py`.
export async function shutdownApp(): Promise<{
  status: string;
  ports: number[];
}> {
  return fetchJson<{ status: string; ports: number[] }>(
    "/api/admin/shutdown",
    { method: "POST" },
  );
}
