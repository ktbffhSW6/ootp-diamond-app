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

import { CareerArc } from "@/components/CareerArc";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PlayerContractCard } from "@/components/PlayerContractCard";
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

  const { bio, roster_status: rs } = player;

  // Service-class color hint — emerald (FA-eligible / vet) ~ accent-blue
  // (arb-eligible) ~ neutral (pre-arb). Cap the choice list small so the
  // header stays calm.
  const serviceClassClass = !rs
    ? ""
    : rs.is_free_agent_eligible
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
      : rs.service_class.startsWith("arb_")
        ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
        : "bg-surface-elevated text-content-secondary";

  return (
    <article className="space-y-6">
      {/* Bio header — mirrors Bref's player-page top strip */}
      <header className="flex flex-wrap items-start gap-4 border-b border-border pb-4">
        <PlayerAvatar
          playerId={playerId}
          displayName={bio.full_name}
          size="lg"
        />
        <div className="min-w-[200px] flex-1">
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
        </div>
      </header>

      {/* Service & Status — small card under the bio header. Skipped
          for retired / never-rostered players (rs is null). Shows MLB
          service time, arb/FA class, options, and any non-active
          status flags (DL / DFA / waivers). The November snapshot
          tends to have all status flags off (offseason) — they light
          up in mid-season ingests. */}
      {rs && (
        <section className="rounded-md border border-border bg-surface-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <div>
              <span className="text-content-muted">MLB service:</span>{" "}
              <span className="font-mono font-semibold text-content-primary">
                {rs.service_display}
              </span>
              <span className="ml-1 text-xs text-content-muted">
                ({rs.mlb_service_days}d)
              </span>
            </div>
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${serviceClassClass}`}
              title={
                rs.is_free_agent_eligible
                  ? "Player has reached 6.000 years of MLB service — eligible for free agency at end of contract / season."
                  : rs.service_class === "pre_arb"
                    ? "Pre-arbitration: less than 3.000 years of MLB service. Renewable contract; no salary leverage. (Super-Two qualifiers not modeled in v1.)"
                    : "Arbitration-eligible: 3 to 6 years of MLB service. Three arb years before reaching free agency."
              }
            >
              {rs.service_class_label}
            </span>
            {!rs.is_free_agent_eligible && (
              <div>
                <span className="text-content-muted">FA in</span>{" "}
                <span className="font-mono text-content-primary">
                  {rs.days_to_free_agency}d
                </span>
              </div>
            )}
            <div title="Minor-league options used. Players have 3 option years; once exhausted, they can't be sent to MiLB without DFA.">
              <span className="text-content-muted">Options:</span>{" "}
              <span className="font-mono text-content-primary">
                {rs.options_used}/3
              </span>
              {rs.options_used_this_year > 0 && (
                <span className="ml-1 text-xs text-content-muted">
                  (+{rs.options_used_this_year} this season)
                </span>
              )}
            </div>
            {/* Status flags — only render when truthy. Most are zero
                on the offseason November dump; in-season ingests will
                light them up. */}
            <div className="ml-auto flex flex-wrap gap-1.5">
              {rs.is_active && (
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                  Active
                </span>
              )}
              {rs.is_on_secondary && (
                <span
                  className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
                  title="On the 40-man / reserve roster"
                >
                  40-man
                </span>
              )}
              {rs.is_on_dl && (
                <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-rose-800 dark:bg-rose-900/40 dark:text-rose-300">
                  10-day IL
                </span>
              )}
              {rs.is_on_dl60 && (
                <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-rose-800 dark:bg-rose-900/40 dark:text-rose-300">
                  60-day IL
                </span>
              )}
              {rs.designated_for_assignment && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                  DFA
                </span>
              )}
              {rs.is_on_waivers && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                  Waivers
                </span>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Career arc — small WAR-by-year line chart between the Service
          card and the tab strip. Shape tells the career story at a
          glance (peak years, trajectory, gaps). Renders an empty
          placeholder for players with no advanced data. */}
      <section>
        <CareerArc
          batting={player.advanced_batting}
          pitching={player.advanced_pitching}
        />
      </section>

      {/* Contract — salary-by-year bar chart with options + no-trade.
          Skipped for players without an active contract row (amateurs,
          retirees, FAs). */}
      {player.contract && <PlayerContractCard contract={player.contract} />}

      {/* Tab strip — only Stats is wired in v1. Charts cross-link to
          /explore/spray and /explore/ev-la for batters; the link drops
          if the player has no MLB BIP data. Other labels stay
          placeholders. */}
      <nav className="flex flex-wrap items-center gap-1 border-b border-border text-sm">
        <span className="border-b-2 border-content-primary px-3 py-1.5 font-semibold text-content-primary">
          Stats
        </span>
        <Link
          href={`/explore/spray?player=${player.bio.player_id}`}
          className="px-3 py-1.5 text-content-secondary hover:text-content-primary"
        >
          Spray ↗
        </Link>
        <Link
          href={`/explore/ev-la?player=${player.bio.player_id}`}
          className="px-3 py-1.5 text-content-secondary hover:text-content-primary"
        >
          EV / LA ↗
        </Link>
        {["Game log", "Comparisons", "Scouting", "Contract"].map((label) => (
          <span
            key={label}
            className="cursor-not-allowed px-3 py-1.5 text-content-muted"
            title="Coming soon"
          >
            {label}
          </span>
        ))}
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
