// Player page — bio header + tab nav + Stats tab content.
//
// Server component: fetches player payload + glossary in parallel
// (so column-header tooltips pull from the D15 dictionary). Hands the
// result to the client-side Stats tab for disclosure-row interaction.
//
// Route shape: /player/[id] where [id] is the internal `player_id`
// (BIGINT in the warehouse). Per D16 we picked numeric IDs over
// bbref_id for v1 — bbref-shaped routes can be added later as
// redirects without breaking this URL.

import Link from "next/link";
import { notFound } from "next/navigation";

import { PlayerStatsTab } from "@/components/PlayerStatsTab";
import { getGlossary, getPlayer } from "@/lib/api";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const playerId = Number.parseInt(id, 10);
  if (!Number.isFinite(playerId)) {
    return { title: "Player — Diamond" };
  }
  try {
    const player = await getPlayer(playerId);
    return { title: `${player.bio.full_name} — Diamond` };
  } catch {
    return { title: `Player ${id} — Diamond` };
  }
}

export default async function PlayerPage({ params }: Props) {
  const { id } = await params;
  const playerId = Number.parseInt(id, 10);
  if (!Number.isFinite(playerId)) {
    notFound();
  }

  // Fetch in parallel — glossary supplies column-header tooltips
  // (per D15 maintenance contract: every UI label comes from the
  // dictionary). The cost of the extra fetch is trivial on localhost.
  let player, glossary;
  try {
    [player, glossary] = await Promise.all([
      getPlayer(playerId),
      getGlossary(),
    ]);
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      notFound();
    }
    throw err;
  }

  const { bio } = player;

  return (
    <article className="space-y-6">
      {/* Bio header — mirrors Bref's player-page top strip */}
      <header className="border-b border-border pb-4">
        <p className="text-xs uppercase tracking-wide text-content-muted">
          {bio.position_name}
          {bio.bats_throws && bio.bats_throws !== "?/?" && (
            <span className="ml-2">
              <span className="text-content-muted">·</span> Bats/Throws{" "}
              <span className="font-mono text-content-secondary">
                {bio.bats_throws}
              </span>
            </span>
          )}
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-content-primary">
          {bio.full_name}
          {bio.uniform_number != null && (
            <span className="ml-3 font-mono text-xl font-normal text-content-muted">
              #{bio.uniform_number}
            </span>
          )}
        </h1>
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-content-secondary">
          {bio.current_team && (
            <div>
              <dt className="inline text-content-muted">Team:</dt>{" "}
              <dd className="inline">
                <span className="font-mono text-content-primary">
                  {bio.current_team.abbr}
                </span>{" "}
                <span className="text-content-muted">
                  ({bio.current_team.level_name ?? "—"})
                </span>
              </dd>
            </div>
          )}
          {bio.age != null && (
            <div>
              <dt className="inline text-content-muted">Age:</dt>{" "}
              <dd className="inline font-mono text-content-primary">
                {bio.age}
              </dd>
            </div>
          )}
          {bio.bbref_id && (
            <div>
              <dt className="inline text-content-muted">Bref ID:</dt>{" "}
              <dd className="inline font-mono text-content-primary">
                {bio.bbref_id}
              </dd>
            </div>
          )}
          {bio.retired && (
            <div className="rounded bg-surface-elevated px-2 text-xs text-content-secondary">
              Retired
            </div>
          )}
          {bio.free_agent && !bio.retired && (
            <div className="rounded bg-amber-50 px-2 text-xs text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
              Free Agent
            </div>
          )}
          {bio.hall_of_fame && (
            <div className="rounded bg-amber-100 px-2 text-xs font-semibold text-amber-800 dark:bg-amber-900/60 dark:text-amber-200">
              ★ Hall of Fame
            </div>
          )}
        </dl>
      </header>

      {/* Tab strip — only Stats is wired in v1; others are placeholders.
          Sticky-position lands when we add scrollable per-tab content. */}
      <nav className="flex gap-1 border-b border-border text-sm">
        <span className="border-b-2 border-content-primary px-3 py-1.5 font-semibold text-content-primary">
          Stats
        </span>
        {["Charts", "Game log", "Comparisons", "Scouting", "Contract"].map(
          (label) => (
            <span
              key={label}
              className="cursor-not-allowed px-3 py-1.5 text-content-muted"
              title="Coming soon"
            >
              {label}
            </span>
          ),
        )}
      </nav>

      <PlayerStatsTab player={player} glossary={glossary} />

      <p className="pt-4 text-xs text-content-muted">
        <Link href="/" className="hover:text-content-primary">
          ← Diamond
        </Link>
      </p>
    </article>
  );
}
