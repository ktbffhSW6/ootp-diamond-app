// Movement-ledger page — the GM-sidekick flagship per UI_DESIGN.md.
//
// Backed by `GET /api/movements?year=YYYY`. Renders one row per
// intra-org promotion / demotion in the user's org for the season,
// with before/after performance and a verdict glyph (working /
// reconsider / struggling / too_small).
//
// v1 cuts:
// - Org is hardcoded by the backend (active SaveConfig.audit_team_id =
//   Red Sox = 4 in BUILDING_THE_GREEN_MONSTER).
// - Trade pickups, FA signings, releases — deferred. Promotion +
//   demotion are the only types where before/after-at-the-org is well
//   defined.
// - Year picker is a server-rendered <Link> grid (no client state)
//   driven by `available_seasons` in the response.
//
// Per the player page convention: this page is `force-dynamic` so
// Next's build-time prerender doesn't try to hit uvicorn.

import Link from "next/link";

import { TeamLogo } from "@/components/TeamLogo";
import { getMovements } from "@/lib/api";
import type {
  MovementBattingStats,
  MovementPitchingStats,
  MovementRow,
} from "@/lib/types/api";

export const metadata = {
  title: "Movement ledger — Diamond",
};

export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Verdict styling
// ─────────────────────────────────────────────────────────────────────

const VERDICT_GLYPH: Record<string, string> = {
  working: "🟢",
  reconsider: "🟡",
  struggling: "🔴",
  too_small: "⚪",
};

const VERDICT_LABEL: Record<string, string> = {
  working: "working",
  reconsider: "reconsider",
  struggling: "struggling",
  too_small: "too early",
};

// ─────────────────────────────────────────────────────────────────────
// Stat-formatting helpers
// ─────────────────────────────────────────────────────────────────────

function fmtBatLine(s: MovementBattingStats | null): string {
  if (s === null) return "—";
  const ops = s.ops_plus !== null ? `${s.ops_plus} OPS+` : "— OPS+";
  return `${ops} · ${s.pa} PA`;
}

function fmtPitLine(s: MovementPitchingStats | null): string {
  if (s === null) return "—";
  const era = s.era_plus !== null ? `${s.era_plus} ERA+` : "— ERA+";
  const ip = s.ip_display !== null ? s.ip_display.toFixed(1) : "—";
  return `${era} · ${ip} IP`;
}

