// History · Streaks — top-50 holders per (streak_id × scope).
//
// Backed by `GET /api/streaks?streak_id=&scope=`. Two pickers:
// streak type (21 codes from f_player_streak — Hitting / Scoreless
// Innings / On-Base / Win / etc.) × scope (active | all_time).
// Active streaks are alive in the latest dump's snapshot; all-time
// includes every streak ever observed (active + ended).
//
// Defaults: streak_id=0 (Hitting Streak), scope=all_time, limit=25.
// Bad query strings fall back to defaults.

import Link from "next/link";

import { getStreaks } from "@/lib/api";
import type {
  StreakCategoryRef,
  StreakRow,
  StreaksResponse,
} from "@/lib/types/api";

export const metadata = { title: "Streaks — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// URL builder + picker rows
// ─────────────────────────────────────────────────────────────────────

function buildHref(args: { streakId: number; scope: string }): string {
  const params = new URLSearchParams({
    streak_id: String(args.streakId),
    scope: args.scope,
  });
  return `/history/streaks?${params.toString()}`;
}

function StreakPicker({
  available,
  current,
  scope,
}: {
  available: StreakCategoryRef[];
  current: number;
  scope: string;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Streak
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {available.map((s) => {
          const active = s.streak_id === current;
          return (
            <Link
              key={s.streak_id}
              href={buildHref({ streakId: s.streak_id, scope })}
              title={s.label}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {s.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

const SCOPE_OPTIONS = ["all_time", "active"] as const;
const SCOPE_LABEL: Record<string, string> = {
  all_time: "All-Time",
  active: "Active",
};
const SCOPE_TOOLTIP: Record<string, string> = {
  all_time:
    "Every streak ever observed in the latest dump's players_streak.csv (active + ended).",
  active: "Streaks currently alive in the latest dump's snapshot.",
};

function ScopePicker({
  current,
  streakId,
  visibleScopes,
}: {
  current: string;
  streakId: number;
  visibleScopes: readonly string[];
}) {
  if (visibleScopes.length <= 1) return null;
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        Scope
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {visibleScopes.map((s) => {
          const active = s === current;
          return (
            <Link
              key={s}
              href={buildHref({ streakId, scope: s })}
              title={SCOPE_TOOLTIP[s]}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {SCOPE_LABEL[s] ?? s}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Streak table
// ─────────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  // ISO date string from API. Render short-form so the cell stays
  // narrow.
  // Date-only strings ("2028-07-01") would otherwise be parsed as UTC
  // midnight and shift to the prior day in any TZ west of UTC.
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const dt = dateOnly
    ? (() => {
        const [y, m, d] = iso.split("-").map(Number);
        return new Date(y, m - 1, d);
      })()
    : new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtEnded(ended: string | null): string {
  if (!ended) return "—";
  // OOTP's date format ("2028-7-29") doesn't always zero-pad single-
  // digit months — reformat for display.
  const m = ended.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (!m) return ended;
  const [, year, month, day] = m;
  const dt = new Date(`${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`);
  if (Number.isNaN(dt.getTime())) return ended;
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function StreakTable({ rows }: { rows: StreakRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
        No streaks for this combination.
      </p>
    );
  }
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Rank within scope"
            >
              #
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Player</th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Streak length (games / innings / etc.)"
            >
              Length
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Started</th>
            <th className="px-3 py-1.5 text-left font-medium">Ended</th>
            <th className="px-3 py-1.5 text-left font-medium">Team</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const linkable = row.player_id !== null;
            const nameCell = linkable ? (
              <Link
                href={`/player/${row.player_id}`}
                className="font-medium text-link hover:text-link-hover hover:underline"
              >
                {row.display_name}
              </Link>
            ) : (
              <span className="font-medium text-content-primary">
                {row.display_name}
              </span>
            );
            return (
              <tr
                key={`${row.rank}-${row.player_id ?? row.display_name}-${row.value}`}
                className="border-t border-border hover:bg-surface-elevated"
              >
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-muted">
                  {row.rank}
                </td>
                <td className="px-3 py-1.5 align-middle">{nameCell}</td>
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                  {row.value}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs tabular-nums text-content-secondary">
                  {fmtDate(row.started)}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs tabular-nums">
                  {row.has_ended ? (
                    <span className="text-content-secondary">
                      {fmtEnded(row.ended)}
                    </span>
                  ) : (
                    <span
                      className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                      title="Streak still active in the latest dump"
                    >
                      Live
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs text-content-muted">
                  {row.team_abbr ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function StreaksPage({
  searchParams,
}: {
  searchParams: Promise<{ streak_id?: string; scope?: string }>;
}) {
  const params = await searchParams;
  const data: StreaksResponse = await getStreaks({
    streakId: params.streak_id ? Number(params.streak_id) : undefined,
    scope:
      params.scope === "active" || params.scope === "all_time"
        ? params.scope
        : undefined,
  });

  const activeStreak: StreakCategoryRef | undefined =
    data.available_streaks.find((s) => s.streak_id === data.streak_id);
  const visibleScopes = SCOPE_OPTIONS.filter((s) => {
    if (!activeStreak) return s === "all_time";
    return activeStreak.available_scopes.includes(s);
  });

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          History · Streaks
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {data.streak_label} — {SCOPE_LABEL[data.scope]} Top {data.rows.length}
        </h1>
        <p className="text-sm text-content-secondary">
          {data.scope === "all_time" ? (
            <>
              Every {data.streak_label.toLowerCase()} ever observed in the
              save (active + ended). Top-50 ranks are pre-cut at L3 build
              time; this view shows the top {data.rows.length} of {data.total_in_scope}.
            </>
          ) : (
            <>
              {data.streak_label} streaks alive in the latest dump's
              snapshot. Top {data.rows.length} of {data.total_in_scope} active.
            </>
          )}
        </p>
      </header>

      <div className="space-y-6">
        <ScopePicker
          current={data.scope}
          streakId={data.streak_id}
          visibleScopes={visibleScopes}
        />
        <StreakPicker
          available={data.available_streaks}
          current={data.streak_id}
          scope={data.scope}
        />
      </div>

      <StreakTable rows={data.rows} />

      <section className="space-y-2 border-t border-border pt-6 text-xs text-content-muted">
        <p>
          <strong>Active streaks</strong> are alive at the time of the
          latest monthly dump — they may have ended in OOTP's running
          season since. The "Live" badge marks them; ended streaks show
          their actual ended date.
        </p>
        <p>
          <strong>All-Time</strong> includes every streak ever observed
          in the save (the dump retains finished streaks indefinitely).
          Active streaks naturally appear in both scopes — same player,
          same length.
        </p>
        <p>
          <strong>Streak labels</strong> are best-guess decoded from the
          ``streak_id`` codebook (see{" "}
          <code>diamond.constants.StreakId</code>). Codes 17 / 18 / 11
          carry rare-streak rows whose semantics aren't fully decoded;
          their leaderboards are surfaced verbatim from the dump.
        </p>
      </section>
    </div>
  );
}
