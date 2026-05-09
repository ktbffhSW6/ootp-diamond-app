// History view — past seasons, records, awards, HoF. Most of this
// already exists as CLI commands (`diamond records / awards / hof /
// streaks`); porting them into web views is the v1 content. Stub.

import { TabStub } from "@/components/TabStub";

export const metadata = { title: "History — Diamond" };
export const dynamic = "force-dynamic";

export default function HistoryPage() {
  return (
    <TabStub
      title="History"
      blurb="Past seasons, records, awards, Hall of Fame. The CLI surfaces (`diamond records`, `diamond awards`, `diamond hof`, `diamond streaks`) all already exist — porting them into web views is the v1 content here."
      sections={[
        {
          title: "Records",
          status: "live",
          href: "/history/records",
          blurb:
            "All-time leaderboards (single-season + career, batting + pitching + Statcast). Save data + Lahman 1871-2019 + BREF 2020-2025 + cross-source merged career rollups.",
        },
        {
          title: "Awards history",
          status: "soon",
          blurb:
            "Every MVP / Cy Young / ROY / GG / SS in the save, sortable + filterable.",
        },
        {
          title: "Hall of Fame",
          status: "soon",
          blurb:
            "Inducted players with career-arc summaries. Cross-era comparisons live under Explore.",
        },
        {
          title: "Streaks",
          status: "soon",
          blurb:
            "Hitting streaks, scoreless-inning streaks, scored-in-every-game streaks. Decoded streak history with leaderboards.",
        },
        {
          title: "Past draft classes",
          status: "soon",
          blurb:
            "Each draft class with retrospectives — who hit, who busted, who's still developing.",
        },
      ]}
    />
  );
}
