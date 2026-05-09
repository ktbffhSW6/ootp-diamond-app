"use client";

// Leaderboard client component.
//
// Two responsibilities:
// 1. Picker UI (stat dropdown, year input, level pills, min-qualifier
//    input). Picker writes to URL via router.replace so deep-links
//    survive a refresh and the Back button works.
// 2. TanStack Table rendering with client-side sort. Sort defaults to
//    the stat's natural direction (desc for HR, asc for ERA); user can
//    flip to whichever column they care about. Rows never paginate —
//    we cap at 100 server-side and let the user scroll.

import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { plusMinusClass, warSeasonClass } from "@/lib/heatscale";
import type {
  LeaderboardOption,
  LeaderboardResponse,
  LeaderboardRow,
} from "@/lib/types/api";

const LEVEL_OPTIONS: { id: number; label: string }[] = [
  { id: 1, label: "MLB" },
  { id: 2, label: "AAA" },
  { id: 3, label: "AA" },
  { id: 4, label: "A+" },
  { id: 5, label: "A" },
  { id: 6, label: "Rk" },
];

// Discipline grouping for the picker dropdown — ordered so common
// stats (batting / pitching) sit above the cohort-only Statcast group.
const DISCIPLINE_LABEL: Record<string, string> = {
  batting: "Batting",
  pitching: "Pitching",
  statcast_b: "Statcast (Batter)",
  statcast_p: "Statcast (Pitcher)",
};
const DISCIPLINE_ORDER = ["batting", "pitching", "statcast_b", "statcast_p"];

interface Props {
  options: LeaderboardOption[];
  initial: LeaderboardResponse;
  initialPaMin: number | undefined;
}

