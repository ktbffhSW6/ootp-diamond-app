"use client";

// Chart Builder — pick X, Y (optional), color (optional), filters,
// see the result rendered as a Plot scatter (or histogram when Y is
// omitted). URL-driven so deep-links + the back button work.
//
// The picker uses the same 32-stat catalog as /league/leaderboards
// (returned by `getLeaderboardOptions`). Cross-table is fair game —
// the API LEFT-JOINs the source tables together when X and Y come
// from different sources (every supported stat keys on (player, year,
// league, level) at the L3 grain).
//
// Histogram rendering: when Y is null we bin the X distribution into
// ~30 buckets client-side (`Plot.binX` + `Plot.rectY`). Scatter mode
// is a simple `Plot.dot` with optional color encoding.

import * as Plot from "@observablehq/plot";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useTransition } from "react";

import { useElementWidth } from "@/lib/useElementWidth";
import type {
  ChartBuilderResponse,
  LeaderboardOption,
} from "@/lib/types/api";

const DISCIPLINE_LABEL: Record<string, string> = {
  batting: "Batting",
  pitching: "Pitching",
  statcast_b: "Statcast (Batter)",
  statcast_p: "Statcast (Pitcher)",
};
const DISCIPLINE_ORDER = ["batting", "pitching", "statcast_b", "statcast_p"];

const LEVEL_OPTIONS: { id: number; label: string }[] = [
  { id: 1, label: "MLB" },
  { id: 2, label: "AAA" },
  { id: 3, label: "AA" },
  { id: 4, label: "A+" },
  { id: 5, label: "A" },
];

interface Props {
  options: LeaderboardOption[];
  initial: ChartBuilderResponse;
  initialQualifierMin: number | undefined;
}

