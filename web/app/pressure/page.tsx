// Pressure board — the "who *should* move" view. Companion to
// /movements (which shows who DID move).
//
// Backed by `GET /api/pressure?year=`. Returns per-level
// promotion-vs-pressure decomposition for the org tree.
//
// Each level renders as a two-column card: top OPS+/ERA+ on the
// left (promotion candidates), bottom OPS+/ERA+ on the right
// (pressure cases). Reading top-to-bottom, you can pattern-match
// "AAA #1 mashing 130 OPS+ next to MLB #5 sitting at 75 OPS+ at
// the same position" and see the obvious roster decision.

import Link from "next/link";

import { getPressure } from "@/lib/api";
import { plusMinusClass } from "@/lib/heatscale";
import type {
  PressureLevelGroup,
  PressurePlayer,
  PressureResponse,
} from "@/lib/types/api";

export const metadata = { title: "Pressure Board — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Year picker — flat strip
// ─────────────────────────────────────────────────────────────────────

function YearPicker({
  available,
  current,
}: {
  available: number[];
  current: number;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Season
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {available.slice(0, 8).map((y) => {
          const active = y === current;
          return (
            <Link
              key={y}
              href={`/pressure?year=${y}`}
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
        {available.length > 8 && (
          <span
            className="text-xs text-content-muted"
            title={`Older years (${available[available.length - 1]}–${available[7]}) available via direct URL: ?year=YYYY`}
          >
            +{available.length - 8} older
          </span>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Per-player row — same layout for both columns; the metric label
// shifts (OPS+ for batters, ERA+ for pitchers).
// ─────────────────────────────────────────────────────────────────────

function fmtSample(p: PressurePlayer): string {
  if (p.role === "batter" && p.pa !== null) return `${p.pa} PA`;
  if (p.role === "pitcher" && p.ip !== null) return `${p.ip.toFixed(1)} IP`;
  return "—";
}

function fmtMetricLabel(role: string): string {
  return role === "batter" ? "OPS+" : "ERA+";
}

function fmtWar(war: number): string {
  return war >= 0 ? `+${war.toFixed(1)}` : war.toFixed(1);
}

const POSITION_NAMES: Record<number, string> = {
  1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
  6: "SS", 7: "LF", 8: "CF", 9: "RF",
};

function fmtPosition(p: PressurePlayer): string {
  if (p.role === "pitcher") return "P";
  if (p.position && POSITION_NAMES[p.position]) return POSITION_NAMES[p.position];
  return "—";
}

// Color the metric cell — uses the central heat-scale (web/lib/heatscale.ts)
// so the gradient matches roster Advanced + player page Advanced. Five
// intensities per side with bg-fill at the extremes (≥160 / ≤40) so
// MVP-tier and replacement-level rows really pop in the column.

function PlayerRow({ p }: { p: PressurePlayer }) {
  const roleChip =
    p.role === "batter"
      ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
      : "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300";
  return (
    <tr className="border-t border-border hover:bg-surface-elevated">
      <td className="px-3 py-1.5 align-middle">
        <span
          className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide ${roleChip}`}
          title={p.role === "batter" ? "Batter" : "Pitcher"}
        >
          {fmtPosition(p)}
        </span>
      </td>
      <td className="px-3 py-1.5 align-middle">
        <Link
          href={`/player/${p.player_id}`}
          className="font-medium text-link hover:text-link-hover hover:underline"
        >
          {p.display_name}
        </Link>
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-content-muted">
        {fmtSample(p)}
      </td>
      <td
        className={`px-3 py-1.5 text-right font-mono text-sm tabular-nums ${plusMinusClass(p.metric)}`}
        title={`${fmtMetricLabel(p.role)} ${p.metric} (${p.delta >= 0 ? "+" : ""}${p.delta} vs lg avg)`}
      >
        {p.metric}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-content-secondary">
        {fmtWar(p.war)}
      </td>
      <td className="px-3 py-1.5 font-mono text-xs text-content-muted">
        {p.team_abbr ?? "—"}
      </td>
    </tr>
  );
}

function ColumnTable({
  rows,
  emptyMessage,
}: {
  rows: PressurePlayer[];
  emptyMessage: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="px-4 py-3 text-xs text-content-muted">{emptyMessage}</p>
    );
  }
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
          <th
            className="px-3 py-1.5 text-left font-medium"
            title="Position (B = batter primary; P = pitcher)"
          >
            Pos
          </th>
          <th className="px-3 py-1.5 text-left font-medium">Player</th>
          <th
            className="px-3 py-1.5 text-right font-medium"
            title="Sample volume (PA for batters, IP for pitchers)"
          >
            Sample
          </th>
          <th
            className="px-3 py-1.5 text-right font-medium"
            title="OPS+ (batter) / ERA+ (pitcher) — 100 = league average"
          >
            +/−
          </th>
          <th
            className="px-3 py-1.5 text-right font-medium"
            title="OOTP-supplied combined WAR"
          >
            WAR
          </th>
          <th className="px-3 py-1.5 text-left font-medium">Team</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <PlayerRow key={`${p.player_id}-${p.role}`} p={p} />
        ))}
      </tbody>
    </table>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Per-level card — header with level + qualifying count, two
// columns side-by-side.
// ─────────────────────────────────────────────────────────────────────

function LevelCard({ group }: { group: PressureLevelGroup }) {
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <header className="flex items-baseline gap-3 border-b border-border px-4 py-2">
        <h2 className="text-base font-semibold text-content-primary">
          {group.level_name}
        </h2>
        <span className="font-mono text-xs text-content-muted">
          {group.qualifying_count} qualifying
        </span>
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-2">
        <div className="lg:border-r lg:border-border">
          <header className="border-b border-border bg-emerald-50 px-3 py-1.5 dark:bg-emerald-900/20">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
              ↑ Promotion Candidates
            </h3>
            <p className="text-[10px] text-content-muted">
              Mashing relative to level average — call-up worthy.
            </p>
          </header>
          <ColumnTable
            rows={group.promotion_candidates}
            emptyMessage="No standouts at this level."
          />
        </div>
        <div>
          <header className="border-b border-border bg-rose-50 px-3 py-1.5 dark:bg-rose-900/20">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
              ↓ Pressure Cases
            </h3>
            <p className="text-[10px] text-content-muted">
              Underperforming — send-down or replacement candidate.
            </p>
          </header>
          <ColumnTable
            rows={group.pressure_cases}
            emptyMessage="No struggles at this level."
          />
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function PressurePage({
  searchParams,
}: {
  searchParams: Promise<{ year?: string }>;
}) {
  const params = await searchParams;
  const data: PressureResponse = await getPressure({
    year: params.year ? Number(params.year) : undefined,
  });

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          Club · Pressure Board
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {data.year} Pressure Board
        </h1>
        <p className="text-sm text-content-secondary">
          The "who <em>should</em> move" view. For each level, the strongest
          performers (call-up candidates) sit on the left; the weakest
          (send-down or replacement candidates) on the right. Pattern-match
          across levels — a 130 OPS+ at AAA next to a 75 OPS+ at MLB is the
          obvious roster decision.
        </p>
      </header>

      <YearPicker available={data.available_years} current={data.year} />

      {data.levels.length === 0 ? (
        <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
          No qualifying players at any level for {data.year}. Try a different
          season — early years or fresh expansion years can have small
          samples.
        </p>
      ) : (
        <div className="space-y-6">
          {data.levels.map((g) => (
            <LevelCard key={g.level_id} group={g} />
          ))}
        </div>
      )}

      <section className="space-y-2 border-t border-border pt-6 text-xs text-content-muted">
        <p>
          <strong>Metric</strong> — OPS+ for batters, ERA+ for pitchers.
          Both are park-adjusted, league-relative, scale 100 = league
          average. Both rank the same direction (high = good), so the
          left column is "above 100" and the right column is "below 100"
          regardless of role.
        </p>
        <p>
          <strong>Sample bars</strong> — batters need ≥50 PA, pitchers
          ≥20 IP. Below that, rate stats noise out and the cards become
          unreliable. Higher sample bars (e.g., MLB-only ≥100 PA) would
          tighten the call-up cohort but lose interesting AAA flashes —
          v1 keeps it permissive.
        </p>
        <p>
          <strong>Cross-level signals</strong> — a player who sits on
          both a higher-level "pressure" list and a lower-level
          "promotion" list is the call-up no-brainer. A player only on
          one list is a one-sided story (great at AAA + no MLB time
          yet, or struggling at MLB + AAA depth that hasn't broken
          out). Both are GM-actionable.
        </p>
        <p>
          <strong>Companion</strong> — pair this with{" "}
          <Link
            href="/movements"
            className="text-link hover:text-link-hover hover:underline"
          >
            /movements
          </Link>{" "}
          (who DID move) to see whether the org is acting on its own
          pressure signals.
        </p>
      </section>
    </div>
  );
}
