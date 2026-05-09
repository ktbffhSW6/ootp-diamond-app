// History · Awards — career trophy-case leaderboards.
//
// Drains the second /history stub. Backed by `GET /api/awards?
// league_id=&award_id=&era=` — career-rollup of every (player ×
// league × award) combination from save data + cross-source merged
// real-life awards (Lahman + MLB Stats API dedup'd via Chadwick
// Register).
//
// Server component; pickers are <Link> grids (no client state).
// Names link to /player/<id> when the row carries a save player_id;
// otherwise plain text (real-life player not in the save).
//
// Defaults: league=MLB (203), award=MVP (5), era=all, limit=25.
// Bad query strings fall back to defaults rather than 404'ing.

import Link from "next/link";

import { getAwards } from "@/lib/api";
import type {
  AwardCategoryRef,
  AwardHolderRow,
  AwardLeagueRef,
  AwardsResponse,
} from "@/lib/types/api";

export const metadata = { title: "Awards — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Source chip — same color convention as /history/records but only
// two sources (save + merged) actually appear in awards data.
// ─────────────────────────────────────────────────────────────────────

const SOURCE_LABEL: Record<string, string> = {
  save: "Save",
  merged: "Real",
};

const SOURCE_TOOLTIP: Record<string, string> = {
  save:
    "Your OOTP save universe — includes OOTP-imported real-history awards (Bonds 7 MVPs, Maddux 18 GG, etc.).",
  merged:
    "Cross-source real-life rollup — Lahman + MLB Stats API + BREF dedup'd to bbref_id via Chadwick Register, scoped to retired players whose bbref_ids aren't in the save (Yadier Molina 9 GG, R.A. Dickey 1 Cy, etc.).",
};

function SourceChip({ source }: { source: string }) {
  const label = SOURCE_LABEL[source] ?? source;
  const tooltip = SOURCE_TOOLTIP[source] ?? "";
  const cls =
    source === "save"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
      : source === "merged"
        ? "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300"
        : "bg-surface-elevated text-content-muted";
  return (
    <span
      title={tooltip}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls}`}
    >
      {label}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────
// League picker — group available leagues by tier so MLB sits at top.
// Mirrors /league's LEVEL_HEADER convention.
// ─────────────────────────────────────────────────────────────────────

const LEVEL_HEADER: Record<number, string> = {
  1: "MLB",
  2: "AAA",
  3: "AA",
  4: "A+ / A",
  6: "Rk / DSL",
  7: "Indy",
};

function groupLeaguesByLevel(
  leagues: AwardLeagueRef[],
): { level: number; header: string; entries: AwardLeagueRef[] }[] {
  const byLevel = new Map<number, AwardLeagueRef[]>();
  for (const lg of leagues) {
    const arr = byLevel.get(lg.league_level) ?? [];
    arr.push(lg);
    byLevel.set(lg.league_level, arr);
  }
  return [...byLevel.entries()]
    .sort(([a], [b]) => a - b)
    .map(([level, entries]) => ({
      level,
      header: LEVEL_HEADER[level] ?? `Lvl ${level}`,
      entries,
    }));
}

// ─────────────────────────────────────────────────────────────────────
// URL builder + picker pill row (shared with records — could lift to
// a component later; one extra props sig wasn't worth a shared module
// for v1).
// ─────────────────────────────────────────────────────────────────────

function buildHref(args: {
  leagueId: number;
  awardId: number;
  era: string;
}): string {
  const params = new URLSearchParams({
    league_id: String(args.leagueId),
    award_id: String(args.awardId),
    era: args.era,
  });
  return `/history/awards?${params.toString()}`;
}

function LeaguePicker({
  available,
  current,
  awardId,
  era,
}: {
  available: AwardLeagueRef[];
  current: number;
  awardId: number;
  era: string;
}) {
  const groups = groupLeaguesByLevel(available);
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        League
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {groups.map((g) => (
          <div key={g.level} className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-content-muted">
              {g.header}
            </span>
            {g.entries.map((lg) => {
              const active = lg.league_id === current;
              return (
                <Link
                  key={lg.league_id}
                  href={buildHref({
                    leagueId: lg.league_id,
                    awardId,
                    era,
                  })}
                  title={lg.name ?? lg.abbr ?? ""}
                  className={
                    active
                      ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                      : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
                  }
                >
                  {lg.abbr ?? lg.league_id}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function AwardPicker({
  available,
  current,
  leagueId,
  era,
}: {
  available: AwardCategoryRef[];
  current: number;
  leagueId: number;
  era: string;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Award
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {available.map((a) => {
          const active = a.award_id === current;
          return (
            <Link
              key={a.award_id}
              href={buildHref({
                leagueId,
                awardId: a.award_id,
                era,
              })}
              title={a.label}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {a.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

const ERA_OPTIONS = ["all", "save", "real"] as const;
const ERA_LABEL: Record<string, string> = {
  all: "All",
  save: "Save",
  real: "Real",
};
const ERA_TOOLTIP: Record<string, string> = {
  all: "Merge save + real-life rollups.",
  save: "Records from your OOTP save universe only.",
  real: "Cross-source real-life rollups (retired players not in the save).",
};

function EraPicker({
  current,
  leagueId,
  awardId,
  visibleEras,
}: {
  current: string;
  leagueId: number;
  awardId: number;
  visibleEras: readonly string[];
}) {
  if (visibleEras.length <= 1) return null;
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Era
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {visibleEras.map((e) => {
          const active = e === current;
          return (
            <Link
              key={e}
              href={buildHref({ leagueId, awardId, era: e })}
              title={ERA_TOOLTIP[e]}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {ERA_LABEL[e] ?? e}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Trophy table
// ─────────────────────────────────────────────────────────────────────

function fmtYears(first: number | null, last: number | null): string {
  if (first === null && last === null) return "—";
  if (first === null) return `?–${last}`;
  if (last === null) return `${first}–?`;
  if (first === last) return String(first);
  return `${first}–${last}`;
}

function fmtTeams(first: string | null, last: string | null): string {
  if (!first && !last) return "—";
  if (first && last && first === last) return first;
  if (first && last) return `${first} → ${last}`;
  return last ?? first ?? "—";
}

function TrophyTable({ rows }: { rows: AwardHolderRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
        No award holders for this combination of league × award × era. Try
        a different era filter (<span className="font-mono">all</span> usually
        has the broadest coverage) or pick a different award.
      </p>
    );
  }
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Rank by trophy count (ties broken by recency)"
            >
              #
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Player</th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Career wins of this award in this league"
            >
              Won
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="First and last winning seasons"
            >
              Years
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Team at first win → team at last win"
            >
              Team
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const linkable = row.player_id !== null;
            const nameCell = linkable ? (
              <Link
                href={`/player/${row.player_id}`}
                className="font-medium text-link hover:text-link-hover hover:underline"
              >
                {row.display_name}
              </Link>
            ) : (
              <span
                className="font-medium text-content-primary"
                title={
                  row.external_id
                    ? `External ID: ${row.external_id}`
                    : undefined
                }
              >
                {row.display_name}
              </span>
            );
            return (
              <tr
                key={`${row.source}-${row.display_name}-${row.first_year ?? "?"}-${row.last_year ?? "?"}`}
                className="border-t border-border hover:bg-surface-elevated"
              >
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-muted">
                  {row.rank}
                </td>
                <td className="px-3 py-1.5 align-middle">{nameCell}</td>
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                  {row.n_won}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-content-secondary">
                  {fmtYears(row.first_year, row.last_year)}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs text-content-muted">
                  {fmtTeams(row.first_team_abbr, row.last_team_abbr)}
                </td>
                <td className="px-3 py-1.5 align-middle">
                  <SourceChip source={row.source} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function AwardsPage({
  searchParams,
}: {
  searchParams: Promise<{
    league_id?: string;
    award_id?: string;
    era?: string;
  }>;
}) {
  const params = await searchParams;
  const data: AwardsResponse = await getAwards({
    leagueId: params.league_id ? Number(params.league_id) : undefined,
    awardId: params.award_id ? Number(params.award_id) : undefined,
    era:
      params.era === "all" || params.era === "save" || params.era === "real"
        ? params.era
        : undefined,
  });

  const activeAward: AwardCategoryRef | undefined =
    data.available_awards.find((a) => a.award_id === data.award_id);
  const awardLabel = activeAward?.label ?? `Award ${data.award_id}`;
  const leagueLabel =
    data.league.name ?? data.league.abbr ?? `League ${data.league.league_id}`;

  // Era filter — hide "real" when no merged data exists for this
  // (league, award), hide "save" when no save data exists. "all"
  // always shows.
  const visibleEras = ERA_OPTIONS.filter((e) => {
    if (!activeAward) return e === "all";
    if (e === "all") return true;
    if (e === "save")
      return activeAward.available_sources.includes("save");
    if (e === "real")
      return activeAward.available_sources.includes("merged");
    return false;
  });

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          History · Awards
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {awardLabel} — {leagueLabel}
        </h1>
        <p className="text-sm text-content-secondary">
          Career holders, ordered by trophy count.
          {data.total_in_source > 0 && (
            <>
              {" "}Showing top {data.rows.length}
              {data.total_in_source > data.rows.length && (
                <span className="text-content-muted">
                  {" "}of {data.total_in_source}
                </span>
              )}
              .
            </>
          )}
          {" "}Era filter:{" "}
          <span className="font-mono text-content-primary">
            {ERA_LABEL[data.era]}
          </span>
          {data.era === "all" && (
            <> — save data + cross-source merged real-life rollups.</>
          )}
          {data.era === "save" && (
            <> — your OOTP save universe only (includes OOTP-imported real-history awards).</>
          )}
          {data.era === "real" && (
            <> — Lahman + MLB Stats API rollups for real-life players not in the save.</>
          )}
        </p>
      </header>

      <div className="space-y-6">
        <div className="flex flex-wrap gap-x-8 gap-y-4">
          <LeaguePicker
            available={data.available_leagues}
            current={data.league.league_id}
            awardId={data.award_id}
            era={data.era}
          />
          <EraPicker
            current={data.era}
            leagueId={data.league.league_id}
            awardId={data.award_id}
            visibleEras={visibleEras}
          />
        </div>
        <AwardPicker
          available={data.available_awards}
          current={data.award_id}
          leagueId={data.league.league_id}
          era={data.era}
        />
      </div>

      <TrophyTable rows={data.rows} />

      {/* Source legend + caveats */}
      <section className="space-y-3 border-t border-border pt-6">
        <h2 className="text-sm font-semibold text-content-secondary">
          Source legend
        </h2>
        <div className="flex flex-wrap gap-3">
          {(["save", "merged"] as const).map((s) => (
            <div key={s} className="flex items-center gap-1.5">
              <SourceChip source={s} />
              <span className="text-xs text-content-secondary">
                {SOURCE_TOOLTIP[s]}
              </span>
            </div>
          ))}
        </div>
        <ul className="mt-2 space-y-1 text-xs text-content-muted">
          <li>
            <strong>OOTP imports real-life award winners</strong> as save data,
            so "Save" rows include canonical historical totals (Bonds 7 MVPs,
            Maddux 18 Gold Gloves, Brooks Robinson 16 GG, etc.). The "Real"
            (merged) source only fires for retired players whose bbref_ids
            aren't matched to OOTP active players — Yadier Molina 9 GG, R.A.
            Dickey 1 Cy, J.D. Drew 1 All-Star, etc.
          </li>
          <li>
            <strong>"top-3"</strong> — for MVP / Cy / RoY, OOTP records the
            top-3 vote-getters as award rows, not just the winner. The
            leaderboard counts include those finalist appearances.
          </li>
          <li>
            <strong>WS Champion roster</strong> counts every player on the
            winning team's 40-man — high-volume rows where a long-tenured
            dynasty player can rack up double-digit titles. Series MVP is
            the per-series award (WC / DS / CS / WS).
          </li>
          <li>
            <strong>Player links</strong> — players with an OOTP{" "}
            <em>player_id</em> link to their player page. Real-life retired
            players who aren't in this save render as plain text.
          </li>
        </ul>
      </section>

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        Per-season race views (e.g. "2029 MVP race") are out of scope here —
        they need an event-grain query against{" "}
        <code className="font-mono">f_award_event</code>. Live in a future
        slice. Per-team / per-franchise rollups are the same story (powered
        by <code className="font-mono">f_award_franchise</code>).
      </p>
    </div>
  );
}
