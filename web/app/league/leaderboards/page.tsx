// Custom leaderboards — Fangraphs-style sortable / filterable.
//
// URL state drives the picker:
//   ?stat=HR&year=2029&level=1&pa_min=100
//
// Server pre-fetches the supported-stats list + the initial
// leaderboard for the requested (or default) selection. The client
// component then handles the picker UI, client-side TanStack Table
// sort, and re-fetch on filter change.

import { Suspense } from "react";

import { LeaderboardClient } from "@/components/LeaderboardClient";
import { getLeaderboard, getLeaderboardOptions } from "@/lib/api";

export const metadata = { title: "Leaderboards — Diamond" };
export const dynamic = "force-dynamic";

type SearchParams = {
  stat?: string;
  year?: string;
  level?: string;
  league?: string;
  pa_min?: string;
};

export default async function LeaderboardsPage(
  props: { searchParams: Promise<SearchParams> },
) {
  const sp = await props.searchParams;

  // Default to bWAR if no stat given — most "interesting" single number
  // a fan would pick when landing on the page cold.
  const stat = sp.stat ?? "bWAR";
  const year = sp.year ? Number(sp.year) : undefined;
  const levelId = sp.level ? Number(sp.level) : 1;
  const leagueId = sp.league ? Number(sp.league) : undefined;
  const paMin = sp.pa_min ? Number(sp.pa_min) : undefined;

  // Both fetches in parallel — options is a small static lookup, the
  // leaderboard is the heavy SQL.
  const [optionsRes, leaderboardRes] = await Promise.all([
    getLeaderboardOptions(),
    getLeaderboard({ stat, year, levelId, leagueId, paMin, limit: 100 }),
  ]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            League · Leaderboards
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            {leaderboardRes.stat.label}
            <span className="ml-2 text-sm font-normal text-content-secondary">
              · {leaderboardRes.year ?? "latest"}
            </span>
          </h1>
        </div>
        <p className="text-xs text-content-muted">
          32 stats · click any column header to re-sort
        </p>
      </header>

      <Suspense fallback={<div className="text-content-muted">Loading…</div>}>
        <LeaderboardClient
          options={optionsRes.options}
          initial={leaderboardRes}
          initialPaMin={paMin}
        />
      </Suspense>
    </div>
  );
}
