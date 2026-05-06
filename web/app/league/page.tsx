// League view — scoped leagues (MLB tree + DSL + AFL), current state.
// Stub: lists what's planned, no live content yet.

import { TabStub } from "@/components/TabStub";

export const metadata = { title: "League — Diamond" };
export const dynamic = "force-dynamic";

export default function LeaguePage() {
  return (
    <TabStub
      title="League"
      blurb="Standings, leaderboards, awards races, and free agents across the leagues you scope to (MLB + AAA / AA / A+ / A / Rk / DSL + AFL). Current state — for past seasons, see History."
      sections={[
        {
          title: "Standings",
          status: "soon",
          blurb:
            "All teams across all scoped levels with W-L, run differential, Pythagorean projection.",
        },
        {
          title: "Leaderboards",
          status: "soon",
          blurb:
            "Curated league leaders by stat category. The build-your-own version lives under Explore.",
        },
        {
          title: "Awards races",
          status: "soon",
          blurb:
            "MVP / Cy Young / ROY / GG / SS — current-season frontrunners with stat-citation context.",
        },
        {
          title: "Free agent pool",
          status: "soon",
          blurb:
            "Unsigned players cross-referenced with their last team and recent performance.",
        },
      ]}
    />
  );
}
