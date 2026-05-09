// Explore · Compare — first live mode in the Explore sandbox.
//
// Pick up to 4 player_ids via ?ids=1,2,3,4. Renders side-by-side
// compare cards: bio header + career stat block + career WAR
// sparkline. Trout-vs-Cobb / Bonds-vs-Aaron / your-prospect-vs-MVP
// type comparisons.
//
// Default landing (no ids) shows a hint with example deep-links.
// IDs that don't resolve surface in a small "not in scope" footer.

import Link from "next/link";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Sparkline } from "@/components/Sparkline";
import { plusMinusClass, warSeasonClass } from "@/lib/heatscale";
import { getCompare } from "@/lib/api";
import type { ComparePlayer, CompareResponse } from "@/lib/types/api";

export const metadata = { title: "Compare — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function fmtSlash(v: number | null): string {
  if (v === null) return "—";
  const s = v.toFixed(3);
  return v < 1 ? s.replace(/^0/, "") : s;
}

function fmtIp(outs: number): string {
  if (!outs) return "—";
  const full = Math.floor(outs / 3);
  const frac = outs % 3;
  return `${full}.${frac}`;
}

function fmt2(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}

function fmtWar(v: number | null): string {
  if (v === null) return "—";
  return v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}

// Featured demo links — surfaced on the empty state to make the page
// useful without pre-existing knowledge of player IDs.
const DEMO_LINKS: { ids: number[]; label: string; blurb: string }[] = [
  {
    ids: [3259, 2009, 14136],
    label: "Bonds · Aaron · Ruth",
    blurb: "All-time HR leaderboard top three, three different eras.",
  },
  {
    ids: [28963, 36239, 33526],
    label: "Trout · Ohtani · Judge",
    blurb: "Modern-era WAR titans — including Ohtani two-way.",
  },
  {
    ids: [10751, 11099, 4509],
    label: "Pedro · Maddux · Clemens",
    blurb: "ERA+ peaks across the steroid era.",
  },
];

// ─────────────────────────────────────────────────────────────────────
// Compare card
// ─────────────────────────────────────────────────────────────────────

