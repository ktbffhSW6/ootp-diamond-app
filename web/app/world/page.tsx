// World view — every league in the save, including ones outside the
// scoped tree (international, KBO/NPB, indie ball when present). For
// users who follow all leagues, not just their org's. Stub.

import { TabStub } from "@/components/TabStub";

export const metadata = { title: "World — Diamond" };
export const dynamic = "force-dynamic";

export default function WorldPage() {
  return (
    <TabStub
      title="World"
      blurb="Every league in the save, scoped or not. For users who follow international ball, indie leagues, or just want the cross-league perspective. Most data exists in L0 / L1 already; surfacing it is what's deferred."
      sections={[
        {
          title: "All leagues",
          status: "soon",
          blurb:
            "Browse every league in the save with standings + headline stats. Not currently scoped: KBO / NPB / Cuban Winter / others when OOTP imports them.",
        },
        {
          title: "Cross-league movements",
          status: "soon",
          blurb:
            "Player flow between leagues: international signings, foreign-league call-ups, postings.",
        },
        {
          title: "World rankings",
          status: "soon",
          blurb:
            "Top performers across every league at once, normalized via league-relative metrics where constants exist.",
        },
        {
          title: "International prospects",
          status: "soon",
          blurb:
            "Pre-draft / pre-signing prospect pool with home-league context.",
        },
      ]}
    />
  );
}
