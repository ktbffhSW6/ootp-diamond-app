// Cockpit dashboard — the front-office "morning coffee" view.
//
// Replaces the old tools-grid landing as of 2026-05-12. Composes:
//   - Save header (identity + warehouse status, kept from previous)
//   - Sox AL East standings strip (with our row pulled out)
//   - Pressure summary — top 3 promotion + top 3 pressure at MLB
//   - Spotlight cards — top 6 Sox by current-year WAR with inline
//     career-WAR sparkline + auto-generated insight
//   - Recent movements — last 8 ledger rows for the current year
//
// Single round-trip via /api/cockpit. Year is implicit (latest);
// historical views live on the dedicated tabs.

import Link from "next/link";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Sparkline } from "@/components/Sparkline";
import { TeamLogo } from "@/components/TeamLogo";
import { plusMinusClass } from "@/lib/heatscale";
import { getCockpit, getSave } from "@/lib/api";
import type {
  CockpitMovementRow,
  CockpitPressureRow,
  CockpitResponse,
  CockpitSpotlightCard,
  CockpitStandingsRow,
} from "@/lib/types/api";

export const metadata = { title: "Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (iso === null) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtCount(n: number): string {
  return n.toLocaleString("en-US");
}

function fmtPct(p: number): string {
  if (!Number.isFinite(p)) return ".000";
  return p.toFixed(3).replace(/^0/, "");
}

function fmtGb(gb: number): string {
  if (gb === 0) return "—";
  return gb.toFixed(1);
}

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

const POSITION_NAMES: Record<number, string> = {
  1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B",
  6: "SS", 7: "LF", 8: "CF", 9: "RF",
};

const MOVEMENT_TYPE_LABEL: Record<string, string> = {
  promotion: "Called up",
  demotion: "Sent down",
  trade: "Traded",
  intra_org_lateral: "Reassigned",
  signed: "Signed",
  released: "Released",
  waiver_or_other: "Waiver",
  first_appearance: "Joined org",
};

const DIRECTION_COLOR: Record<string, string> = {
  internal: "text-sky-700 dark:text-sky-400",
  incoming: "text-emerald-700 dark:text-emerald-400",
  outgoing: "text-rose-700 dark:text-rose-400",
};

// ─────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────

function SectionHeader({
  title,
  subtitle,
  href,
  hrefLabel,
}: {
  title: string;
  subtitle?: string;
  href?: string;
  hrefLabel?: string;
}) {
  return (
    <header className="mb-3 flex items-baseline justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold text-content-primary">{title}</h2>
        {subtitle && (
          <p className="text-xs text-content-muted">{subtitle}</p>
        )}
      </div>
      {href && (
        <Link
          href={href}
          className="text-xs text-link hover:text-link-hover hover:underline"
        >
          {hrefLabel ?? "View all"} →
        </Link>
      )}
    </header>
  );
}

// ─── Standings strip ─────────────────────────────────────────────────