function CompareCard({ p }: { p: ComparePlayer }) {
  const isPitcher = p.career_outs > 0 && p.career_pa < 50;
  const showBatting = p.career_pa >= 50;
  const showPitching = p.career_outs >= 30;
  const headlineMetric = p.latest_ops_plus ?? p.latest_era_plus;
  const headlineLabel = p.latest_ops_plus !== null ? "OPS+" : "ERA+";

  return (
    <article className="flex flex-col gap-3 rounded-md border border-border bg-surface-card p-4">
      <header className="flex items-start gap-3 border-b border-border pb-3">
        <PlayerAvatar
          playerId={p.player_id}
          displayName={p.display_name}
          size="md"
        />
        <div className="min-w-0 flex-1">
          <Link
            href={`/player/${p.player_id}`}
            className="text-base font-semibold text-link hover:text-link-hover hover:underline"
          >
            {p.display_name}
          </Link>
          <p className="mt-0.5 text-xs text-content-muted">
            {p.position_name}
            {p.bats_throws && p.bats_throws !== "?/?" && (
              <span className="ml-2 font-mono">{p.bats_throws}</span>
            )}
            {p.age !== null && (
              <span className="ml-2">age {p.age}</span>
            )}
            {p.current_team_abbr && (
              <span className="ml-2 font-mono text-content-secondary">
                · {p.current_team_abbr}
              </span>
            )}
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {p.is_hall_of_fame && (
              <span
                className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                title="Hall of Fame inductee"
              >
                HoF
              </span>
            )}
            {p.is_retired && !p.is_hall_of_fame && (
              <span className="rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-content-muted">
                Retired
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Career WAR sparkline + headline metric */}
      <section className="space-y-1">
        <div className="flex items-baseline justify-between">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Career arc · {p.career_years.length}{" "}
            season{p.career_years.length === 1 ? "" : "s"}
          </p>
          <p className="font-mono text-lg font-semibold tabular-nums text-content-primary">
            <span className={warSeasonClass(p.career_total_war)}>
              {p.career_total_war.toFixed(1)}
            </span>
            <span className="ml-1 text-[10px] font-normal text-content-muted">
              WAR
            </span>
          </p>
        </div>
        <Sparkline
          values={p.career_war}
          width={300}
          height={48}
          showDots
          label={`Career WAR — ${p.career_years[0]} to ${p.career_years[p.career_years.length - 1]}`}
        />
        {headlineMetric !== null && p.latest_year !== null && (
          <p className="text-[10px] text-content-muted">
            {p.latest_year}:{" "}
            <span
              className={`font-mono font-semibold ${plusMinusClass(headlineMetric)}`}
            >
              {headlineMetric}
            </span>{" "}
            <span className="text-content-secondary">{headlineLabel}</span>
            {p.latest_war !== null && (
              <>
                {" · "}
                <span
                  className={`font-mono font-semibold ${warSeasonClass(p.latest_war)}`}
                >
                  {fmtWar(p.latest_war)}
                </span>{" "}
                <span className="text-content-secondary">WAR</span>
              </>
            )}
          </p>
        )}
      </section>

      {/* Career batting line */}
      {showBatting && (
        <section className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Career batting
          </p>
          <table className="w-full font-mono text-xs tabular-nums">
            <tbody>
              <tr>
                <td className="text-content-muted">G</td>
                <td className="text-right text-content-primary">{p.career_g_bat}</td>
                <td className="pl-3 text-content-muted">PA</td>
                <td className="text-right text-content-primary">{p.career_pa}</td>
                <td className="pl-3 text-content-muted">H</td>
                <td className="text-right text-content-primary">{p.career_h}</td>
              </tr>
              <tr>
                <td className="text-content-muted">HR</td>
                <td className="text-right text-content-primary">{p.career_hr}</td>
                <td className="pl-3 text-content-muted">RBI</td>
                <td className="text-right text-content-primary">{p.career_rbi}</td>
                <td className="pl-3 text-content-muted">SB</td>
                <td className="text-right text-content-primary">{p.career_sb}</td>
              </tr>
              <tr>
                <td className="text-content-muted">AVG</td>
                <td className="text-right text-content-primary">{fmtSlash(p.career_avg)}</td>
                <td className="pl-3 text-content-muted">OBP</td>
                <td className="text-right text-content-primary">{fmtSlash(p.career_obp)}</td>
                <td className="pl-3 text-content-muted">SLG</td>
                <td className="text-right text-content-primary">{fmtSlash(p.career_slg)}</td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      {/* Career pitching line */}
      {showPitching && (
        <section className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Career pitching
          </p>
          <table className="w-full font-mono text-xs tabular-nums">
            <tbody>
              <tr>
                <td className="text-content-muted">G</td>
                <td className="text-right text-content-primary">{p.career_g_pit}</td>
                <td className="pl-3 text-content-muted">W-L</td>
                <td className="text-right text-content-primary">
                  {p.career_w}-{p.career_l}
                </td>
                <td className="pl-3 text-content-muted">SV</td>
                <td className="text-right text-content-primary">{p.career_sv}</td>
              </tr>
              <tr>
                <td className="text-content-muted">IP</td>
                <td className="text-right text-content-primary">{fmtIp(p.career_outs)}</td>
                <td className="pl-3 text-content-muted">SO</td>
                <td className="text-right text-content-primary">{p.career_so}</td>
                <td className="pl-3 text-content-muted">ERA</td>
                <td className="text-right text-content-primary">{fmt2(p.career_era)}</td>
              </tr>
              <tr>
                <td className="text-content-muted">WHIP</td>
                <td className="text-right text-content-primary">{fmt2(p.career_whip)}</td>
                <td className="pl-3" colSpan={4} />
              </tr>
            </tbody>
          </table>
        </section>
      )}
      {/* Suppress unused-var warning when role doesn't drive layout. */}
      <span className="hidden">{isPitcher ? "p" : "b"}</span>
    </article>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Empty state — surfaced when no `ids` arrive (or all parse fails)
// ─────────────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="space-y-6">
      <p className="text-sm text-content-secondary">
        Pick up to 4 players to compare side by side. Pass IDs via the URL:
        <span className="ml-2 font-mono text-content-primary">
          /league/compare?ids=1,2,3
        </span>
        . Try one of these:
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {DEMO_LINKS.map((d) => (
          <Link
            key={d.label}
            href={`/league/compare?ids=${d.ids.join(",")}`}
            className="rounded-md border border-border bg-surface-card p-3 transition hover:border-border-strong hover:bg-surface-elevated"
          >
            <h3 className="text-sm font-semibold text-content-primary">
              {d.label}
            </h3>
            <p className="mt-1 text-xs text-content-secondary">{d.blurb}</p>
          </Link>
        ))}
      </div>
      <p className="border-t border-border pt-4 text-xs text-content-muted">
        IDs are OOTP-internal player_ids — find them on the{" "}
        <Link href="/roster" className="text-link hover:text-link-hover">
          roster
        </Link>{" "}
        page or via the address bar on any{" "}
        <Link href="/player/26166" className="text-link hover:text-link-hover">
          player page
        </Link>
        .
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ ids?: string }>;
}) {
  const params = await searchParams;
  const idsRaw = params.ids ?? "";
  const ids = idsRaw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number.parseInt(s, 10))
    .filter((n) => Number.isFinite(n));

  let data: CompareResponse | null = null;
  if (ids.length > 0) {
    data = await getCompare(ids);
  }

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          League · Compare
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {data && data.players.length > 0
            ? `Compare · ${data.players.map((p) => p.display_name).join(" vs ")}`
            : "Compare players"}
        </h1>
        <p className="text-sm text-content-secondary">
          Side-by-side career stat blocks + overlaid WAR sparklines.
          Cross-era is fair game — D20&apos;s pre-save MLB league baselines
          mean Bonds 2001 / Trout 2018 / Skubal 2029 all carry full
          advanced numbers.
        </p>
      </header>

      {data === null ? (
        <EmptyState />
      ) : data.players.length === 0 ? (
        <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
          None of the requested player IDs resolved to active records. IDs
          tried: {data.not_found.join(", ") || "none"}.
        </p>
      ) : (
        <>
          <div
            className={
              data.players.length === 1
                ? "grid grid-cols-1 gap-4"
                : data.players.length === 2
                  ? "grid grid-cols-1 gap-4 lg:grid-cols-2"
                  : data.players.length === 3
                    ? "grid grid-cols-1 gap-4 lg:grid-cols-3"
                    : "grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4"
            }
          >
            {data.players.map((p) => (
              <CompareCard key={p.player_id} p={p} />
            ))}
          </div>
          {data.not_found.length > 0 && (
            <p className="rounded-md border border-dashed border-border bg-surface-card px-4 py-2 text-xs text-content-muted">
              IDs not found:{" "}
              <span className="font-mono">{data.not_found.join(", ")}</span>{" "}
              — these aren&apos;t in the warehouse&apos;s scoped player set.
            </p>
          )}
        </>
      )}

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        Compare currently caps at 4 players for side-by-side legibility.
        Wider cohort views (cohort scatter, distribution overlays) will
        live as separate Explore modes.
      </p>
    </div>
  );
}
