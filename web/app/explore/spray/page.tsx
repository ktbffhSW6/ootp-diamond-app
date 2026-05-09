// Spray-chart view — batter-relative hit distribution by spray angle.
//
// URL: /explore/spray?player=<id>&year=<n>
//
// Empty state offers three demo deep-links so a fresh visitor sees
// what the page looks like without having to know an ID.

import Link from "next/link";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SprayChart } from "@/components/SprayChart";
import { getBattedBalls, getPlayer } from "@/lib/api";

export const metadata = { title: "Spray chart — Diamond" };
export const dynamic = "force-dynamic";

type SearchParams = { player?: string; year?: string };

const DEMOS = [
  { name: "Rafael Devers", id: 34393, year: 2029 },
  { name: "Aaron Judge", id: 33526, year: 2029 },
  { name: "Gunnar Henderson", id: 26166, year: 2029 },
];

export default async function SprayPage(
  props: { searchParams: Promise<SearchParams> },
) {
  const sp = await props.searchParams;
  const playerId = sp.player ? Number(sp.player) : NaN;
  const year = sp.year ? Number(sp.year) : undefined;

  if (!Number.isFinite(playerId)) {
    return <EmptyState />;
  }

  const [bb, player] = await Promise.all([
    getBattedBalls({ playerId, year, levelId: 1 }),
    getPlayer(playerId).catch(() => null),
  ]);

  // bats: 1=R, 2=L, 3=S per src/diamond/api/routes/players.py
  const handedness: "L" | "R" | "S" =
    player?.bio.bats === 2 ? "L" : player?.bio.bats === 3 ? "S" : "R";

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-center gap-4">
        <PlayerAvatar
          playerId={playerId}
          displayName={bb.player_name}
          size="md"
        />
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            <Link
              href={`/player/${playerId}`}
              className="text-link hover:text-link-hover"
            >
              {bb.player_name}
            </Link>
            <span className="ml-2 text-content-muted">
              · {bb.year} · {bb.bip_count} BIP
            </span>
          </h1>
          <p className="text-sm text-content-secondary">
            Spray angle (batter-relative). Bats: {handedness}. Outs muted,
            hits saturated, HR loud.
          </p>
        </div>
      </header>

      {bb.bip_count === 0 ? (
        <div className="rounded-lg border border-border bg-surface-card p-8 text-center text-content-muted">
          No batted-ball data for this player at MLB in {bb.year || "any year"}.
          Try a different year or player.
        </div>
      ) : (
        <SprayChart rows={bb.rows} handedness={handedness} />
      )}

      <p className="mt-6 text-xs text-content-muted">
        Method: OOTP encodes spray as a 1D `hit_xy` integer. We bin events
        into 12 wedges across the 0-130 in-arc range and stack each
        wedge's outcomes (out → hit → HR) by count. Distance dimension
        isn&apos;t available in the dump, so the radius shows BIP volume,
        not hit distance.
      </p>
    </main>
  );
}

function EmptyState() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-2xl font-bold text-content-primary">Spray chart</h1>
      <p className="mt-2 text-sm text-content-secondary">
        Batter-relative hit distribution. Pick a player to see where their
        balls in play go.
      </p>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {DEMOS.map((d) => (
          <Link
            key={d.id}
            href={`/explore/spray?player=${d.id}&year=${d.year}`}
            className="rounded-lg border border-border bg-surface-card p-4 hover:border-border-strong"
          >
            <div className="font-semibold text-content-primary">{d.name}</div>
            <div className="text-xs text-content-muted">
              {d.year} MLB · /explore/spray?player={d.id}&amp;year={d.year}
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
