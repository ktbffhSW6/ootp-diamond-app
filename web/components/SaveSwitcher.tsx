"use client";

// SaveSwitcher — radio-card list of available saves.
//
// Clicking a row's "Make active" button POSTs to /api/saves/active.
// The active save's row is highlighted; saves without a warehouse
// get an amber "needs ingest" badge.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { setActiveSave } from "@/lib/api";
import type { SavesListResponse, SaveSummaryDto } from "@/lib/types/api";

interface Props {
  initial: SavesListResponse;
}

export function SaveSwitcher({ initial }: Props) {
  const router = useRouter();
  const [data, setData] = useState(initial);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pick(name: string) {
    setPending(name);
    setError(null);
    try {
      const next = await setActiveSave(name);
      setData(next);
      // Refresh the whole layout so any cached server-component data
      // (e.g., the Save page header in the cockpit) re-fetches.
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  if (data.saves.length === 0) {
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-5 text-sm text-amber-700 dark:text-amber-300">
        No saves found under{" "}
        <code className="font-mono text-xs">{data.saves_root}</code>.
        Make sure OOTP is installed and you have at least one save
        (look for a <code>*.lg</code> folder).
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {data.saves.map((s) => (
        <SaveCard
          key={s.name}
          save={s}
          pending={pending === s.name}
          onPick={pick}
        />
      ))}
      {error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}
    </div>
  );
}

function SaveCard({
  save,
  pending,
  onPick,
}: {
  save: SaveSummaryDto;
  pending: boolean;
  onPick: (name: string) => void;
}) {
  const lastModified = save.last_modified
    ? new Date(save.last_modified * 1000).toLocaleString()
    : "—";

  return (
    <div
      className={`rounded-lg border p-4 ${
        save.is_active
          ? "border-accent bg-accent/5"
          : "border-border bg-surface-card"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-content-primary">
              {save.name}
            </span>
            {save.is_active && (
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-500/25 dark:text-emerald-300">
                Active
              </span>
            )}
            {!save.has_warehouse && (
              <span
                className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/25 dark:text-amber-300"
                title="Run `diamond ingest` in your terminal to build the warehouse for this save."
              >
                Needs ingest
              </span>
            )}
          </div>
          <div className="mt-1 truncate text-xs text-content-muted">
            {save.path}
          </div>
          <div className="text-xs text-content-muted">
            Last modified: {lastModified}
          </div>
        </div>
        {!save.is_active && (
          <button
            onClick={() => onPick(save.name)}
            disabled={pending}
            className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {pending ? "Switching…" : "Make active"}
          </button>
        )}
      </div>
    </div>
  );
}
