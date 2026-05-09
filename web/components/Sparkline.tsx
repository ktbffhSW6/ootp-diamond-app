// Sparkline — tiny inline SVG trend chart. No chart library dependency;
// just a polyline + dots over a baseline. Intended for dense table
// rows + card hero spots where a real chart would be overkill but a
// number alone is too quiet.
//
// Usage:
//   <Sparkline values={[3.2, 5.5, 4.7, 6.1, 4.0]} width={80} height={24} />
//
// Color picks itself from the trend (last vs first) by default —
// emerald if rising, rose if falling, sky if flat. Override with
// `color` prop when the call-site has a stronger opinion (e.g.,
// pitcher streak should always read in violet).
//
// Y-axis auto-fits to value range with a 10% padding band; X-axis
// is index-based (one slot per value). For sparser data with
// missing years, pass nulls in the array and the component will
// skip those points cleanly (gap in the line).

import type { CSSProperties } from "react";

export type SparkPoint = number | null;

const STROKE_EMERALD = "stroke-emerald-500 dark:stroke-emerald-400";
const STROKE_ROSE = "stroke-rose-500 dark:stroke-rose-400";
const STROKE_SKY = "stroke-sky-500 dark:stroke-sky-400";
const FILL_EMERALD = "fill-emerald-500 dark:fill-emerald-400";
const FILL_ROSE = "fill-rose-500 dark:fill-rose-400";
const FILL_SKY = "fill-sky-500 dark:fill-sky-400";

type SparkColor = "auto" | "emerald" | "rose" | "sky";

export interface SparklineProps {
  values: SparkPoint[];
  width?: number;
  height?: number;
  color?: SparkColor;
  /** Show a dot at each data point (defaults true for ≤12 points, false otherwise). */
  showDots?: boolean;
  /** Highlight the last point with a slightly larger dot. */
  highlightLast?: boolean;
  /** Optional label rendered as an accessible <title> on the SVG. */
  label?: string;
  /** Override style (e.g., to set explicit width via CSS). */
  style?: CSSProperties;
}

export function Sparkline({
  values,
  width = 80,
  height = 24,
  color = "auto",
  showDots,
  highlightLast = true,
  label,
  style,
}: SparklineProps) {
  // Filter to defined values for range calc, but keep the original
  // array shape for index alignment (gaps stay at the right index).
  const defined = values.filter((v): v is number => v !== null);
  if (defined.length === 0) {
    return (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        style={style}
        className="block"
        role="img"
        aria-label={label ?? "no data"}
      >
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          className="stroke-border"
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  // Auto-pick stroke from trend (last defined vs first defined). This
  // matches the heat-scale convention: rising = good (emerald),
  // falling = trouble (rose), flat or single-point = sky.
  const first = defined[0];
  const last = defined[defined.length - 1];
  let resolvedColor: "emerald" | "rose" | "sky";
  if (color === "auto") {
    if (defined.length === 1) resolvedColor = "sky";
    else if (last > first) resolvedColor = "emerald";
    else if (last < first) resolvedColor = "rose";
    else resolvedColor = "sky";
  } else {
    resolvedColor = color;
  }
  const strokeClass =
    resolvedColor === "emerald"
      ? STROKE_EMERALD
      : resolvedColor === "rose"
        ? STROKE_ROSE
        : STROKE_SKY;
  const fillClass =
    resolvedColor === "emerald"
      ? FILL_EMERALD
      : resolvedColor === "rose"
        ? FILL_ROSE
        : FILL_SKY;

  // Y-range with 10% padding above/below; if all values are equal,
  // synthesize a tiny range so the line still renders mid-height.
  let yMin = Math.min(...defined);
  let yMax = Math.max(...defined);
  if (yMin === yMax) {
    yMin = yMin - 1;
    yMax = yMax + 1;
  } else {
    const pad = (yMax - yMin) * 0.1;
    yMin -= pad;
    yMax += pad;
  }

  const padX = 2; // small inner padding so dots don't clip at edges
  const padY = 2;
  const drawW = width - 2 * padX;
  const drawH = height - 2 * padY;
  const stepX = values.length > 1 ? drawW / (values.length - 1) : 0;

  const x = (i: number) => padX + i * stepX;
  const y = (v: number) => padY + drawH * (1 - (v - yMin) / (yMax - yMin));

  // Build path segments, breaking on null gaps so we don't draw a
  // straight line across a missing year.
  const segments: string[] = [];
  let current: string[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (current.length > 0) {
        segments.push(current.join(" "));
        current = [];
      }
      return;
    }
    const cmd = current.length === 0 ? "M" : "L";
    current.push(`${cmd} ${x(i).toFixed(2)} ${y(v).toFixed(2)}`);
  });
  if (current.length > 0) segments.push(current.join(" "));
  const pathD = segments.join(" ");

  const drawDots = showDots ?? values.length <= 12;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      style={style}
      className="block overflow-visible"
      role="img"
      aria-label={label ?? "trend"}
    >
      {label && <title>{label}</title>}
      <path
        d={pathD}
        className={strokeClass}
        fill="none"
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {drawDots &&
        values.map((v, i) =>
          v === null ? null : (
            <circle
              key={i}
              cx={x(i)}
              cy={y(v)}
              r={i === values.length - 1 && highlightLast ? 1.8 : 1.1}
              className={fillClass}
            />
          ),
        )}
    </svg>
  );
}
