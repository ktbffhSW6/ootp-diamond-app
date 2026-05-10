// Explore — two-mode workshop.
//
// 2026-05-15 (D31): added Metabase iframe mode. /explore is now:
//   ?mode=quick      → Diamond's curated ChartBuilder (scatter +
//                      histogram, ~38 stat catalog, fast)
//   ?mode=workshop   → embedded Metabase (full BI tool — every chart
//                      type, drag-and-drop encoding shelves, save +
//                      share dashboards). Live save data via Pattern A
//                      (Metabase's Database #1 follows the active save).
//
// Quick is the default — fast to land, no extra process required.
// Workshop is the power tool. Both run against the same DuckDB
// warehouse, so the data is identical.
//
// Per D16 architecture, the embedded Metabase runs on localhost:3000.
// If it's not running, the workshop tab shows a cold-start guide
// (`metabase.bat /b` from `~/.diamond/metabase/`).

import { ChartBuilderClient } from "@/components/ChartBuilderClient";
import { ExploreModeTabs } from "@/components/ExploreModeTabs";
import { MetabaseWorkshop } from "@/components/MetabaseWorkshop";
import { getChartBuilder, getLeaderboardOptions } from "@/lib/api";

export const metadata = { title: "Chart Builder — Diamond" };
export const dynamic = "force-dynamic";

type SearchParams = {
  mode?: string;
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
  const mode = sp.mode === "workshop" ? "workshop" : "quick";

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Explore
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            {mode === "workshop" ? "Workshop · Metabase" : "Quick chart"}
          </h1>
        </div>
        <p className="text-xs text-content-muted">
          Diamond&apos;s scatter / histogram for fast cohort answers ·{" "}
          Metabase Workshop for full BI · same warehouse, different surfaces
        </p>
      </header>

      <ExploreModeTabs current={mode} />

      {mode === "workshop" ? (
        <MetabaseWorkshop />
      ) : (
        <QuickChart sp={sp} />
      )}
    </div>
  );
}

async function QuickChart({ sp }: { sp: SearchParams }) {
  // Defaults: a "show me something interesting" landing — wRC+ vs bWAR
  // is the canonical "production vs value" scatter and looks great
  // cold. The user can swap in any pair from the picker.
  const x = sp.x ?? "wRC_plus";
  const y = sp.y ?? "bWAR";
  const color = sp.color || undefined;
  const year = sp.year ? Number(sp.year) : undefined;
  const levelId = sp.level ? Number(sp.level) : 1;
  const qualifierMin = sp.qualifier_min
    ? Number(sp.qualifier_min)
    : undefined;

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
    <ChartBuilderClient
      options={optionsRes.options}
      initial={dataRes}
      initialQualifierMin={qualifierMin}
    />
  );
}
