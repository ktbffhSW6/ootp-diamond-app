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
    <main className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          Custom leaderboards
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          Pick a stat + filters, click any column header to re-sort. 32
          stats supported across batting / pitching / Statcast.
        </p>
      </header>

      <Suspense fallback={<div className="text-content-muted">Loading…</div>}>
        <LeaderboardClient
          options={optionsRes.options}
          initial={leaderboardRes}
          initialPaMin={paMin}
        />
      </Suspense>
    </main>
  );
}
