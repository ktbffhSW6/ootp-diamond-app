"use client";

// SprayChart — batter-relative hit distribution by spray angle.
//
// OOTP encodes spray as a 1D `hit_xy` integer. The 0-130 range covers
// the field arc (0 = pull-side foul line, ~65 = center, 130 = oppo
// foul line); 130-255 are mostly out-of-play / dead-ball codes that
// we don't render.
//
// We render TWO views in one chart, side-by-side:
// 1. A polar fan: a 12-wedge half-disc (foul-line to foul-line)
//    where each wedge's radius is the BIP count, segmented by outcome.
//    This is the visual centerpiece — looks like a real spray chart.
// 2. A horizontal stacked bar: same data, alternative read for
//    quantitative comparison ("how many singles to LF?").
//
// We don't have ball-in-play distance from OOTP, so true Savant-style
// (x, y) scatter isn't possible. The fan + bar combo is the most
// faithful "what does this batter's spray look like" view we can
// build from the codebook.

import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";

import type { BattedBallEvent } from "@/lib/types/api";

const RESULT_LABELS: Record<number, string> = {
  4: "GO",
  5: "FO",
  6: "1B",
  7: "2B",
  8: "3B",
  9: "HR",
};

// Color map per outcome — outs muted, hits saturated, HR loud.
// Picked to read on both light + dark themes.
const RESULT_COLORS: Record<number, string> = {
  4: "#94a3b8", // slate-400 — ground out
  5: "#cbd5e1", // slate-300 — fly out
  6: "#22c55e", // green-500 — single
  7: "#3b82f6", // blue-500 — double
  8: "#a855f7", // purple-500 — triple
  9: "#f97316", // orange-500 — home run
};

// Wedge bins (12 wedges across the 90° arc). Friendly labels
// rendered on hover.
const WEDGE_COUNT = 12;
const ANGLE_MAX = 130; // hit_xy values above this are out-of-play

interface Props {
  rows: BattedBallEvent[];
  handedness?: "L" | "R" | "S";
  height?: number;
}

export function SprayChart({ rows, handedness = "R", height = 360 }: Props) {
  const fanRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);

  // Filter to in-arc events. hit_xy ∈ [0, ANGLE_MAX] only.
  const events = rows.filter(
    (r) => r.hit_xy !== null && r.hit_xy >= 0 && r.hit_xy <= ANGLE_MAX,
  );

  // Bin by angle wedge × outcome. Each wedge spans ANGLE_MAX/WEDGE_COUNT.
  type Bin = { wedge: number; result: number; count: number; angle_mid: number };
  const bins: Bin[] = [];
  for (let w = 0; w < WEDGE_COUNT; w++) {
    for (const result of Object.keys(RESULT_COLORS).map(Number)) {
      bins.push({
        wedge: w,
        result,
        count: 0,
        angle_mid: ((w + 0.5) * ANGLE_MAX) / WEDGE_COUNT,
      });
    }
  }
  for (const e of events) {
    const w = Math.min(
      WEDGE_COUNT - 1,
      Math.floor((e.hit_xy! / ANGLE_MAX) * WEDGE_COUNT),
    );
    const bin = bins.find((b) => b.wedge === w && b.result === e.result);
    if (bin) bin.count += 1;
  }
  const filledBins = bins.filter((b) => b.count > 0);

  // ─── Polar fan: hand-rolled SVG (Plot's polar isn't great for stacked
  //     wedges) ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!fanRef.current) return;
    fanRef.current.innerHTML = "";
    fanRef.current.appendChild(renderFan(events, handedness, height));
  }, [rows, handedness, height, events]);

  // ─── Horizontal stacked bar: Plot's barX with stackY by result ──────
  useEffect(() => {
    if (!barRef.current) return;
    barRef.current.innerHTML = "";
    if (filledBins.length === 0) return;

    const chart = Plot.plot({
      height: height,
      width: 360,
      x: { label: "BIP" },
      y: {
        label: handedness === "L" ? "← Pull   |   Oppo →" : "← Oppo   |   Pull →",
        domain: Array.from({ length: WEDGE_COUNT }, (_, i) =>
          handedness === "L" ? i : WEDGE_COUNT - 1 - i,
        ),
        tickFormat: (i: number) => {
          const a = ((i + 0.5) * ANGLE_MAX) / WEDGE_COUNT;
          if (a < ANGLE_MAX / 3) return "Pull";
          if (a < (2 * ANGLE_MAX) / 3) return "Center";
          return "Oppo";
        },
      },
      color: {
        legend: true,
        domain: [4, 5, 6, 7, 8, 9].map((r) => RESULT_LABELS[r]),
        range: [4, 5, 6, 7, 8, 9].map((r) => RESULT_COLORS[r]),
      },
      marks: [
        Plot.barX(filledBins, {
          y: "wedge",
          x: "count",
          fill: (d: Bin) => RESULT_LABELS[d.result],
          tip: true,
          title: (d: Bin) => `${RESULT_LABELS[d.result]}: ${d.count}`,
        }),
      ],
    });
    barRef.current.appendChild(chart);
    return () => chart.remove();
  }, [filledBins, handedness, height]);

  if (events.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface-card p-6 text-center text-content-muted">
        No in-arc batted-ball events to plot.
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[auto_minmax(0,1fr)]">
      <div
        ref={fanRef}
        className="flex items-center justify-center rounded-lg border border-border bg-surface-card p-2"
      />
      <div
        ref={barRef}
        className="rounded-lg border border-border bg-surface-card p-2"
      />
    </div>
  );
}


