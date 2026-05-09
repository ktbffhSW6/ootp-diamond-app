"use client";

// EvLaScatter — exit velocity × launch angle scatter, colored by outcome.
//
// Each ball-in-play event becomes one dot at (exit_velo, launch_angle).
// Color encodes the outcome (out / single / double / triple / HR).
//
// Reference overlays:
// - **Barrel zone** (orange dashed) — Statcast's classic definition,
//   adjusted for OOTP's ~5 mph EV scale offset:
//     EV ≥ 93, LA ∈ [22°, 38°]
//   (Real Statcast uses EV ≥ 98 + LA ∈ [26°, 30°] expanding with EV;
//   we shrink the EV floor by ~5 to match OOTP's lower scale.)
// - **Sweet-spot zone** (subtle blue) — LA ∈ [8°, 32°] across all EVs.
//
// Width tracks the container via ResizeObserver (lib/useElementWidth)
// so the scatter fills whatever pane it lives in. LA axis -30 to +60
// covers ~99% of contact.

import * as Plot from "@observablehq/plot";
import { useEffect } from "react";

import { useElementWidth } from "@/lib/useElementWidth";
import type { BattedBallEvent } from "@/lib/types/api";

const RESULT_LABELS: Record<number, string> = {
  4: "GO",
  5: "FO",
  6: "1B",
  7: "2B",
  8: "3B",
  9: "HR",
};
const RESULT_COLORS: Record<number, string> = {
  4: "#94a3b8",
  5: "#cbd5e1",
  6: "#22c55e",
  7: "#3b82f6",
  8: "#a855f7",
  9: "#f97316",
};

interface Props {
  rows: BattedBallEvent[];
  height?: number;
}

export function EvLaScatter({ rows, height = 480 }: Props) {
  const { ref, width } = useElementWidth<HTMLDivElement>(720);

  useEffect(() => {
    if (!ref.current) return;
    // Empty the host before each re-render. We deliberately don't
    // re-use the previous chart node — Plot regenerates SVG marks
    // every time so there's no benefit to retention.
    ref.current.innerHTML = "";

    const events = rows.filter(
      (r) => r.exit_velo !== null && r.launch_angle !== null,
    );
    if (events.length === 0) return;

    const enriched = events.map((e) => ({
      ev: e.exit_velo!,
      la: e.launch_angle!,
      outcome: RESULT_LABELS[e.result] ?? "?",
      result: e.result,
    }));

    const sweetSpotZone = [{ ev0: 50, ev1: 130, la0: 8, la1: 32 }];
    const barrelZone = [{ ev0: 93, ev1: 130, la0: 22, la1: 38 }];

    const chart = Plot.plot({
      height,
      width,
      x: { label: "Exit Velocity (mph)", domain: [50, 130], grid: true },
      y: { label: "Launch Angle (°)", domain: [-30, 60], grid: true },
      color: {
        legend: true,
        domain: ["GO", "FO", "1B", "2B", "3B", "HR"],
        range: [4, 5, 6, 7, 8, 9].map((r) => RESULT_COLORS[r]),
      },
      marks: [
        Plot.rect(sweetSpotZone, {
          x1: "ev0",
          x2: "ev1",
          y1: "la0",
          y2: "la1",
          fill: "rgba(59, 130, 246, 0.06)",
          stroke: "rgba(59, 130, 246, 0.2)",
          strokeDasharray: "2,2",
        }),
        Plot.rect(barrelZone, {
          x1: "ev0",
          x2: "ev1",
          y1: "la0",
          y2: "la1",
          fill: "rgba(249, 115, 22, 0.08)",
          stroke: "rgba(249, 115, 22, 0.45)",
          strokeDasharray: "4,2",
        }),
        Plot.dot(enriched, {
          x: "ev",
          y: "la",
          fill: "outcome",
          r: 3.5,
          stroke: "rgba(15, 23, 42, 0.4)",
          strokeWidth: 0.5,
          opacity: 0.85,
          tip: true,
          title: (d: { ev: number; la: number; outcome: string }) =>
            `${d.outcome}: ${d.ev.toFixed(1)} mph @ ${d.la}°`,
        }),
      ],
    });
    ref.current.appendChild(chart);
    return () => chart.remove();
  }, [rows, height, width, ref]);

  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface-card p-6 text-center text-content-muted">
        No batted-ball events to plot.
      </div>
    );
  }
  return <div ref={ref} className="rounded-md border border-border bg-surface-card p-2" />;
}