function MoveArrow({ row }: { row: MovementRow }) {
  // Three shapes depending on direction:
  //   - internal (promotion/demotion): "MLB → AAA Worcester" — leading
  //     anchor is the level so the up/down step reads at a glance.
  //   - incoming acquisition: "CLE → MLB" / "FA → AAA Worcester" —
  //     leading anchor is the prior team or "FA" for signings.
  //   - outgoing departure: "MLB → CLE" / "MLB → FA" — leading anchor
  //     is *our* level; destination is the other team's abbr.
  //
  // Slice B: render real OOTP logos on either side of the arrow when
  // both teams have a team_id; fall back to text-only otherwise.
  const Sep = () => <span className="text-content-muted">→</span>;
  const FA = () => (
    <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-700 dark:bg-sky-900/40 dark:text-sky-300">
      FA
    </span>
  );

  if (row.direction === "internal") {
    return (
      <div className="flex items-center gap-1.5">
        <TeamLogo teamId={row.from_team.team_id} abbr={row.from_team.abbr} size="sm" />
        <span className="text-content-secondary">{row.from_team.level_name ?? "?"}</span>
        <Sep />
        <TeamLogo teamId={row.to_team.team_id} abbr={row.to_team.abbr} size="sm" />
        <span className="text-content-secondary">
          {row.to_team.level_name ?? "?"}
          {row.to_team.nickname ? ` ${row.to_team.nickname}` : ""}
        </span>
      </div>
    );
  }
  if (row.direction === "incoming") {
    if (row.movement_type === "signed") {
      return (
        <div className="flex items-center gap-1.5">
          <FA />
          <Sep />
          <TeamLogo teamId={row.to_team.team_id} abbr={row.to_team.abbr} size="sm" />
          <span className="text-content-secondary">
            {row.to_team.level_name ?? "?"}
            {row.to_team.nickname ? ` ${row.to_team.nickname}` : ""}
          </span>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-1.5">
        <TeamLogo teamId={row.from_team.team_id} abbr={row.from_team.abbr} size="sm" />
        <span className="text-content-secondary">
          {row.from_team.abbr ?? row.from_team.level_name ?? "?"}
        </span>
        <Sep />
        <TeamLogo teamId={row.to_team.team_id} abbr={row.to_team.abbr} size="sm" />
        <span className="text-content-secondary">
          {row.to_team.level_name ?? "?"}
          {row.to_team.nickname ? ` ${row.to_team.nickname}` : ""}
        </span>
      </div>
    );
  }
  // outgoing — the "from" is our team, the "to" is wherever they went
  if (row.movement_type === "released") {
    return (
      <div className="flex items-center gap-1.5">
        <TeamLogo teamId={row.from_team.team_id} abbr={row.from_team.abbr} size="sm" />
        <span className="text-content-secondary">{row.from_team.level_name ?? "?"}</span>
        <Sep />
        <FA />
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      <TeamLogo teamId={row.from_team.team_id} abbr={row.from_team.abbr} size="sm" />
      <span className="text-content-secondary">{row.from_team.level_name ?? "?"}</span>
      <Sep />
      <TeamLogo teamId={row.to_team.team_id} abbr={row.to_team.abbr} size="sm" />
      <span className="text-content-secondary">
        {row.to_team.abbr ?? row.to_team.nickname ?? "?"}
      </span>
    </div>
  );
}

// Move-type badges. Each accent color carries `dark:` overrides so it
// reads sensibly on the slate-900 dark surface. Tailwind's
// `darkMode: ["class", '[data-theme="dark"]']` config means `dark:`
// utilities only fire when the dark theme is active, so light /
// neutral / cb still render the soft pastel originals.
const MOVE_BADGE: Record<
  string,
  { label: string; classes: string }
> = {
  promotion: {
    label: "Up",
    classes:
      "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  },
  demotion: {
    label: "Down",
    classes:
      "bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  },
  trade: {
    label: "Trade",
    classes:
      "bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300",
  },
  signed: {
    label: "FA",
    classes: "bg-sky-50 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  },
  waiver_or_other: {
    label: "Waiver",
    classes:
      "bg-slate-100 text-slate-700 dark:bg-slate-700/40 dark:text-slate-300",
  },
  released: {
    label: "Released",
    classes: "bg-rose-50 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  },
};

function fmtDate(d: string): string {
  // ISO date string from the API. Render as "Jun 12" (no year — the
  // page header already shows the season).
  const dt = new Date(d);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─────────────────────────────────────────────────────────────────────
// Subcomponents
// ─────────────────────────────────────────────────────────────────────

function buildHref(year: number, latestYear: number, includePending: boolean): string {
  // Default URL `/movements` shorthand for "latest year, no pending".
  // Anything non-default gets explicit query params for shareability.
  const params: string[] = [];
  if (year !== latestYear) params.push(`year=${year}`);
  if (includePending) params.push("include_pending=1");
  return params.length === 0 ? "/movements" : `/movements?${params.join("&")}`;
}

function YearPicker({
  available,
  current,
  includePending,
}: {
  available: number[];
  current: number;
  includePending: boolean;
}) {
  if (available.length <= 1) return null;
  const latest = available[0];
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-content-muted">Season:</span>
      {available.map((y) => {
        const active = y === current;
        return (
          <Link
            key={y}
            href={buildHref(y, latest, includePending)}
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
  );
}

function PendingToggle({
  current,
  latest,
  includePending,
  pendingCount,
}: {
  current: number;
  latest: number;
  includePending: boolean;
  pendingCount: number;
}) {
  if (pendingCount === 0 && !includePending) return null;
  if (includePending) {
    return (
      <Link
        href={buildHref(current, latest, false)}
        className="text-xs text-link underline-offset-2 hover:text-link-hover hover:underline"
      >
        Hide {pendingCount} pending move{pendingCount === 1 ? "" : "s"} (under sample threshold)
      </Link>
    );
  }
  return (
    <Link
      href={buildHref(current, latest, true)}
      className="text-xs text-link underline-offset-2 hover:text-link-hover hover:underline"
    >
      Show {pendingCount} pending move{pendingCount === 1 ? "" : "s"} (under sample threshold)
    </Link>
  );
}

function Row({ row }: { row: MovementRow }) {
  const beforeStr =
    row.role === "batter"
      ? fmtBatLine(row.before_batting)
      : fmtPitLine(row.before_pitching);
  const afterStr =
    row.role === "batter"
      ? fmtBatLine(row.after_batting)
      : fmtPitLine(row.after_pitching);
  const badge = MOVE_BADGE[row.movement_type] ?? {
    label: row.movement_type,
    classes:
      "bg-slate-100 text-slate-700 dark:bg-slate-700/40 dark:text-slate-300",
  };
  const moveBadge = (
    <span
      className={`rounded ${badge.classes} px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide`}
    >
      {badge.label}
    </span>
  );

  return (
    <tr className="border-t border-border hover:bg-surface-elevated">
      <td className="px-3 py-2 align-top text-sm text-content-secondary whitespace-nowrap">
        {fmtDate(row.dump_date_observed)}
      </td>
      <td className="px-3 py-2 align-top">
        <Link
          href={`/player/${row.player_id}`}
          className="font-medium text-link underline-offset-2 hover:text-link-hover hover:underline"
        >
          {row.player_name}
        </Link>
        <span className="ml-2 font-mono text-xs text-content-muted">
          {row.primary_position}
        </span>
      </td>
      <td className="px-3 py-2 align-top whitespace-nowrap">
        <div className="flex items-center gap-2 text-sm">
          {moveBadge}
          <MoveArrow row={row} />
        </div>
      </td>
      <td className="px-3 py-2 align-top font-mono text-xs text-content-secondary whitespace-nowrap">
        {beforeStr}
      </td>
      <td className="px-3 py-2 align-top font-mono text-xs text-content-primary whitespace-nowrap">
        {afterStr}
      </td>
      <td className="px-3 py-2 align-top">
        <div className="flex items-baseline gap-2">
          <span aria-hidden>{VERDICT_GLYPH[row.verdict]}</span>
          <span className="text-xs font-medium uppercase tracking-wide text-content-secondary">
            {VERDICT_LABEL[row.verdict]}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-content-muted">{row.verdict_note}</div>
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function MovementsPage({
  searchParams,
}: {
  // Next 15 typed search params: server components see them as a Promise.
  searchParams: Promise<{ year?: string; include_pending?: string }>;
}) {
  const { year: yearParam, include_pending } = await searchParams;
  const year = yearParam ? Number(yearParam) : undefined;
  // Pending = verdict "too_small". Hidden by default since EOS roster
  // shuffles flood the view with no-sample rows; toggle reveals them.
  const includePending = include_pending === "1";
  const data = await getMovements(year);

  const orgLabel = data.org_team_nickname
    ? `${data.org_team_abbr ?? ""} ${data.org_team_nickname}`.trim()
    : (data.org_team_abbr ?? `Team ${data.org_team_id}`);

  // Filter pending unless toggle is on. We compute a single visible set
  // and bucket-count over both visible and hidden so the toggle CTA can
  // tell the user how many they're hiding.
  const visibleRows = includePending
    ? data.rows
    : data.rows.filter((r) => r.verdict !== "too_small");
  const pendingCount = data.rows.filter((r) => r.verdict === "too_small").length;

  const promotions = visibleRows.filter(
    (r) => r.direction === "internal" && r.movement_type === "promotion",
  );
  const demotions = visibleRows.filter(
    (r) => r.direction === "internal" && r.movement_type === "demotion",
  );
  const acquisitions = visibleRows.filter((r) => r.direction === "incoming");
  const departures = visibleRows.filter((r) => r.direction === "outgoing");
  const latest = data.available_seasons[0] ?? data.season;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Club · Movements
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            {orgLabel}
            <span className="ml-2 text-sm font-normal text-content-secondary">
              · {data.season}
            </span>
          </h1>
        </div>
        <p className="text-xs text-content-muted">
          Verdict on OPS+ (batters) / ERA+ (pitchers); MLB ≥100 working, MiLB ≥90.
          Departures invert — 🔴 = let good player go.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4">
        <YearPicker
          available={data.available_seasons}
          current={data.season}
          includePending={includePending}
        />
        <PendingToggle
          current={data.season}
          latest={latest}
          includePending={includePending}
          pendingCount={pendingCount}
        />
      </div>

      {data.rows.length === 0 ? (
        <p className="text-sm text-content-muted">
          No movements recorded for this season yet.
        </p>
      ) : (
        <>
          <Section
            title="Call-ups"
            subtitle={`${promotions.length} promotion${promotions.length === 1 ? "" : "s"}`}
            rows={promotions}
            beforeHeader="Before (prior level)"
            afterHeader="After (new level)"
          />
          <Section
            title="Send-downs"
            subtitle={`${demotions.length} demotion${demotions.length === 1 ? "" : "s"}`}
            rows={demotions}
            beforeHeader="Before (prior level)"
            afterHeader="After (new level)"
          />
          <Section
            title="Acquisitions"
            subtitle={`${acquisitions.length} trade${acquisitions.length === 1 ? "" : "s"}/signing${acquisitions.length === 1 ? "" : "s"} from outside the org`}
            rows={acquisitions}
            beforeHeader="Before (prior org)"
            afterHeader="After (with us)"
          />
          <Section
            title="Departures"
            subtitle={`${departures.length} release${departures.length === 1 ? "" : "s"}/trade${departures.length === 1 ? "" : "s"} out`}
            rows={departures}
            beforeHeader="Before (with us)"
            afterHeader="After (elsewhere)"
          />
        </>
      )}

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        v1 caveats: before / after stats are season-totals at each level,
        so multi-stint years conflate stints. Two-way players are evaluated
        on their primary position only. Acquisition before-stats reflect
        the player's prior org / level for the same season; FA signings
        with no prior team this year show a dash. Outgoing moves
        (releases, trades away) are deferred to a follow-up tab.
      </p>
    </div>
  );
}

function Section({
  title,
  subtitle,
  rows,
  beforeHeader,
  afterHeader,
}: {
  title: string;
  subtitle: string;
  rows: MovementRow[];
  beforeHeader: string;
  afterHeader: string;
}) {
  if (rows.length === 0) {
    return (
      <section>
        <h2 className="mb-3 text-lg font-semibold text-content-primary">
          {title}{" "}
          <span className="text-sm font-normal text-content-muted">({subtitle})</span>
        </h2>
        <p className="text-sm text-content-muted">No moves in this direction.</p>
      </section>
    );
  }
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-content-primary">
        {title}{" "}
        <span className="text-sm font-normal text-content-muted">({subtitle})</span>
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-surface-elevated text-left text-xs uppercase tracking-wide text-content-muted">
              <th className="px-3 py-2 font-medium">Date</th>
              <th className="px-3 py-2 font-medium">Player</th>
              <th className="px-3 py-2 font-medium">Move</th>
              <th className="px-3 py-2 font-medium">{beforeHeader}</th>
              <th className="px-3 py-2 font-medium">{afterHeader}</th>
              <th className="px-3 py-2 font-medium">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Row key={r.movement_id} row={r} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