export function ChartBuilderClient({
  options,
  initial,
  initialQualifierMin,
}: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const { ref, width } = useElementWidth<HTMLDivElement>(800);

  // Picker state mirrors URL-resolved values from the server fetch.
  const x = initial.x_stat;
  const y = initial.y_stat ?? "";
  const color = initial.color_stat ?? "";
  const year = initial.year ?? "";
  const levelId = initial.level_id ?? 1;
  const qualifierMin = initialQualifierMin ?? initial.qualifier_min;

  const groupedOptions = useMemo(() => {
    const groups: Record<string, LeaderboardOption[]> = {};
    for (const o of options) {
      if (!groups[o.discipline]) groups[o.discipline] = [];
      groups[o.discipline].push(o);
    }
    return groups;
  }, [options]);

  function updateUrl(updates: Record<string, string | number | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === undefined || v === "" || v === null) next.delete(k);
      else next.set(k, String(v));
    }
    startTransition(() => {
      router.replace(`/explore?${next.toString()}`);
    });
  }

  const xSpec = options.find((o) => o.id === x);
  const ySpec = y ? options.find((o) => o.id === y) : null;
  const colorSpec = color ? options.find((o) => o.id === color) : null;

  // Plot render — re-runs whenever the dataset, mode, or labels change.
  useEffect(() => {
    if (!ref.current) return;
    ref.current.innerHTML = "";

    const valid = initial.points.filter(
      (p) => p.x !== null && (initial.mode === "histogram" || p.y !== null),
    );
    if (valid.length === 0) {
      ref.current.innerHTML =
        '<div class="rounded-lg border border-border bg-surface-card p-8 text-center text-content-muted">No rows match the current filters. Try lowering the Min qualifier.</div>';
      return;
    }

    const xLabel = xSpec?.label ?? x;
    const yLabel = ySpec?.label ?? "";
    const colorLabel = colorSpec?.label ?? "";

    let chart: SVGElement | HTMLElement;
    if (initial.mode === "histogram") {
      chart = Plot.plot({
        height: 420,
        width,
        x: { label: xLabel, grid: true },
        y: { label: "Players", grid: true },
        marks: [
          // Plot.binX takes {y: 'count'} as the reducer spec, then a
          // separate options object for the rect mark itself. Style
          // properties (fill/stroke) belong on the mark options.
          Plot.rectY(valid, Plot.binX({ y: "count" }, { x: "x" })),
          // Style overlay — Plot lets you stack marks; the second
          // pass paints fill/stroke without colliding with the
          // reducer signature.
          Plot.ruleY([0]),
        ],
        style: { color: "currentColor" },
        color: { range: ["#3b82f6"] },
      });
    } else {
      // Scatter — color by `color_value` if provided, else single color.
      const colorChannel: Record<string, unknown> = colorSpec
        ? {
            stroke: "color",
            tip: true,
            title: (
              d: {
                player_name: string;
                x: number;
                y: number;
                color: number | null;
              },
            ) =>
              `${d.player_name}\n${xLabel}: ${d.x.toFixed(xSpec?.decimals ?? 2)}\n${yLabel}: ${d.y.toFixed(ySpec?.decimals ?? 2)}` +
              (d.color !== null
                ? `\n${colorLabel}: ${d.color.toFixed(colorSpec?.decimals ?? 2)}`
                : ""),
          }
        : {
            fill: "var(--accent, #3b82f6)",
            tip: true,
            title: (
              d: { player_name: string; x: number; y: number },
            ) =>
              `${d.player_name}\n${xLabel}: ${d.x.toFixed(xSpec?.decimals ?? 2)}\n${yLabel}: ${d.y.toFixed(ySpec?.decimals ?? 2)}`,
          };

      chart = Plot.plot({
        height: 480,
        width,
        x: { label: xLabel, grid: true, reverse: xSpec?.direction === "asc" },
        y: { label: yLabel, grid: true, reverse: ySpec?.direction === "asc" },
        color: colorSpec
          ? { legend: true, label: colorLabel, scheme: "viridis" }
          : undefined,
        marks: [
          Plot.dot(valid, {
            x: "x",
            y: "y",
            r: 4,
            fillOpacity: 0.7,
            strokeWidth: 1.5,
            ...colorChannel,
          }),
        ],
      });
    }

    ref.current.appendChild(chart);
    return () => {
      if (chart && "remove" in chart) (chart as SVGElement).remove();
    };
  }, [initial, x, y, color, xSpec, ySpec, colorSpec, width, ref]);

  return (
    <div className="space-y-4">
      {/* Picker */}
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-border bg-surface-card p-4">
        <StatPicker
          label="X axis"
          value={x}
          onChange={(v) => updateUrl({ x: v })}
          groups={groupedOptions}
        />
        <StatPicker
          label="Y axis"
          value={y}
          onChange={(v) => updateUrl({ y: v })}
          groups={groupedOptions}
          allowNone
        />
        <StatPicker
          label="Color"
          value={color}
          onChange={(v) => updateUrl({ color: v })}
          groups={groupedOptions}
          allowNone
        />
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
            Min qual
          </label>
          <input
            type="number"
            value={qualifierMin}
            onChange={(e) => updateUrl({ qualifier_min: e.target.value })}
            min={0}
            className="w-24 rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
          />
        </div>
      </div>

      {/* Chart */}
      <div
        ref={ref}
        className="rounded-lg border border-border bg-surface-card p-4"
      />

      <p className="text-xs text-content-muted">
        Mode: <span className="font-mono">{initial.mode}</span> · {initial.points.length}{" "}
        rows · year {initial.year} · level {initial.level_id} · min {initial.qualifier_min}.
        Click a dot in scatter mode for a tooltip; histogram bars show the
        player count per bin.{" "}
        <Link
          href="/league/leaderboards"
          className="text-link hover:text-link-hover"
        >
          Leaderboards
        </Link>{" "}
        for ranked single-stat lists,{" "}
        <Link
          href="/league/compare"
          className="text-link hover:text-link-hover"
        >
          Compare
        </Link>{" "}
        for player-vs-player blocks.
      </p>
    </div>
  );
}

function StatPicker({
  label,
  value,
  onChange,
  groups,
  allowNone = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  groups: Record<string, LeaderboardOption[]>;
  allowNone?: boolean;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
      >
        {allowNone && <option value="">— none —</option>}
        {DISCIPLINE_ORDER.map(
          (d) =>
            groups[d] && (
              <optgroup key={d} label={DISCIPLINE_LABEL[d] ?? d}>
                {groups[d].map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </optgroup>
            ),
        )}
      </select>
    </div>
  );
}