// ─── Polar fan renderer ─────────────────────────────────────────────────


function renderFan(
  events: BattedBallEvent[],
  handedness: "L" | "R" | "S",
  height: number,
): SVGElement {
  // Half-disc spanning 90° + buffer; cx at center, cy near bottom.
  const w = height;
  const h = height;
  const cx = w / 2;
  const cy = h - 30;
  const radiusMax = h - 60;

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("width", String(w));
  svg.setAttribute("height", String(h));
  svg.setAttribute("class", "block");

  // Field background — outfield arc + foul lines + infield diamond hint.
  // For LHB, pull side is the right (RF); for RHB, pull side is the left
  // (LF). We orient the chart so the BATTER POV is at the bottom (cy)
  // looking up at the field. Pull-side at left for RHB, at right for LHB.
  const flipPull = handedness === "L";

  // Outfield arc + foul lines (light outline)
  const outfield = document.createElementNS(svgNS, "path");
  outfield.setAttribute(
    "d",
    `M ${cx - radiusMax} ${cy} A ${radiusMax} ${radiusMax} 0 0 1 ${cx + radiusMax} ${cy} L ${cx} ${cy} Z`,
  );
  outfield.setAttribute("fill", "rgba(34, 197, 94, 0.05)");
  outfield.setAttribute("stroke", "rgba(148, 163, 184, 0.4)");
  outfield.setAttribute("stroke-width", "1");
  svg.appendChild(outfield);

  // Infield diamond hint (small triangle at base)
  const infieldR = radiusMax * 0.3;
  const infield = document.createElementNS(svgNS, "path");
  infield.setAttribute(
    "d",
    `M ${cx - infieldR} ${cy} A ${infieldR} ${infieldR} 0 0 1 ${cx + infieldR} ${cy} L ${cx} ${cy} Z`,
  );
  infield.setAttribute("fill", "rgba(245, 158, 11, 0.08)");
  infield.setAttribute("stroke", "rgba(148, 163, 184, 0.3)");
  infield.setAttribute("stroke-width", "1");
  svg.appendChild(infield);

  // Tally per wedge × outcome
  type Tally = { wedge: number; result: number; count: number };
  const tally: Tally[] = [];
  for (let w = 0; w < WEDGE_COUNT; w++) {
    for (const result of Object.keys(RESULT_COLORS).map(Number)) {
      tally.push({ wedge: w, result, count: 0 });
    }
  }
  for (const e of events) {
    const wIdx = Math.min(
      WEDGE_COUNT - 1,
      Math.floor((e.hit_xy! / ANGLE_MAX) * WEDGE_COUNT),
    );
    const t = tally.find((x) => x.wedge === wIdx && x.result === e.result);
    if (t) t.count += 1;
  }
  // Max wedge total → scales radius
  const maxWedgeTotal = Math.max(
    ...Array.from({ length: WEDGE_COUNT }, (_, w) =>
      tally.filter((t) => t.wedge === w).reduce((s, t) => s + t.count, 0),
    ),
    1,
  );

  // Render wedges, stacked bottom-up by outcome (out → hit → HR)
  const STACK_ORDER = [4, 5, 6, 7, 8, 9];
  for (let wIdx = 0; wIdx < WEDGE_COUNT; wIdx++) {
    const total = tally
      .filter((t) => t.wedge === wIdx)
      .reduce((s, t) => s + t.count, 0);
    if (total === 0) continue;
    const wedgeRadius = (total / maxWedgeTotal) * radiusMax * 0.92;

    // Angle from foul line on the pull side. RHB pull-side = left of
    // chart (180° in SVG terms going CCW from horizontal); LHB pull-side
    // = right. We render half-disc with foul lines at 180° (left) and 0°
    // (right) relative to cy.
    const wedgeIdxOriented = flipPull ? WEDGE_COUNT - 1 - wIdx : wIdx;
    const a0 =
      Math.PI - (wedgeIdxOriented * Math.PI) / WEDGE_COUNT; // CCW
    const a1 =
      Math.PI - ((wedgeIdxOriented + 1) * Math.PI) / WEDGE_COUNT;

    let runningR = 0;
    for (const result of STACK_ORDER) {
      const t = tally.find((x) => x.wedge === wIdx && x.result === result);
      if (!t || t.count === 0) continue;
      const r0 = (runningR / total) * wedgeRadius;
      const r1 = ((runningR + t.count) / total) * wedgeRadius;
      runningR += t.count;

      const path = wedgePath(cx, cy, r0, r1, a0, a1);
      const p = document.createElementNS(svgNS, "path");
      p.setAttribute("d", path);
      p.setAttribute("fill", RESULT_COLORS[result]);
      p.setAttribute("opacity", "0.85");
      p.setAttribute("stroke", "rgba(15, 23, 42, 0.4)");
      p.setAttribute("stroke-width", "0.5");
      const titleEl = document.createElementNS(svgNS, "title");
      titleEl.textContent = `${RESULT_LABELS[result]}: ${t.count}`;
      p.appendChild(titleEl);
      svg.appendChild(p);
    }
  }

  // Foul lines accent
  for (const angle of [0, Math.PI]) {
    const x2 = cx + Math.cos(angle) * radiusMax;
    const y2 = cy - Math.sin(angle) * radiusMax;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", String(cx));
    line.setAttribute("y1", String(cy));
    line.setAttribute("x2", String(x2));
    line.setAttribute("y2", String(y2));
    line.setAttribute("stroke", "rgba(148, 163, 184, 0.6)");
    line.setAttribute("stroke-width", "1");
    svg.appendChild(line);
  }

  // Direction labels (Pull / Center / Oppo)
  const labelData = [
    { txt: handedness === "L" ? "Pull" : "Oppo", x: cx + radiusMax * 0.92, y: cy + 18 },
    { txt: "Center", x: cx, y: cy - radiusMax - 6 },
    { txt: handedness === "L" ? "Oppo" : "Pull", x: cx - radiusMax * 0.92, y: cy + 18 },
  ];
  for (const l of labelData) {
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", String(l.x));
    t.setAttribute("y", String(l.y));
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("font-size", "11");
    t.setAttribute("fill", "currentColor");
    t.setAttribute("class", "fill-content-secondary");
    t.textContent = l.txt;
    svg.appendChild(t);
  }

  return svg;
}


function wedgePath(
  cx: number,
  cy: number,
  r0: number,
  r1: number,
  a0: number,
  a1: number,
): string {
  // Annular wedge — outer arc r1 (a0→a1), inner arc r0 (a1→a0).
  // Note: SVG y goes down, so for the upper half-disc we negate sin().
  const x0 = cx + Math.cos(a0) * r0;
  const y0 = cy - Math.sin(a0) * r0;
  const x1 = cx + Math.cos(a0) * r1;
  const y1 = cy - Math.sin(a0) * r1;
  const x2 = cx + Math.cos(a1) * r1;
  const y2 = cy - Math.sin(a1) * r1;
  const x3 = cx + Math.cos(a1) * r0;
  const y3 = cy - Math.sin(a1) * r0;
  const sweep = a0 > a1 ? 0 : 1;
  return `M ${x0} ${y0} L ${x1} ${y1} A ${r1} ${r1} 0 0 ${sweep} ${x2} ${y2} L ${x3} ${y3} A ${r0} ${r0} 0 0 ${1 - sweep} ${x0} ${y0} Z`;
}
