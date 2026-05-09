"use client";

// RefreshButton — header-bar control for picking up newly-arrived
// dumps mid-session.
//
// Polls `/api/admin/dump-status` every 60 seconds. When the API
// reports `pending_count > 0`, an amber badge appears on the button
// with the pending count. Click to trigger
// `POST /api/admin/ingest` — synchronous; the API blocks the UI's
// other tabs during the ingest (could be 30s-3min depending on
// pending count), then unblocks them with fresh data.
//
// States:
//   - **idle (no pending)**: muted "↻" with no badge
//   - **idle (pending)**: amber "↻" + count badge
//   - **ingesting**: spinning "↻" + "Ingesting…" tooltip
//   - **error**: rose "!" badge with error tooltip; click resets

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { getDumpStatus, triggerIngest } from "@/lib/api";

type Phase =
  | { kind: "idle"; pending: number; latest: string | null }
  | { kind: "loading" }
  | { kind: "ingesting" }
  | { kind: "ok"; ingested: number; elapsed: number; pending: number; latest: string | null }
  | { kind: "err"; message: string };

const POLL_INTERVAL_MS = 60_000;

export function RefreshButton() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load + recurring poll
  useEffect(() => {
    let cancelled = false;
    async function refreshStatus() {
      try {
        const s = await getDumpStatus();
        if (cancelled) return;
        setPhase({
          kind: "idle",
          pending: s.pending_count,
          latest: s.latest_ingested_dump,
        });
      } catch {
        // Don't surface poll errors as a hard error — the API may be
        // briefly unreachable (e.g., during ingest), and we'll retry
        // on next poll.
      }
    }
    refreshStatus();
    pollTimer.current = setInterval(refreshStatus, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, []);

  async function onClick() {
    setPhase({ kind: "ingesting" });
    try {
      const result = await triggerIngest();
      // Re-check status after ingest so the badge reflects reality
      const s = await getDumpStatus();
      setPhase({
        kind: "ok",
        ingested: result.ingested.length,
        elapsed: result.elapsed_seconds,
        pending: s.pending_count,
        latest: s.latest_ingested_dump,
      });
      // Refresh server-rendered pages so the new data shows everywhere.
      router.refresh();
      // Auto-clear the "ok" toast after a few seconds, returning to
      // idle so the count badge tracks future polling.
      setTimeout(
        () =>
          setPhase({
            kind: "idle",
            pending: s.pending_count,
            latest: s.latest_ingested_dump,
          }),
        5000,
      );
    } catch (e) {
      setPhase({
        kind: "err",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  // Render variants ────────────────────────────────────────────────
  if (phase.kind === "loading") {
    return (
      <span className="text-xs text-content-muted" title="Checking ingest status…">
        ↻
      </span>
    );
  }

  if (phase.kind === "ingesting") {
    return (
      <button
        disabled
        className="flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 dark:text-amber-300"
        title="Ingesting new dumps… this can take a few minutes."
      >
        <SpinnerGlyph />
        <span>Ingesting…</span>
      </button>
    );
  }

  if (phase.kind === "err") {
    return (
      <button
        onClick={() =>
          setPhase({ kind: "idle", pending: 0, latest: null })
        }
        className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-700 dark:text-rose-300"
        title={phase.message}
      >
        ! Refresh failed (click to dismiss)
      </button>
    );
  }

  if (phase.kind === "ok") {
    return (
      <button
        onClick={onClick}
        className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300"
        title={`Ingested ${phase.ingested} new dump${phase.ingested === 1 ? "" : "s"} in ${phase.elapsed.toFixed(1)}s. Click to re-check.`}
      >
        ✓ Refreshed ({phase.ingested})
      </button>
    );
  }

  // idle
  const hasPending = phase.pending > 0;
  return (
    <button
      onClick={onClick}
      className={
        hasPending
          ? "flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-700 hover:bg-amber-500/20 dark:text-amber-300"
          : "rounded border border-border bg-surface-page px-2 py-1 text-xs text-content-secondary hover:border-border-strong"
      }
      title={
        hasPending
          ? `${phase.pending} new dump${phase.pending === 1 ? "" : "s"} waiting to be ingested. Click to refresh.`
          : phase.latest
            ? `Up to date — latest: ${phase.latest}. Click to re-check.`
            : "No dumps ingested yet. Click to refresh."
      }
    >
      <span aria-hidden="true">↻</span>
      {hasPending && <span className="tabular-nums">{phase.pending}</span>}
    </button>
  );
}

// Inline spinner glyph — pure CSS, no extra deps. Animates a 12px
// circular outline; matches the button text size.
function SpinnerGlyph() {
  return (
    <span
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-500/50 border-t-transparent"
      aria-hidden="true"
    />
  );
}
