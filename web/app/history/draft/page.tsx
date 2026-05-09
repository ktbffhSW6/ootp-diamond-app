// History · Draft Classes — per-year retrospectives.
//
// Backed by `GET /api/draft?year=`. Returns the entire ~600-pick
// class for one year, grouped by outcome bucket (mlb_regular →
// mlb_callup → in_draft_org → traded_away → released → retired).
//
// Server component; year picker is a <Link> strip. Default year
// = oldest with material outcome variation, so fresh classes don't
// render as a wall of "still developing" rows.

import Link from "next/link";

import { getDraft } from "@/lib/api";
import type {
  DraftBucket,
  DraftClassResponse,
  DraftClassSummary,
  DraftPick,
} from "@/lib/types/api";

export const metadata = { title: "Draft — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Position lookup — keep tight to spare a glossary fetch per row.
// Mirrors POSITION_NAMES in src/diamond/constants.py.
// ─────────────────────────────────────────────────────────────────────

const POSITION_NAMES: Record<number, string> = {
  1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
  6: "SS", 7: "LF", 8: "CF", 9: "RF",
};

const LEVEL_NAMES: Record<number, string> = {
  1: "MLB", 2: "AAA", 3: "AA", 4: "A+/A", 6: "Rk",
};

function fmtPosition(pos: number): string {
  return POSITION_NAMES[pos] ?? `Pos ${pos}`;
}

function fmtPick(round: number | null, overall: number | null): string {
  if (round === null && overall === null) return "—";
  if (round === null) return `#${overall}`;
  if (overall === null) return `Rd ${round}`;
  return `${round}.${overall}`;
}

// IP convention: outs → "X.Y" (Y ∈ {0, 1, 2})
function fmtIp(outs: number): string {
  if (!outs) return "0.0";
  return `${Math.floor(outs / 3)}.${outs % 3}`;
}

// ─────────────────────────────────────────────────────────────────────
// Year picker — flat strip, ordered DESC (most-recent first) for the
// natural "browse back" experience.
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
        Draft Year
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {available.map((y) => {
          const active = y === current;
          return (
            <Link
              key={y}
              href={`/history/draft?year=${y}`}
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
// Class summary — small at-a-glance card, color-coded by outcome.
// ─────────────────────────────────────────────────────────────────────

function ClassSummary({ summary }: { summary: DraftClassSummary }) {
  const reachedMlbPct =
    summary.total_picks > 0
      ? Math.round((summary.ever_made_mlb * 1000) / summary.total_picks) / 10
      : 0;
  return (
    <section className="rounded-md border border-border bg-surface-card p-4">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <div className="font-mono text-2xl font-semibold tabular-nums text-content-primary">
            {summary.total_picks}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-content-muted">
            Total Picks
          </div>
        </div>
        <div>
          <div className="font-mono text-2xl font-semibold tabular-nums text-content-primary">
            {summary.ever_made_mlb}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-content-muted">
            Reached MLB ({reachedMlbPct.toFixed(1)}%)
          </div>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <CountChip kind="mlb_regular" count={summary.mlb_regular} />
          <CountChip kind="mlb_callup" count={summary.mlb_callup} />
          <CountChip kind="in_draft_org" count={summary.in_draft_org} />
          <CountChip kind="traded_away" count={summary.traded_away} />
          <CountChip kind="released" count={summary.released} />
          <CountChip kind="retired" count={summary.retired} />
        </div>
      </div>
    </section>
  );
}

const CHIP_LABEL: Record<string, string> = {
  mlb_regular: "Regulars",
  mlb_callup: "Callups",
  in_draft_org: "Developing",
  traded_away: "Traded",
  released: "Released",
  retired: "Retired",
};

const CHIP_COLOR: Record<string, string> = {
  mlb_regular:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  mlb_callup:
    "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  in_draft_org:
    "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
  traded_away:
    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  released:
    "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  retired:
    "bg-surface-elevated text-content-muted",
};

function CountChip({ kind, count }: { kind: string; count: number }) {
  if (count === 0) return null;
  return (
    <span
      className={`rounded px-2 py-1 text-[11px] font-medium uppercase tracking-wide ${CHIP_COLOR[kind] ?? ""}`}
    >
      {CHIP_LABEL[kind] ?? kind}
      <span className="ml-1.5 font-mono text-xs">{count}</span>
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Bucket section — one card per outcome bucket with a header + a
// dense Bref-style table. Long buckets (in_draft_org with 281 rows
// for 2026) render fully — no pagination, just scroll.
// ─────────────────────────────────────────────────────────────────────

function isPitcher(p: DraftPick): boolean {
  // Position 1 = P. Use mlb_outs as fallback for two-way / converted
  // bats too.
  return p.position === 1 || (p.mlb_outs > 0 && p.mlb_pa === 0);
}

function fmtCareerStats(p: DraftPick): string {
  if (!p.ever_made_mlb) return "—";
  if (isPitcher(p)) {
    if (p.mlb_outs === 0) return "—";
    const wlSv = `${p.mlb_w}-${p.mlb_g_pit > 0 ? Math.max(p.mlb_g_pit - p.mlb_w - p.mlb_s, 0) : 0}`;
    return `${p.mlb_g_pit} G, ${fmtIp(p.mlb_outs)} IP, ${p.mlb_war_pit.toFixed(1)} WAR`;
  }
  if (p.mlb_pa === 0) return "—";
  return `${p.mlb_g} G, ${p.mlb_pa} PA, ${p.mlb_hr} HR, ${p.mlb_war_bat.toFixed(1)} WAR`;
}

function BucketSection({ bucket }: { bucket: DraftBucket }) {
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <header className="flex items-baseline gap-3 border-b border-border px-4 py-2">
        <h2 className="text-base font-semibold text-content-primary">
          {bucket.label}
        </h2>
        <span className="font-mono text-xs text-content-muted">
          {bucket.count}
        </span>
      </header>
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Round.Pick (1.1 = first overall)"
            >
              Pick
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Player</th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Listed primary position"
            >
              Pos
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Drafted By</th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Most recent team + level"
            >
              Now With
            </th>
            <th
              className="px-3 py-1.5 text-left font-medium"
              title="Career MLB stats line — batting (G/PA/HR/WAR) or pitching (G/IP/WAR)"
            >
              MLB Career
            </th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Combined batting + pitching career WAR"
            >
              Career WAR
            </th>
          </tr>
        </thead>
        <tbody>
          {bucket.rows.map((p) => (
            <tr
              key={p.player_id}
              className="border-t border-border hover:bg-surface-elevated"
            >
              <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-content-muted">
                {fmtPick(p.draft_round, p.draft_overall_pick)}
              </td>
              <td className="px-3 py-1.5 align-middle">
                <Link
                  href={`/player/${p.player_id}`}
                  className="font-medium text-link hover:text-link-hover hover:underline"
                >
                  {p.display_name}
                </Link>
              </td>
              <td className="px-3 py-1.5 font-mono text-xs text-content-secondary">
                {fmtPosition(p.position)}
              </td>
              <td className="px-3 py-1.5 text-xs text-content-secondary">
                {p.draft_team_name ?? "—"}
              </td>
              <td className="px-3 py-1.5 text-xs text-content-secondary">
                {p.current_team_name ? (
                  <>
                    {p.current_team_name}
                    {p.current_level_id !== null &&
                      p.current_level_id !== 1 && (
                        <span className="ml-1 font-mono text-[10px] text-content-muted">
                          ({LEVEL_NAMES[p.current_level_id] ?? `L${p.current_level_id}`})
                        </span>
                      )}
                  </>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-content-secondary">
                {fmtCareerStats(p)}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                {p.career_mlb_war > 0 || p.ever_made_mlb
                  ? p.career_mlb_war.toFixed(1)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function DraftPage({
  searchParams,
}: {
  searchParams: Promise<{ year?: string }>;
}) {
  const params = await searchParams;
  const data: DraftClassResponse = await getDraft({
    year: params.year ? Number(params.year) : undefined,
  });

  const yearsSinceClass =
    data.available_years.length > 0
      ? Math.max(...data.available_years) - data.year
      : 0;
  const ageContext =
    yearsSinceClass === 0
      ? "Fresh class — most picks still developing in their draft org."
      : yearsSinceClass === 1
        ? "One year out — early-career outcomes."
        : `${yearsSinceClass} years out — outcomes have largely stabilized.`;

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          History · Draft
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {data.year} Draft Class
        </h1>
        <p className="text-sm text-content-secondary">
          {ageContext} Where are they now? Each pick is bucketed by
          outcome (MLB Regular / Callup / Still Developing / Traded /
          Released / Retired). Within a bucket, rows order by overall
          pick — top-of-class first.
        </p>
      </header>

      <YearPicker available={data.available_years} current={data.year} />

      <ClassSummary summary={data.summary} />

      {data.buckets.length === 0 ? (
        <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
          No picks recorded for {data.year}.
        </p>
      ) : (
        <div className="space-y-6">
          {data.buckets.map((b) => (
            <BucketSection key={b.outcome} bucket={b} />
          ))}
        </div>
      )}

      <section className="space-y-2 border-t border-border pt-6 text-xs text-content-muted">
        <p>
          <strong>Outcome buckets</strong> are derived in the L3 build
          from a snapshot of <code className="font-mono">players_current</code>{" "}
          + <code className="font-mono">player_movements</code>:{" "}
          <em>mlb_regular</em> = made MLB and accumulated meaningful WAR;{" "}
          <em>mlb_callup</em> = made MLB but barely;{" "}
          <em>in_draft_org</em> = still in the org that drafted them;{" "}
          <em>traded_away</em> = moved orgs; <em>released</em>,{" "}
          <em>retired</em> = self-explanatory.
        </p>
        <p>
          <strong>Career WAR</strong> sums OOTP's MLB batting WAR +
          pitching WAR for that player only — minor-league time doesn't
          contribute. A 4-WAR pick from round 4 (Gunner Skelton in 2026)
          beats a 2-WAR pick from round 1 — pick value over time.
        </p>
        <p>
          <strong>Year defaults</strong> to the oldest class with at
          least one non-<em>in_draft_org</em> outcome. Fresh classes
          (e.g., the 2029 draft just-drafted) have ~570 rows of "still
          developing" — boring page. The default puts you on the most
          interesting retrospective.
        </p>
      </section>
    </div>
  );
}
