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
    <main className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6">
        <p className="text-xs uppercase tracking-wide text-content-muted">
          Explore
        </p>
        <h1 className="text-2xl font-bold text-content-primary">
          Chart Builder
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          Pick X (and optional Y) from the 32-stat catalog; filter by
          year / level / min-qualifier. Cross-table is fair game —
          &quot;Avg EV vs HR&quot; works because every supported stat
          keys on (player, year, league, level).
        </p>
        <p className="mt-2 text-xs text-content-muted">
          Per-player charts (spray, EV / LA) live on the{" "}
          <a className="text-link hover:text-link-hover" href="/roster">
            player page
          </a>
          . League-wide tools live under{" "}
          <a className="text-link hover:text-link-hover" href="/league/leaderboards">
            League → Leaderboards
          </a>{" "}
          and{" "}
          <a className="text-link hover:text-link-hover" href="/league/compare">
            League → Compare
          </a>
          .
        </p>
      </header>

      <ChartBuilderClient
        options={optionsRes.options}
        initial={dataRes}
        initialQualifierMin={qualifierMin}
      />
    </main>
  );
}
