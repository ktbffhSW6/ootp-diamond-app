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
  AwardsResponse,
  CockpitResponse,
  DraftClassResponse,
  GlossaryEntry,
  GlossaryListResponse,
  HealthResponse,
  HofResponse,
  MovementsResponse,
  PlayerResponse,
  PressureResponse,
  RecordsResponse,
  RosterResponse,
  SaveResponse,
  StandingsResponse,
  StreaksResponse,
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

// League standings at one dump_date snapshot. Both args are optional:
// backend defaults to MLB / latest year. Resolution falls back to the
// closest valid value when args don't match available data, so deep-
// linked URLs stay forgiving.
export async function getStandings(
  leagueId?: number,
  year?: number,
): Promise<StandingsResponse> {
  const params: string[] = [];
  if (leagueId !== undefined) params.push(`league_id=${leagueId}`);
  if (year !== undefined) params.push(`year=${year}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<StandingsResponse>(`/api/standings${qs}`);
}

// Records leaderboard payload — top-N rows for one (scope × discipline ×
// category) combination, optionally filtered to a source bucket via
// the `era` arg ("all" | "save" | "real" | "statcast"). All args are
// optional; the backend falls back to sane defaults
// (scope=season, discipline=batting, category=HR, era=all, limit=25)
// and re-ranks rows server-side so the rendered list is the source of
// truth for ordering.
export async function getRecords(args: {
  scope?: "season" | "career";
  discipline?: "batting" | "pitching";
  category?: string;
  era?: "all" | "save" | "real" | "statcast";
  limit?: number;
}): Promise<RecordsResponse> {
  const params: string[] = [];
  if (args.scope) params.push(`scope=${args.scope}`);
  if (args.discipline) params.push(`discipline=${args.discipline}`);
  if (args.category) params.push(`category=${encodeURIComponent(args.category)}`);
  if (args.era) params.push(`era=${args.era}`);
  if (args.limit !== undefined) params.push(`limit=${args.limit}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<RecordsResponse>(`/api/records${qs}`);
}

// Awards leaderboard payload — career trophy holders for one
// (league × award) combo. ``era`` is the orthogonal source filter:
// "all" merges save + merged real-life; "save" is your save universe
// only; "real" is cross-source merged real-life awards (Lahman + MLB
// Stats API dedup'd via Chadwick Register, scoped to bbref_ids NOT
// in the save). All args optional; backend falls back to MLB / MVP /
// all-era / 25-row defaults.
export async function getAwards(args: {
  leagueId?: number;
  awardId?: number;
  era?: "all" | "save" | "real";
  limit?: number;
}): Promise<AwardsResponse> {
  const params: string[] = [];
  if (args.leagueId !== undefined) params.push(`league_id=${args.leagueId}`);
  if (args.awardId !== undefined) params.push(`award_id=${args.awardId}`);
  if (args.era) params.push(`era=${args.era}`);
  if (args.limit !== undefined) params.push(`limit=${args.limit}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<AwardsResponse>(`/api/awards${qs}`);
}

// Hall of Fame payload — either the inductees roster or the
// candidates list (top non-inducted by career WAR). Defaults to
// ``view='inductees'`` (the canonical "who's in?" view); pass
// ``view='candidates'`` for the "who should be next?" board.
// ``inductees_count`` and ``candidates_count`` come back on every
// response so the toggle can show "·N" hints.
export async function getHof(args: {
  view?: "inductees" | "candidates";
  limit?: number;
}): Promise<HofResponse> {
  const params: string[] = [];
  if (args.view) params.push(`view=${args.view}`);
  if (args.limit !== undefined) params.push(`limit=${args.limit}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<HofResponse>(`/api/hof${qs}`);
}

// Streaks leaderboard payload — top-N holders for one (streak_id ×
// scope) combination. Backend defaults to streak_id=0 (HITTING_STREAK)
// + scope=all_time + limit=25. Bad streak_id falls back to default
// rather than 404'ing — deep-linked URLs stay forgiving.
export async function getStreaks(args: {
  streakId?: number;
  scope?: "active" | "all_time";
  limit?: number;
}): Promise<StreaksResponse> {
  const params: string[] = [];
  if (args.streakId !== undefined) params.push(`streak_id=${args.streakId}`);
  if (args.scope) params.push(`scope=${args.scope}`);
  if (args.limit !== undefined) params.push(`limit=${args.limit}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<StreaksResponse>(`/api/streaks${qs}`);
}

// Draft class retrospective — full per-year picks, grouped by
// outcome bucket (mlb_regular | mlb_callup | in_draft_org |
// traded_away | released | retired). Backend defaults to the
// oldest year with material outcome variation (so fresh classes
// don't render as 600 rows of "still developing"). All ~600 picks
// returned in one round-trip following the roster page convention.
export async function getDraft(args: {
  year?: number;
}): Promise<DraftClassResponse> {
  const params: string[] = [];
  if (args.year !== undefined) params.push(`year=${args.year}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<DraftClassResponse>(`/api/draft${qs}`);
}

// Pressure-board payload — per-level promotion candidates +
// pressure cases for the org tree at one year. Backend defaults
// to latest year + 6-per-side. Org scope is implicit (the active
// save's audit_team_id + parent rollup).
export async function getPressure(args: {
  year?: number;
  limit?: number;
}): Promise<PressureResponse> {
  const params: string[] = [];
  if (args.year !== undefined) params.push(`year=${args.year}`);
  if (args.limit !== undefined) params.push(`limit=${args.limit}`);
  const qs = params.length === 0 ? "" : `?${params.join("&")}`;
  return fetchJson<PressureResponse>(`/api/pressure${qs}`);
}

// Cockpit dashboard — composes standings + pressure summary +
// spotlight cards + recent movements into one round-trip payload.
// Always reflects "now" (latest year with data); year-spanning views
// live on /league, /pressure, /movements per their own pickers.
export async function getCockpit(): Promise<CockpitResponse> {
  return fetchJson<CockpitResponse>("/api/cockpit");
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
