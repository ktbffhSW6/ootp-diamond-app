// Explore view — sandbox / chart workshop. Bring the question, the
// view brings the primitives. Stub.

import { TabStub } from "@/components/TabStub";

export const metadata = { title: "Explore — Diamond" };
export const dynamic = "force-dynamic";

export default function ExplorePage() {
  return (
    <TabStub
      title="Explore"
      blurb="Sandbox for max-the-data analysis. Compare any players, build any chart, slice the league however you want. The Bloomberg-terminal layer of the app — UI_DESIGN.md §6."
      sections={[
        {
          title: "Compare",
          status: "live",
          href: "/explore/compare",
          blurb:
            "Pick up to 4 players via ?ids=. Side-by-side career stat blocks + overlaid WAR sparklines. Cross-era is fair game — D20 baselines mean Bonds 2001 / Trout 2018 / Skubal 2029 all carry full advanced numbers.",
        },
        {
          title: "Custom leaderboards",
          status: "soon",
          blurb:
            "Fangraphs-style sortable + filterable. Filter strip across year / level / age / min-PA / position / scope; columns drawn from the data dictionary; save-to-URL.",
        },
        {
          title: "Distributions",
          status: "soon",
          blurb:
            "Histogram of any stat across any cohort. “What does the wRC+ distribution at AAA look like” in one click.",
        },
        {
          title: "Spray charts",
          status: "soon",
          blurb:
            "Savant-style field overlay from at-bat events (hit_xy / hit_loc). Filter by handedness, count, zone.",
        },
        {
          title: "EV / LA scatter",
          status: "soon",
          blurb:
            "Exit velocity × launch angle scatter with barrel-zone overlay. Pull in any player or cohort.",
        },
        {
          title: "Chart builder",
          status: "soon",
          blurb:
            "Generic Vega-Lite spec authoring — X / Y / color / size / facet pickers from the data dictionary. Saved gallery, export-to-JSON.",
        },
        {
          title: "Cohorts",
          status: "soon",
          blurb:
            "First-class saved sets with set ops (∪ / ∩ / −). “Farm system MINUS guys I'd never trade INTERSECT age ≤ 24” = trade-bait shortlist.",
        },
      ]}
    />
  );
}
