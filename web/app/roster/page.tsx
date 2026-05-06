// Roster page — full org-tree player list, the entry point for the
// player page (closes the navigation loop).
//
// Server component shape: fetch the full payload server-side (one
// API round-trip on first load), then hand off to <RosterClient> for
// all interactive filtering / sorting / mode-toggling. The client
// component owns state because URL-driven filters would re-fetch on
// every pill click and the data is small enough to make that overkill.
//
// Per the data-fetching-page rule (docs/DEV.md): `force-dynamic` so
// `next build` doesn't try to prerender against a non-running uvicorn.

import { getRoster } from "@/lib/api";

import RosterClient from "@/components/RosterClient";

export const metadata = {
  title: "Roster — Diamond",
};

export const dynamic = "force-dynamic";

export default async function RosterPage() {
  const data = await getRoster();

  const orgLabel = data.org_team_nickname
    ? `${data.org_team_abbr ?? ""} ${data.org_team_nickname}`.trim()
    : (data.org_team_abbr ?? `Team ${data.org_team_id}`);

  const totalPlayers = data.groups.reduce(
    (acc, g) => acc + g.position_players.length + g.pitchers.length,
    0,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          Roster
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-content-secondary">
          Every active player in the{" "}
          <span className="font-medium text-content-primary">{orgLabel}</span>{" "}
          org tree, grouped by their current level. Stats are{" "}
          {data.season} totals at each player&apos;s current level — bouncing
          between levels won&apos;t conflate the numbers here. Click a name
          for the full player page (cross-level history, fielding,
          stints).
        </p>
        <p className="mt-1 text-xs text-content-muted">
          {totalPlayers} player{totalPlayers === 1 ? "" : "s"} loaded across{" "}
          {data.groups.length} level{data.groups.length === 1 ? "" : "s"}.
        </p>
      </div>

      <RosterClient data={data} />

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        v1 caveats: stats reflect the player&apos;s current level only —
        a guy who was AAA most of the year and got a September call-up
        shows just the cup-of-coffee MLB line here. The player page has
        the full per-stint breakdown. Two-way players are filed by
        primary position. OVR is the user-org scouted value (20-80 scale).
        Levels with no players (DSL etc.) don&apos;t render a section.
      </p>
    </div>
  );
}
