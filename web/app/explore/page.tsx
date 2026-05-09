// Explore — Chart Builder.
//
// Per the 2026-05-13 IA shuffle, /explore is no longer a hub-of-tools
// landing page. Per-player charts (spray, EV-LA) live inline on the
// player page; league-wide tools (leaderboards, compare) moved under
// /league. /explore is now JUST the build-any-chart workshop —
// pick X, pick Y, filter, see the scatter (or histogram if Y is
// omitted).
//
// URL state drives the picker so deep-links and the back button work:
//   ?x=wRC_plus&y=bWAR&year=2029&level=1
//
// Server pre-fetches the supported-stats list + the initial dataset
// for the requested (or default) selection. ChartBuilderClient owns
// the picker UI + Plot rendering.

import { ChartBuilderClient } from "@/components/ChartBuilderClient";
import { getChartBuilder, getLeaderboardOptions } from "@/lib/api";

export const metadata = { title: "Chart Builder — Diamond" };
export const dynamic = "force-dynamic";

type SearchParams = {
  x?: string;
  y?: string;
  color?: string;
  year?: string;
  level?: string;
  qualifier_min?: string;
};

export default async function ExplorePage(
  props: { searchParams: Promise<SearchParams> },
) {
  const sp = await props.searchParams;

  // Defaults: a "show me something interesting" landing — wRC+ vs bWAR
  // is the canonical "production vs value" scatter and looks great
  // cold. The user can swap in any pair from the picker.
  const x = sp.x ?? "wRC_plus";
  const y = sp.y ?? "bWAR";
  const color = sp.color || undefined;
  const year = sp.year ? Number(sp.year) : undefined;
  const levelId = sp.level ? Number(sp.level) : 1;
  const qualifierMin = sp.qualifier_min ? Number(sp.qualifier_min) : undefined;

  const [optionsRes, dataRes] = await Promise.all([
    getLeaderboardOptions(),
    getChartBuilder({
      x,
      y,
      color,
      year,
      levelId,
      qualifierMin,
      limit: 500,
    }),
  ]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Explore
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            Chart Builder
          </h1>
        </div>
        <p className="text-xs text-content-muted">
          Cross-table picker · per-player on the{" "}
          <a className="text-link hover:text-link-hover" href="/roster">player page</a>
          {" "}· league-wide on{" "}
          <a className="text-link hover:text-link-hover" href="/league/leaderboards">
            Leaderboards
          </a>{" / "}
          <a className="text-link hover:text-link-hover" href="/league/compare">
            Compare
          </a>
        </p>
      </header>

      <ChartBuilderClient
        options={optionsRes.options}
        initial={dataRes}
        initialQualifierMin={qualifierMin}
      />
    </div>
  );
}
