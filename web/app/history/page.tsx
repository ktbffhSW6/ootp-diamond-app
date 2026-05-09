// History view — past seasons, records, awards, HoF, streaks, draft.
// All five sections shipped 2026-05-12. Now a hub page that links
// through to each retrospective.

import { TabStub } from "@/components/TabStub";

export const metadata = { title: "History — Diamond" };
export const dynamic = "force-dynamic";

export default function HistoryPage() {
  return (
    <TabStub
      title="History"
      blurb="Past seasons through five lenses — all-time records, career trophy cases, the Hall of Fame, streak leaderboards, and per-year draft retrospectives. Save data fused with real MLB history (Lahman 1871-2019, BREF 2020-2025, MLB Stats API for awards / HoF gap-fills, Statcast 2015-2025 for batted-ball quality)."
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
          status: "live",
          href: "/history/awards",
          blurb:
            "Career trophy-case leaderboards — MVP / Cy Young / ROY / Gold Glove / Silver Slugger / Reliever / All-Star / WS Champion / Series MVP. Save data + cross-source merged real-life awards (Lahman + MLB Stats API).",
        },
        {
          title: "Hall of Fame",
          status: "live",
          href: "/history/hof",
          blurb:
            "Cooperstown roster (inductees) + top-WAR non-inducted candidates. OOTP imports the real Hall plus in-save voted-in classes.",
        },
        {
          title: "Streaks",
          status: "live",
          href: "/history/streaks",
          blurb:
            "Top-50 holders for 21 streak types — Hitting / Scoreless Innings / On-Base / Win / etc. Active vs all-time scopes.",
        },
        {
          title: "Past draft classes",
          status: "live",
          href: "/history/draft",
          blurb:
            "Per-year retrospectives bucketed by outcome (MLB Regular / Callup / Still Developing / Traded / Released / Retired). 2026 class — Cholowsky 1.1, Skelton Sox 4th-round 3.6 WAR find.",
        },
      ]}
    />
  );
}