function StandingsRow({ row }: { row: CockpitStandingsRow }) {
  const orgRowClass = row.is_user_org
    ? "border-l-2 border-l-accent bg-surface-elevated/60"
    : "border-l-2 border-l-transparent";
  const teamLabel = row.nickname ?? row.abbr ?? `Team ${row.team_id}`;
  return (
    <tr className={`${orgRowClass} border-t border-border`}>
      <td className="px-3 py-1.5 align-middle">
        <div className="flex items-center gap-2">
          <TeamLogo teamId={row.team_id} abbr={row.abbr} size="md" />
          <span className="font-mono text-xs text-content-muted">
            {row.abbr ?? "—"}
          </span>
          <span className="text-sm font-medium text-content-primary">
            {teamLabel}
          </span>
          {row.is_user_org && (
            <span className="text-[10px] uppercase tracking-wider text-accent">
              You
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
        {row.w}-{row.l}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
        {fmtPct(row.pct)}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
        {fmtGb(row.gb)}
      </td>
      <td className={`px-3 py-1.5 text-right font-mono text-sm tabular-nums ${streakClass(row.streak)}`}>
        {fmtStreak(row.streak)}
      </td>
    </tr>
  );
}

// ─── Pressure summary ────────────────────────────────────────────────

function PressureRow({
  row,
  side,
}: {
  row: CockpitPressureRow;
  side: "promotion" | "pressure";
}) {
  const roleChip =
    row.role === "batter"
      ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
      : "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300";
  const metricLabel = row.role === "batter" ? "OPS+" : "ERA+";
  return (
    <li className="flex items-baseline gap-2 border-t border-border py-1.5 first:border-t-0">
      <span
        className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide ${roleChip}`}
      >
        {row.role === "batter" ? "B" : "P"}
      </span>
      <Link
        href={`/player/${row.player_id}`}
        className="flex-1 truncate text-sm font-medium text-link hover:text-link-hover hover:underline"
      >
        {row.display_name}
      </Link>
      <span className="font-mono text-[10px] text-content-muted">{row.sample}</span>
      <span
        className={`font-mono text-sm font-semibold tabular-nums ${plusMinusClass(row.metric)}`}
        title={`${metricLabel} ${row.metric}`}
      >
        {row.metric}
      </span>
    </li>
  );
}

// ─── Spotlight card ──────────────────────────────────────────────────

function SpotlightCard({ card }: { card: CockpitSpotlightCard }) {
  // Build the sparkline series, padding gaps for years with no data
  // (e.g., Tommy John recovery). Career-WAR list already has nulls
  // for missing years per the API contract.
  const values: (number | null)[] = card.career_war;
  const positionLabel =
    card.role === "two-way" ? "TWO" : POSITION_NAMES[card.position] ?? "—";
  const headlineColor = plusMinusClass(card.headline_metric_value);
  return (
    <Link
      href={`/player/${card.player_id}`}
      className="block rounded-md border border-border bg-surface-card p-3 transition hover:border-border-strong hover:bg-surface-elevated"
    >
      <div className="flex items-center gap-2">
        <PlayerAvatar
          playerId={card.player_id}
          displayName={card.display_name}
          size="sm"
        />
        <span className="rounded bg-surface-elevated px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide text-content-muted">
          {positionLabel}
        </span>
        <h3 className="flex-1 truncate text-sm font-semibold text-content-primary">
          {card.display_name}
        </h3>
        <TeamLogo teamId={card.team_id} abbr={card.team_abbr} size="sm" />
        <span className="font-mono text-[10px] text-content-muted">
          {card.team_abbr ?? "—"}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <div>
          <div className={`font-mono text-2xl font-semibold tabular-nums ${headlineColor}`}>
            {card.headline_metric_value}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-content-muted">
            {card.headline_metric_label} · {card.sample}
          </div>
        </div>
        <div className="ml-auto flex flex-col items-end">
          <Sparkline
            values={values}
            width={120}
            height={32}
            label={`Career WAR — ${card.career_years[0]} to ${card.career_years[card.career_years.length - 1]}`}
          />
          <div className="mt-0.5 font-mono text-[10px] text-content-muted">
            <span className="font-semibold text-content-secondary">
              {card.war_current >= 0 ? "+" : ""}
              {card.war_current.toFixed(1)}
            </span>{" "}
            WAR · career arc
          </div>
        </div>
      </div>
      {card.insight && (
        <p className="mt-2 border-t border-border pt-2 text-xs italic text-content-secondary">
          {card.insight}
        </p>
      )}
    </Link>
  );
}

// ─── Recent movements feed ───────────────────────────────────────────

function MovementRow({ row }: { row: CockpitMovementRow }) {
  const verb = MOVEMENT_TYPE_LABEL[row.movement_type] ?? row.movement_type;
  const dirClass = DIRECTION_COLOR[row.direction] ?? "text-content-secondary";
  const teamPath =
    row.direction === "incoming"
      ? `→ ${row.to_team_abbr ?? "—"}`
      : row.direction === "outgoing"
        ? `${row.from_team_abbr ?? "—"} →`
        : `${row.from_team_abbr ?? "—"} → ${row.to_team_abbr ?? "—"}`;
  return (
    <li className="flex items-baseline gap-3 border-t border-border py-1.5 first:border-t-0">
      <span className="font-mono text-[10px] text-content-muted">
        {fmtDate(row.movement_date)}
      </span>
      <span className={`font-mono text-[10px] uppercase tracking-wider ${dirClass}`}>
        {verb}
      </span>
      <Link
        href={`/player/${row.player_id}`}
        className="flex-1 truncate text-sm font-medium text-link hover:text-link-hover hover:underline"
      >
        {row.display_name}
      </Link>
      <span className="font-mono text-xs text-content-muted">{teamPath}</span>
    </li>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function CockpitPage() {
  const [save, cockpit] = await Promise.all([getSave(), getCockpit()]);
  const data: CockpitResponse = cockpit;

  const orgLabel = save.org_team_nickname
    ? `${save.org_team_abbr ?? ""} ${save.org_team_nickname}`.trim()
    : (save.org_team_abbr ?? `Team ${save.org_team_id}`);

  return (
    <div className="space-y-4">
      {/* ── Header — save identity ───────────────────────────────── */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-3">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Front office
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            {orgLabel}
            {save.latest_season !== null && (
              <span className="ml-2 text-sm font-normal text-content-secondary">
                · {save.latest_season} season
              </span>
            )}
          </h1>
        </div>
        <p className="font-mono text-xs text-content-muted">{save.save_name}</p>
      </header>

      {/* ── Warehouse status row ─────────────────────────────────── */}
      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Dumps tracked"
          value={fmtCount(save.dump_count)}
          sub={
            save.latest_dump_name
              ? `Latest: ${save.latest_dump_name.replace("dump_", "")}`
              : "—"
          }
        />
        <Stat
          label="Last sync"
          value={fmtDate(save.latest_dump_date)}
          sub={save.latest_dump_date ? "Most recent dump" : "No ingests yet"}
        />
        <Stat
          label="Players in scope"
          value={fmtCount(save.scoped_player_count)}
          sub={`Across ${fmtCount(save.scoped_team_count)} teams`}
        />
        <Stat
          label="Seasons covered"
          value={
            save.earliest_season !== null && save.latest_season !== null
              ? `${save.earliest_season}–${save.latest_season}`
              : "—"
          }
          sub="Pre-save history + in-save"
        />
      </section>

      {/* ── Cockpit row 1: Standings + Pressure summary ─────────── */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Standings strip */}
        <section className="rounded-md border border-border bg-surface-card p-4">
          <SectionHeader
            title={data.standings?.division_name ?? "Division"}
            subtitle={
              data.standings
                ? `Standings as of ${fmtDate(data.standings.snapshot_date)}`
                : "No standings data"
            }
            href="/league"
            hrefLabel="Full standings"
          />
          {data.standings && data.standings.rows.length > 0 ? (
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
                  <th className="px-3 py-1.5 text-left font-medium">Team</th>
                  <th className="px-3 py-1.5 text-right font-medium">W-L</th>
                  <th className="px-3 py-1.5 text-right font-medium">Pct</th>
                  <th className="px-3 py-1.5 text-right font-medium">GB</th>
                  <th className="px-3 py-1.5 text-right font-medium">Strk</th>
                </tr>
              </thead>
              <tbody>
                {data.standings.rows.map((r) => (
                  <StandingsRow key={r.team_id} row={r} />
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-xs text-content-muted">
              No standings rows available yet.
            </p>
          )}
        </section>

        {/* Pressure summary */}
        <section className="rounded-md border border-border bg-surface-card p-4">
          <SectionHeader
            title="MLB Pressure"
            subtitle="Top performers vs strugglers, who should move"
            href="/pressure"
            hrefLabel="Full board"
          />
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 lg:grid-cols-2">
            <div>
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                ↑ Promotion
              </h3>
              {data.pressure.promotion.length > 0 ? (
                <ul>
                  {data.pressure.promotion.map((row) => (
                    <PressureRow key={`p-${row.player_id}-${row.role}`} row={row} side="promotion" />
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-content-muted">No qualifiers yet.</p>
              )}
            </div>
            <div>
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-400">
                ↓ Pressure
              </h3>
              {data.pressure.pressure.length > 0 ? (
                <ul>
                  {data.pressure.pressure.map((row) => (
                    <PressureRow key={`pr-${row.player_id}-${row.role}`} row={row} side="pressure" />
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-content-muted">No qualifiers yet.</p>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* ── Cockpit row 2: Spotlight cards ──────────────────────── */}
      <section>
        <SectionHeader
          title="Spotlight"
          subtitle={`Top ${data.spotlight.length} ${orgLabel} players by ${data.year} WAR — career arc + insight`}
          href="/roster"
          hrefLabel="Full roster"
        />
        {data.spotlight.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
            {data.spotlight.map((card) => (
              <SpotlightCard key={card.player_id} card={card} />
            ))}
          </div>
        ) : (
          <p className="rounded-md border border-border bg-surface-card px-4 py-3 text-sm text-content-muted">
            No spotlight players for {data.year} yet.
          </p>
        )}
      </section>

      {/* ── Cockpit row 3: Recent movements ─────────────────────── */}
      <section className="rounded-md border border-border bg-surface-card p-4">
        <SectionHeader
          title="Recent moves"
          subtitle={`Latest ledger activity in ${data.year}`}
          href="/movements"
          hrefLabel="Full ledger"
        />
        {data.recent_movements.length > 0 ? (
          <ul>
            {data.recent_movements.map((row) => (
              <MovementRow key={row.movement_id} row={row} />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-content-muted">
            No movements recorded for {data.year}.
          </p>
        )}
      </section>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <p className="border-t border-border pt-4 text-xs text-content-muted">
        Cockpit composes <Link href="/league" className="text-link hover:text-link-hover">standings</Link>,{" "}
        <Link href="/pressure" className="text-link hover:text-link-hover">pressure board</Link>,{" "}
        <Link href="/roster" className="text-link hover:text-link-hover">roster</Link>, and{" "}
        <Link href="/movements" className="text-link hover:text-link-hover">movement ledger</Link>{" "}
        into one view. Year is implicit (latest);
        historical snapshots live on the dedicated tabs.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-card px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
        {label}
      </p>
      <p className="mt-0.5 text-base font-semibold tabular-nums leading-tight text-content-primary">
        {value}
      </p>
      <p className="mt-0.5 text-[11px] leading-tight text-content-muted">{sub}</p>
    </div>
  );
}