export function LeaderboardClient({ options, initial, initialPaMin }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();

  // Group options by discipline for the dropdown
  const groupedOptions = useMemo(() => {
    const groups: Record<string, LeaderboardOption[]> = {};
    for (const o of options) {
      const d = o.discipline;
      if (!groups[d]) groups[d] = [];
      groups[d].push(o);
    }
    return groups;
  }, [options]);

  // Picker state, synced via URL
  const stat = initial.stat.id;
  const year = initial.year ?? "";
  const levelId = initial.level_id ?? 1;
  const paMin = initialPaMin ?? initial.pa_min;

  function updateUrl(updates: Record<string, string | number | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === undefined || v === "" || v === null) {
        next.delete(k);
      } else {
        next.set(k, String(v));
      }
    }
    startTransition(() => {
      router.replace(`/league/leaderboards?${next.toString()}`);
    });
  }

  // ─── Table columns ──────────────────────────────────────────────
  const columns = useMemo<ColumnDef<LeaderboardRow>[]>(
    () => [
      {
        accessorKey: "rank",
        header: "#",
        cell: (c) => (
          <span className="text-content-muted tabular-nums">
            {c.getValue<number>()}
          </span>
        ),
        size: 40,
        enableSorting: true,
      },
      {
        accessorKey: "player_name",
        header: "Player",
        cell: (c) => (
          <Link
            href={`/player/${c.row.original.player_id}`}
            className="text-link hover:text-link-hover"
          >
            {c.getValue<string>()}
          </Link>
        ),
        size: 200,
      },
      {
        accessorKey: "team_abbr",
        header: "Team",
        cell: (c) => (
          <span className="text-content-secondary">
            {c.getValue<string | null>() ?? "—"}
          </span>
        ),
        size: 60,
      },
      {
        accessorKey: "value",
        header: initial.stat.label,
        cell: (c) => {
          const v = c.getValue<number | null>();
          if (v === null) return <span className="text-content-muted">—</span>;
          const formatted = v.toFixed(initial.stat.decimals);
          // Heat-scale on plus stats and WAR fields.
          let cls = "text-content-primary tabular-nums";
          if (
            initial.stat.id === "wRC_plus" ||
            initial.stat.id === "OPS_plus" ||
            initial.stat.id === "ERA_plus"
          ) {
            cls = `tabular-nums px-2 py-0.5 rounded ${plusMinusClass(v)}`;
          } else if (
            initial.stat.id === "bWAR" ||
            initial.stat.id === "pWAR" ||
            initial.stat.id === "RA9_WAR" ||
            initial.stat.id === "oWAR" ||
            initial.stat.id === "pit_WAR"
          ) {
            cls = `tabular-nums px-2 py-0.5 rounded ${warSeasonClass(v)}`;
          }
          return <span className={cls}>{formatted}</span>;
        },
        size: 100,
        enableSorting: true,
        sortDescFirst: initial.stat.direction === "desc",
      },
      {
        accessorKey: "qualifier_value",
        header: initial.qualifier_label === "IP"
          ? "IP"
          : initial.qualifier_label,
        cell: (c) => {
          const v = c.getValue<number>();
          // qualifier_value is in PA (counting) / outs (IP) / BIP. For
          // IP, divide outs by 3 with .1-decimal display matching MLB
          // convention (172.1 = 172⅓ IP).
          if (initial.qualifier_label === "IP") {
            const ip = Math.floor(v / 3) + (v % 3) * 0.1;
            return (
              <span className="text-content-muted tabular-nums">
                {ip.toFixed(1)}
              </span>
            );
          }
          return (
            <span className="text-content-muted tabular-nums">{v}</span>
          );
        },
        size: 70,
      },
      {
        accessorKey: "year",
        header: "Year",
        cell: (c) => (
          <span className="text-content-muted tabular-nums">
            {c.getValue<number | null>() ?? "—"}
          </span>
        ),
        size: 60,
      },
    ],
    [initial.stat, initial.qualifier_label],
  );

  // ─── Sort state, default to natural direction by value ──────────
  const [sorting, setSorting] = useState<SortingState>([
    { id: "value", desc: initial.stat.direction === "desc" },
  ]);

  const table = useReactTable({
    data: initial.rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // ─── Picker UI ──────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-border bg-surface-card p-4">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
            Stat
          </label>
          <select
            value={stat}
            onChange={(e) => updateUrl({ stat: e.target.value })}
            className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
          >
            {DISCIPLINE_ORDER.map(
              (d) =>
                groupedOptions[d] && (
                  <optgroup
                    key={d}
                    label={DISCIPLINE_LABEL[d] ?? d}
                  >
                    {groupedOptions[d].map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </optgroup>
                ),
            )}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
            Year
          </label>
          <input
            type="number"
            value={year}
            onChange={(e) => updateUrl({ year: e.target.value })}
            placeholder="latest"
            className="w-24 rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
            Level
          </label>
          <div className="flex gap-1">
            {LEVEL_OPTIONS.map((l) => (
              <button
                key={l.id}
                onClick={() => updateUrl({ level: l.id })}
                className={`rounded px-2.5 py-1.5 text-xs ${
                  levelId === l.id
                    ? "bg-accent text-white"
                    : "border border-border bg-surface-page text-content-secondary hover:border-border-strong"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
            Min {initial.qualifier_label}
          </label>
          <input
            type="number"
            value={paMin}
            onChange={(e) => updateUrl({ pa_min: e.target.value })}
            min={0}
            className="w-24 rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
          />
        </div>

        {isPending && (
          <span className="ml-auto text-xs text-content-muted">Loading…</span>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-surface-card">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr
                key={hg.id}
                className="border-b border-border bg-surface-elevated text-left"
              >
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    onClick={h.column.getToggleSortingHandler()}
                    className="cursor-pointer select-none px-3 py-2 text-xs uppercase tracking-wide text-content-secondary hover:text-content-primary"
                    style={{ width: h.column.columnDef.size }}
                  >
                    {flexRender(
                      h.column.columnDef.header,
                      h.getContext(),
                    )}
                    {{ asc: " ↑", desc: " ↓" }[
                      h.column.getIsSorted() as string
                    ] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-12 text-center text-content-muted"
                >
                  No rows match the current filters. Try lowering the
                  Min&nbsp;{initial.qualifier_label}.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-border last:border-0 hover:bg-surface-elevated"
                >
                  {r.getVisibleCells().map((c) => (
                    <td key={c.id} className="px-3 py-1.5">
                      {flexRender(
                        c.column.columnDef.cell,
                        c.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-content-muted">
        Showing top {initial.rows.length}.&nbsp;
        Sort handled client-side — click any column header to flip.&nbsp;
        Stat direction &quot;{initial.stat.direction}&quot; means{" "}
        {initial.stat.direction === "desc" ? "higher" : "lower"} is better.
      </p>
    </div>
  );
}
