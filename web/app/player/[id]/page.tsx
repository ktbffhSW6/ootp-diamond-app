// Player page — bio + persistent header strip + tab-filtered content.
//
// 2026-05-13 IA shuffle (round 2): the page was a single long scroll
// — Stats table, Spray chart, EV/LA scatter, AI summary all stacked.
// Now `?tab=` (query state) selects which content section is visible:
//
//   ?tab=stats       (default) Stats tables (PlayerStatsTab)
//   ?tab=charts      Spray + EV/LA + (if there's BIP at MLB)
//   ?tab=ai          AI summary trigger
//   ?tab=game-log / comparisons / scouting  ─ placeholders
//
// Header content (bio + Service & Status + CareerArc + Contract)
// stays visible across all tabs — it's the "page metadata" strip,
// not a tab. When you flip from Stats to Charts you don't lose the
// player's name + position + age + service-time context.
//
// Server component reads `searchParams.tab`; PlayerTabNav (also
// server) is just a strip of <Link> elements. No client tab-state
// plumbing — every tab change is a regular URL navigation, browser
// back works, deep-links work.

import Link from "next/link";
import { notFound } from "next/navigation";

import { AISummarizeButton } from "@/components/AISummarizeButton";
import { CareerArc } from "@/components/CareerArc";
import { EvLaScatter } from "@/components/EvLaScatter";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PlayerContractCard } from "@/components/PlayerContractCard";
import { PlayerStatsTab } from "@/components/PlayerStatsTab";
import { PlayerTabNav, type PlayerTab } from "@/components/PlayerTabNav";
import { StadiumSprayChart } from "@/components/StadiumSprayChart";
import { TeamLogo } from "@/components/TeamLogo";
import { getBattedBalls, getGlossary, getParks, getPlayer, getSave } from "@/lib/api";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}

const TAB_VALUES: PlayerTab[] = [
  "stats",
  "charts",
  "ai",
  "game-log",
  "comparisons",
  "scouting",
];

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

export default async function PlayerPage({ params, searchParams }: Props) {
  const { id } = await params;
  const sp = await searchParams;
  const playerId = Number.parseInt(id, 10);
  if (!Number.isFinite(playerId)) {
    notFound();
  }

  // Validate ?tab= against the union; bad values fall back to "stats".
  const requestedTab = (sp.tab ?? "stats") as PlayerTab;
  const tab: PlayerTab = TAB_VALUES.includes(requestedTab) ? requestedTab : "stats";

  // Fetch in parallel — glossary supplies column-header tooltips
  // (per D15 maintenance contract: every UI label comes from the
  // dictionary). batted_balls populates the inline Spray + EV-LA
  // sections (gated on bip_count > 0). save metadata gives us the
  // user's home park abbr for the stadium-overlay default.
  let player, glossary, battedBalls, save, parks;
  try {
    [player, glossary, battedBalls, save, parks] = await Promise.all([
      getPlayer(playerId),
      getGlossary(),
      // Don't fail the whole page if batted_balls 404s — defensive,
      // since most players (especially pitchers / non-MLB call-ups)
      // have an empty BIP set at MLB. Empty rows[] is the normal
      // shape and gates the section render below.
      getBattedBalls({ playerId, levelId: 1 }).catch(() => null),
      getSave().catch(() => null),
      // Park catalog (D29 Slice C) — feeds StadiumSprayChart's
      // OOTP-canonical geometry path. Tolerant of failure: hand-coded
      // dimensions still render the chart correctly without it.
      getParks().catch(() => null),
    ]);
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      notFound();
    }
    throw err;
  }

  const { bio, roster_status: rs } = player;
  const hasBip = !!battedBalls && battedBalls.bip_count > 0;

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
      {/* Bio header — always visible. */}
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
              <div className="flex items-center gap-2">
                <dt className="inline text-content-muted">Team:</dt>{" "}
                <TeamLogo
                  teamId={bio.current_team.team_id}
                  abbr={bio.current_team.abbr}
                  size="md"
                />
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

      {/* Service & Status — always visible header strip. Skipped for
          retired / never-rostered players (rs is null). */}
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
                    ? "Pre-arbitration: less than 3.000 years of MLB service. Renewable contract; no salary leverage."
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

      {/* Career arc — always visible. Career story at a glance. */}
      <section>
        <CareerArc
          batting={player.advanced_batting}
          pitching={player.advanced_pitching}
        />
      </section>

      {/* Contract — always visible if active. */}
      {player.contract && <PlayerContractCard contract={player.contract} />}

      {/* Tab nav — selects which content section renders below. */}
      <PlayerTabNav active={tab} playerId={playerId} hasBip={hasBip} />

      {/* Tab content — only the active tab renders. */}
      {tab === "stats" && <PlayerStatsTab player={player} glossary={glossary} />}

      {tab === "charts" && !hasBip && (
        <section className="rounded-md border border-border bg-surface-card p-8 text-center text-content-muted">
          <p className="text-sm">
            No MLB ball-in-play events for this player. Charts populate
            once a batter has BIP data at the major-league level
            (pitchers, amateurs, and minor-league call-ups all drop this
            tab).
          </p>
        </section>
      )}
      {tab === "charts" && hasBip && battedBalls && (
        <div className="space-y-8">
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-secondary">
              Spray · {battedBalls.year} MLB · {battedBalls.bip_count} BIP
            </h2>
            <p className="mb-3 text-xs text-content-muted">
              Each dot is one ball-in-play, plotted at its{" "}
              <strong>field-absolute</strong> location. Spray angle from
              OOTP&apos;s `hit_xy` (batter-relative, flipped per
              handedness {bio.bats_throws}); distance synthesized from
              EV + LA via projectile physics with empirical drag (HRs
              floored to clear the foul-pole distance). Stadium overlay
              picks the user&apos;s home park by default —{" "}
              <strong>switchable</strong> in the dropdown.
            </p>
            <StadiumSprayChart
              rows={battedBalls.rows}
              handedness={
                bio.bats === 2 ? "L" : bio.bats === 3 ? "S" : "R"
              }
              defaultStadium={save?.org_team_abbr ?? "BOS"}
              parksApi={parks}
            />
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-secondary">
              EV / LA · {battedBalls.year} MLB
            </h2>
            <p className="mb-3 text-xs text-content-muted">
              Sweet-spot band (blue) = LA 8–32°. Barrel zone (orange) =
              EV ≥ 93 mph + LA 22–38° — calibrated for OOTP&apos;s ~5
              mph offset from real Statcast.
            </p>
            <EvLaScatter rows={battedBalls.rows} />
          </section>
        </div>
      )}

      {tab === "ai" && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-secondary">
            AI summary
          </h2>
          <AISummarizeButton
            kind="player"
            targetId={player.bio.player_id}
            label="Summarize career"
          />
        </section>
      )}

      {(tab === "game-log" || tab === "comparisons" || tab === "scouting") && (
        <section className="rounded-md border border-border bg-surface-card p-8 text-center text-content-muted">
          <p className="text-sm">
            <span className="font-semibold capitalize text-content-primary">
              {tab.replace("-", " ")}
            </span>{" "}
            — coming soon.
          </p>
        </section>
      )}

      <p className="pt-4 text-xs text-content-muted">
        <Link href="/" className="hover:text-content-primary">
          ← Diamond
        </Link>
      </p>
    </article>
  );
}
