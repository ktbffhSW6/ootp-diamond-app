// History · Hall of Fame.
//
// Two views: Inductees (every player flagged hall_of_fame=1 in
// players_current — OOTP imports the real Cooperstown roster plus
// in-save inductees the simulation has voted in) and Candidates
// (top career WAR who aren't yet inducted — the "who should be
// next?" view). Backed by `GET /api/hof?view=&limit=`.
//
// No era picker — the HoF flag is save-only, and OOTP imports
// real-life HoFers as save data. Inductees view shows them all.
//
// Defaults: view=inductees, limit=25 (only applies to candidates).

import Link from "next/link";

import { getHof, getHofPlaques, type HofPlaqueManifest } from "@/lib/api";
import type { HofPlayer, HofResponse } from "@/lib/types/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const metadata = { title: "Hall of Fame — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// View toggle — Inductees vs Candidates as count-pill links so each
// side shows its size without a second round-trip.
// ─────────────────────────────────────────────────────────────────────

function ViewPill({
  view,
  current,
  count,
  label,
}: {
  view: "inductees" | "candidates";
  current: string;
  count: number;
  label: string;
}) {
  const active = view === current;
  return (
    <Link
      href={`/history/hof?view=${view}`}
      className={
        active
          ? "rounded bg-content-primary px-3 py-1.5 text-sm font-semibold text-surface-page"
          : "rounded border border-border bg-surface-card px-3 py-1.5 text-sm text-content-secondary hover:border-border-strong hover:bg-surface-elevated"
      }
    >
      {label}
      <span className="ml-1.5 text-xs opacity-70">·&nbsp;{count}</span>
    </Link>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Roster table — same shape for both views; per-view differences
// are: Inductees show the Inducted year column, Candidates show the
// Rank column. Career WAR + Last Team are common.
// ─────────────────────────────────────────────────────────────────────

function fmtWar(war: number | null): string {
  if (war === null) return "—";
  return war.toFixed(1);
}

function HofTable({
  rows,
  view,
}: {
  rows: HofPlayer[];
  view: "inductees" | "candidates";
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
        No rows for this view.
      </p>
    );
  }
  const showRank = view === "candidates";
  const showInducted = view === "inductees";
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            {showRank && (
              <th
                className="px-3 py-1.5 text-right font-medium"
                title="Rank by career WAR within the non-inducted cohort"
              >
                #
              </th>
            )}
            <th className="px-3 py-1.5 text-left font-medium">Player</th>
            {showInducted && (
              <th
                className="px-3 py-1.5 text-right font-medium"
                title="Year of induction"
              >
                Inducted
              </th>
            )}
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Career WAR (sum of bWAR + pWAR across all seasons)"
            >
              Career WAR
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Most recent team"
            >
              Team
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.player_id}
              className="border-t border-border hover:bg-surface-elevated"
            >
              {showRank && (
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-muted">
                  {row.rank ?? ""}
                </td>
              )}
              <td className="px-3 py-1.5 align-middle">
                <Link
                  href={`/player/${row.player_id}`}
                  className="font-medium text-link hover:text-link-hover hover:underline"
                >
                  {row.display_name}
                </Link>
              </td>
              {showInducted && (
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                  {row.inducted_year ?? "—"}
                </td>
              )}
              <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                {fmtWar(row.career_war)}
              </td>
              <td className="px-3 py-1.5 font-mono text-xs text-content-muted">
                {row.last_team_abbr ?? "—"}
              </td>
              <td className="px-3 py-1.5 align-middle">
                {row.retired ? (
                  <span className="rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-content-muted">
                    Retired
                  </span>
                ) : (
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                    Active
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Plaque gallery
//
// OOTP ships ~8 marquee plaques as PNG files in
// <install>/hof/. The /api/photos/hof manifest enumerates the ones
// actually present on disk; we render those as a horizontal-scroll
// gallery above the inductees table. Each thumbnail links into the
// player page for that bbref_id when we can resolve a player_id from
// the inductees rows. Clicking the image opens the full plaque in a
// new tab via /api/photos/hof/{bbref_id}.png.
// ─────────────────────────────────────────────────────────────────────

function PlaqueGallery({
  manifest,
  inductees,
}: {
  manifest: HofPlaqueManifest;
  inductees: HofPlayer[];
}) {
  if (manifest.plaques.length === 0) return null;
  // Build bbref_id → player_id map from inductees so plaque clicks
  // navigate into the player page where possible.
  const playerIdByBbref = new Map<string, number>();
  for (const row of inductees) {
    if (row.bbref_id) playerIdByBbref.set(row.bbref_id, row.player_id);
  }
  return (
    <section className="rounded-md border border-border bg-surface-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-content-secondary">
        Real plaques · OOTP-shipped imagery
      </h2>
      <p className="mb-3 text-xs text-content-muted">
        {manifest.plaques.length} of OOTP&apos;s real Cooperstown plaque PNGs
        ship with the install. Click to open at full resolution.
      </p>
      <div className="-mx-1 flex flex-nowrap gap-3 overflow-x-auto px-1 pb-2">
        {manifest.plaques.map((p) => {
          const playerId = playerIdByBbref.get(p.bbref_id);
          const inner = (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${API_URL}/api/photos/hof/${p.bbref_id}.png`}
                alt={`${p.name} plaque`}
                width={140}
                height={180}
                loading="lazy"
                decoding="async"
                className="h-44 w-auto rounded border border-border object-cover transition group-hover:border-border-strong"
              />
              <div className="mt-1 text-center text-xs text-content-secondary">
                <div className="truncate font-medium text-content-primary">
                  {p.name}
                </div>
                <div className="truncate text-[10px] text-content-muted">
                  {p.description.split("\n")[0]}
                </div>
              </div>
            </>
          );
          return playerId !== undefined ? (
            <Link
              key={p.bbref_id}
              href={`/player/${playerId}`}
              className="group block w-36 shrink-0"
              title={`${p.name} — ${p.description}`}
            >
              {inner}
            </Link>
          ) : (
            <a
              key={p.bbref_id}
              href={`${API_URL}/api/photos/hof/${p.bbref_id}.png`}
              target="_blank"
              rel="noopener noreferrer"
              className="group block w-36 shrink-0"
              title={`${p.name} — ${p.description}`}
            >
              {inner}
            </a>
          );
        })}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function HofPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const params = await searchParams;
  const view: "inductees" | "candidates" =
    params.view === "candidates" ? "candidates" : "inductees";
  // Fetch HoF rows + plaque manifest in parallel. Manifest call is
  // tolerant of failure — the page renders the table only if it 404s.
  const [data, plaqueManifest]: [HofResponse, HofPlaqueManifest] =
    await Promise.all([
      getHof({ view }),
      getHofPlaques().catch(() => ({ plaques: [] }) as HofPlaqueManifest),
    ]);

  const headline =
    view === "inductees"
      ? "Hall of Fame — Inductees"
      : "Hall of Fame — Candidates";

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          History · Hall of Fame
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {headline}
        </h1>
        <p className="text-sm text-content-secondary">
          {view === "inductees" ? (
            <>
              Cooperstown roster — every player flagged{" "}
              <code className="font-mono">hall_of_fame=1</code> in the save's
              latest snapshot. OOTP imports the real Cooperstown roster
              (Aaron, Mays, Mantle, etc.) plus any in-save inductees the
              simulation has voted in (Pujols 2028, Cabrera 2029).
            </>
          ) : (
            <>
              Top {data.candidates_count} non-inducted players ranked by
              career WAR. Surfaces marquee absentees (Bonds, Clemens, Pete
              Rose, A-Rod), recent retirees the sim hasn't yet voted in,
              and active stars on the Hall track (Trout, Judge).
            </>
          )}
        </p>
      </header>

      <div className="flex flex-wrap gap-3">
        <ViewPill
          view="inductees"
          current={view}
          count={data.inductees_count}
          label="Inductees"
        />
        <ViewPill
          view="candidates"
          current={view}
          count={data.candidates_count}
          label="Candidates"
        />
      </div>

      {view === "inductees" && (
        <PlaqueGallery manifest={plaqueManifest} inductees={data.rows} />
      )}

      <HofTable rows={data.rows} view={view} />

      <section className="space-y-2 border-t border-border pt-6 text-xs text-content-muted">
        <p>
          <strong>Career WAR</strong> sums OOTP's directly-supplied WAR
          field (the IE-A-tier-reconciled <code>b_war</code> +{" "}
          <code>p_war</code>) across every season. Falls back to a dash for
          players whose career predates the WAR-tracking era and OOTP
          didn't import a value.
        </p>
        <p>
          <strong>Inductees ordering</strong> — most recent induction first.
          The 2028 / 2029 Cooperstown classes (Cabrera, Pujols, Cano) sit
          at the top.
        </p>
        <p>
          <strong>Candidates ranking</strong> — career WAR is the canonical
          Hall-worthiness proxy in modern voting. Ties broken alphabetically.
          Pure pitchers with high <code>p_war</code> appear in the same
          ranking via a UNION on the WAR column.
        </p>
      </section>
    </div>
  );
}
