// League view — scoped leagues (MLB tree + DSL + AFL).
//
// Shipped 2026-05-10: standings (sub-league × division × team) at a
// resolved dump_date snapshot. Defaults to MLB / latest year — both
// pickable via query string. The user's org row is highlighted.
//
// Backed by `GET /api/standings?league_id=&year=`. Server component;
// the league + year pickers are server-rendered <Link> grids (no client
// state) driven by `available_leagues` / `available_years` in the
// response.
//
// Below the standings block we keep slim stubs for the other planned
// /league content (leaderboards / awards races / FA pool) so the IA
// stays visible — when those ship they replace the stubs in place.

import Link from "next/link";

import { getStandings } from "@/lib/api";
import type {
  StandingsLeagueRef,
  StandingsResponse,
  StandingsTeamRow,
} from "@/lib/types/api";

export const metadata = { title: "League — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

// PCT renders without leading zero per baseball convention (".574").
function fmtPct(p: number): string {
  if (!Number.isFinite(p)) return ".000";
  return p.toFixed(3).replace(/^0/, "");
}

// GB convention: 0.0 → "—" (the leader), otherwise one decimal.
function fmtGb(gb: number): string {
  if (gb === 0) return "—";
  return gb.toFixed(1);
}

// Streak is signed (positive = W, negative = L). Zero = no streak.
function fmtStreak(s: number): string {
  if (s === 0) return "—";
  if (s > 0) return `W${s}`;
  return `L${Math.abs(s)}`;
}

function streakClass(s: number): string {
  if (s === 0) return "text-content-muted";
  if (s > 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-rose-600 dark:text-rose-400";
}

function fmtSnapshotDate(iso: string): string {
  // ISO date string from API. Render long-form so the user knows
  // exactly which monthly cut they're looking at.
  const dt = new Date(iso);
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ─────────────────────────────────────────────────────────────────────
// League picker — group available leagues by level so the strip is
// scannable. Order: MLB, AAA, AA, A+, A, Rk/Complex, DSL.
// ─────────────────────────────────────────────────────────────────────

const LEVEL_HEADER: Record<number, string> = {
  1: "MLB",
  2: "AAA",
  3: "AA",
  4: "A+ / A",
  6: "Rk / DSL",
};

function groupByLevel(
  leagues: StandingsLeagueRef[],
): { level: number; header: string; entries: StandingsLeagueRef[] }[] {
  const byLevel = new Map<number, StandingsLeagueRef[]>();
  for (const lg of leagues) {
    const arr = byLevel.get(lg.league_level) ?? [];
    arr.push(lg);
    byLevel.set(lg.league_level, arr);
  }
  return [...byLevel.entries()]
    .sort(([a], [b]) => a - b)
    .map(([level, entries]) => ({
      level,
      header: LEVEL_HEADER[level] ?? `Level ${level}`,
      entries,
    }));
}

function buildHref(leagueId: number, year: number): string {
  return `/league?league_id=${leagueId}&year=${year}`;
}

function LeaguePicker({
  available,
  current,
  year,
}: {
  available: StandingsLeagueRef[];
  current: number;
  year: number;
}) {
  const groups = groupByLevel(available);
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        League
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {groups.map((g) => (
          <div key={g.level} className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-content-muted">
              {g.header}
            </span>
            {g.entries.map((lg) => {
              const active = lg.league_id === current;
              return (
                <Link
                  key={lg.league_id}
                  href={buildHref(lg.league_id, year)}
                  title={lg.name ?? lg.abbr ?? ""}
                  className={
                    active
                      ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                      : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
                  }
                >
                  {lg.abbr ?? lg.league_id}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function YearPicker({
  available,
  current,
  leagueId,
}: {
  available: number[];
  current: number;
  leagueId: number;
}) {
  if (available.length <= 1) return null;
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Season
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {available.map((y) => {
          const active = y === current;
          return (
            <Link
              key={y}
              href={buildHref(leagueId, y)}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {y}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Standings table — one division. Boston row gets a left-border accent
// + a soft surface tint so it's instantly findable in the AL East.
// ─────────────────────────────────────────────────────────────────────

function TeamRow({ row }: { row: StandingsTeamRow }) {
  const orgRowClass = row.is_user_org
    ? "border-l-2 border-l-accent bg-surface-elevated/60"
    : "border-l-2 border-l-transparent";
  const teamLabel = row.nickname ?? row.abbr ?? `Team ${row.team_id}`;
  return (
    <tr className={`${orgRowClass} border-t border-border hover:bg-surface-elevated`}>
      <td className="px-3 py-1.5 align-middle text-xs text-content-muted text-right tabular-nums">
        {row.pos > 0 ? row.pos : ""}
      </td>
      <td className="px-3 py-1.5 align-middle">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-content-muted">
            {row.abbr ?? "—"}
          </span>
          <span className="text-sm font-medium text-content-primary">
            {teamLabel}
          </span>
          {row.clinched && (
            <span
              className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
              title="Clinched division"
            >
              Clinched
            </span>
          )}
          {row.is_user_org && (
            <span className="text-[10px] uppercase tracking-wider text-accent">
              You
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
        {row.w}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
        {row.l}
      </td>
      {/* Ties — usually zero for MLB; surface only if non-zero so the
          column doesn't look like a sea of dashes. */}
      <td
        className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-content-muted"
        title={row.t > 0 ? `${row.t} ties` : "no ties"}
      >
        {row.t > 0 ? row.t : ""}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
        {fmtPct(row.pct)}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
        {fmtGb(row.gb)}
      </td>
      <td className={`px-3 py-1.5 text-right font-mono text-sm tabular-nums ${streakClass(row.streak)}`}>
        {fmtStreak(row.streak)}
      </td>
      <td
        className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-content-muted"
        title={
          row.magic_number === null
            ? "Magic number not applicable"
            : `Magic number to clinch: ${row.magic_number}`
        }
      >
        {row.magic_number !== null ? row.magic_number : "—"}
      </td>
    </tr>
  );
}

function DivisionTable({
  name,
  teams,
}: {
  name: string | null;
  teams: StandingsTeamRow[];
}) {
  return (
    <section className="rounded-md border border-border bg-surface-card">
      {name && (
        <header className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {name}
        </header>
      )}
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            <th className="px-3 py-1.5 text-right font-medium" title="Position in division">
              #
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Team</th>
            <th className="px-3 py-1.5 text-right font-medium" title="Wins">W</th>
            <th className="px-3 py-1.5 text-right font-medium" title="Losses">L</th>
            <th className="px-3 py-1.5 text-right font-medium" title="Ties">T</th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Winning percentage"
            >
              Pct
            </th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Games behind division leader"
            >
              GB
            </th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Current streak (W=win, L=loss)"
            >
              Strk
            </th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Magic number to clinch (— = clinched or not yet meaningful)"
            >
              Mag
            </th>
          </tr>
        </thead>
        <tbody>
          {teams.map((t) => (
            <TeamRow key={t.team_id} row={t} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function LeaguePage({
  searchParams,
}: {
  searchParams: Promise<{ league_id?: string; year?: string }>;
}) {
  const { league_id: leagueParam, year: yearParam } = await searchParams;
  const leagueId = leagueParam ? Number(leagueParam) : undefined;
  const year = yearParam ? Number(yearParam) : undefined;
  const data: StandingsResponse = await getStandings(leagueId, year);

  const leagueLabel = data.league.name ?? data.league.abbr ?? `League ${data.league.league_id}`;
  // Hide the sub-league band when there's only one and it has no name —
  // happens for AAA / AA / A* (divisions only, no AL/NL split).
  const showSubLeagueHeaders =
    data.sub_leagues.length > 1 || data.sub_leagues[0]?.sub_league_name != null;

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          League · Standings
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {leagueLabel}
        </h1>
        <p className="text-sm text-content-secondary">
          Standings as of{" "}
          <span className="font-mono text-content-primary">
            {fmtSnapshotDate(data.dump_date)}
          </span>{" "}
          ({data.year} season). Records reflect the OOTP monthly snapshot —
          mid-season cuts show in-progress standings, the November dump shows
          end-of-season finals.
        </p>
      </header>

      <div className="flex flex-wrap gap-x-8 gap-y-4">
        <LeaguePicker
          available={data.available_leagues}
          current={data.league.league_id}
          year={data.year}
        />
        <YearPicker
          available={data.available_years}
          current={data.year}
          leagueId={data.league.league_id}
        />
      </div>

      {data.sub_leagues.length === 0 ? (
        <p className="text-sm text-content-muted">
          No standings rows for this league at this snapshot.
        </p>
      ) : (
        <div className="space-y-8">
          {data.sub_leagues.map((sub) => (
            <section key={sub.sub_league_id} className="space-y-4">
              {showSubLeagueHeaders && sub.sub_league_name && (
                <h2 className="text-lg font-semibold text-content-primary">
                  {sub.sub_league_name}
                </h2>
              )}
              <div
                className={
                  sub.divisions.length > 1
                    ? "grid grid-cols-1 gap-4 lg:grid-cols-2"
                    : "space-y-4"
                }
              >
                {sub.divisions.map((div) => (
                  <DivisionTable
                    key={`${sub.sub_league_id}-${div.division_id}`}
                    name={div.division_name}
                    teams={div.teams}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {/* Other /league content — leaderboards + compare are live as
          of 2026-05-13; awards races + FA pool stay stubs until they
          ship. */}
      <section className="space-y-3 border-t border-border pt-6">
        <h2 className="text-lg font-semibold text-content-primary">
          More in League
        </h2>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              title: "Leaderboards",
              status: "live" as const,
              href: "/league/leaderboards",
              blurb:
                "Single-stat ranked lists, 32 stats across batting / pitching / Statcast. URL-driven picker, TanStack Table sort.",
            },
            {
              title: "Compare",
              status: "live" as const,
              href: "/league/compare",
              blurb:
                "Side-by-side career stat blocks for ≤4 players + WAR sparklines. Cross-era is fair game (D20 baselines).",
            },
            {
              title: "Awards races",
              status: "soon" as const,
              blurb:
                "MVP / Cy Young / ROY frontrunners with stat context.",
            },
            {
              title: "Free agent pool",
              status: "soon" as const,
              blurb:
                "Unsigned players + last team + recent performance.",
            },
          ].map((s) => {
            const card = (
              <div className={s.status === "live" ? "" : "opacity-60"}>
                <div className="flex items-baseline gap-2">
                  <h3 className="text-sm font-semibold text-content-primary">
                    {s.title}
                  </h3>
                  {s.status === "live" ? (
                    <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:bg-emerald-500/25 dark:text-emerald-300">
                      Live
                    </span>
                  ) : (
                    <span className="rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-content-muted">
                      Soon
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-content-secondary">{s.blurb}</p>
              </div>
            );
            return (
              <li
                key={s.title}
                className="rounded-md border border-border bg-surface-card p-3"
              >
                {s.status === "live" && s.href ? (
                  <Link href={s.href} className="block hover:opacity-80">
                    {card}
                  </Link>
                ) : (
                  card
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        v1 caveats: AFL standings are not surfaced here — the Arizona Fall
        League sits in the scope but lacks a league-meta row in the dump.
        Pythagorean / run-differential columns are deferred (the snapshot
        carries W-L-Pct only). Team-page deep links land in a follow-up.
      </p>
    </div>
  );
}
