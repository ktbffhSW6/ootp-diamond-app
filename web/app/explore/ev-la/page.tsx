// EV-LA scatter — exit velocity × launch angle, colored by outcome.
//
// URL: /explore/ev-la?player=<id>&year=<n>
//
// Sweet-spot zone (LA 8-32°) and barrel zone (EV ≥ 93, LA 22-38°)
// overlay the scatter for context. EV scale is OOTP-native, ~5 mph
// below real Statcast — the zones are calibrated for OOTP's range.

import Link from "next/link";

import { EvLaScatter } from "@/components/EvLaScatter";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { getBattedBalls } from "@/lib/api";

export const metadata = { title: "EV / LA scatter — Diamond" };
export const dynamic = "force-dynamic";

type SearchParams = { player?: string; year?: string };

const DEMOS = [
  { name: "Aaron Judge", id: 33526, year: 2029 },
  { name: "Rafael Devers", id: 34393, year: 2029 },
  { name: "Gunnar Henderson", id: 26166, year: 2029 },
];

export default async function EvLaPage(
  props: { searchParams: Promise<SearchParams> },
) {
  const sp = await props.searchParams;
  const playerId = sp.player ? Number(sp.player) : NaN;
  const year = sp.year ? Number(sp.year) : undefined;

  if (!Number.isFinite(playerId)) {
    return <EmptyState />;
  }

  const bb = await getBattedBalls({ playerId, year, levelId: 1 });

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
            Sweet-spot band (blue) = LA 8–32°. Barrel zone (orange) =
            EV ≥ 93 mph + LA 22–38° (OOTP-calibrated, real Statcast
            uses ≥ 98 mph).
          </p>
        </div>
      </header>

      <EvLaScatter rows={bb.rows} />

      <p className="mt-6 text-xs text-content-muted">
        OOTP&apos;s EV scale runs ~5 mph below real Statcast (league
        average ~83 vs real ~88). The barrel zone EV floor is shifted
        accordingly. Sweet-spot definition is launch-angle-only and
        translates 1:1 from real Statcast.
      </p>
    </main>
  );
}

function EmptyState() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-2xl font-bold text-content-primary">
        EV / LA scatter
      </h1>
      <p className="mt-2 text-sm text-content-secondary">
        Exit velocity × launch angle for every BIP. Pick a player.
      </p>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {DEMOS.map((d) => (
          <Link
            key={d.id}
            href={`/explore/ev-la?player=${d.id}&year=${d.year}`}
            className="rounded-lg border border-border bg-surface-card p-4 hover:border-border-strong"
          >
            <div className="font-semibold text-content-primary">{d.name}</div>
            <div className="text-xs text-content-muted">
              {d.year} MLB · /explore/ev-la?player={d.id}&amp;year={d.year}
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
