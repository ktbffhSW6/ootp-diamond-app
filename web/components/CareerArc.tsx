// CareerArc — small line chart of a player's career WAR by year.
// Hand-rolled SVG (no chart library); designed to sit at the top of
// the player page between the bio header and the Service & Status
// card. The shape tells the career story at a glance:
//
//   - Bonds 2001 → tall late-career spike that dwarfs the rest
//   - Trout 2012-2024 → flat plateau, gentle decline post-2020
//   - Skubal 2024-2029 → ascending arc to ace tier
//
// Inputs are typed as PlayerAdvancedBattingRow[] +
// PlayerAdvancedPitchingRow[] from the player API response. The
// component picks each year's BEST WAR signal — bWAR for batters,
// pWAR for pitchers, MAX of both for two-way / role-changing
// players — so the line is the player's overall season-grade WAR
// regardless of which discipline drove it.
//
// Visual notes:
//   - X-axis: career year span (every year between min and max,
//     even if the player missed a season — those gap years draw a
//     neutral baseline tick rather than nothing).
//   - Y-axis: 0 → max WAR + 10% headroom. Below-zero seasons drop
//     under the baseline.
//   - Dot per (year) with color picked from heat scale (warSeasonClass).
//   - Hover tooltip via <title>: "2001 · 11.9 WAR · SF" style.
//   - Era / level chips skipped for v1; the line is the headline.

import type {
  PlayerAdvancedBattingRow,
  PlayerAdvancedPitchingRow,
} from "@/lib/types/api";

// Resolve per-year best WAR signal across batting + pitching rows.
// A player can have multiple rows in a given year (multiple levels:
// MLB + AAA stints) — collapse to the best WAR within MLB-level
// rows when present, else best across all rows. Skips years with
// no advanced data (some pre-2026 imported real-history seasons
// for players with no league-baseline coverage).
type YearPoint = {
  year: number;
  war: number;
  level_id: number; // 1 = MLB, 2 = AAA, etc.
  league_abbr: string | null;
  team_abbr: string | null;
  role: "batter" | "pitcher" | "both";
};

function buildYearPoints(
  batting: PlayerAdvancedBattingRow[],
  pitching: PlayerAdvancedPitchingRow[],
): YearPoint[] {
  // Group rows by year. A year may have rows from both disciplines,
  // multiple levels, or both. Pick the one with the highest WAR
  // (canonical "this is what mattered most this year"), preferring
  // MLB-level if WARs are tied.
  type Candidate = {
    war: number;
    level_id: number;
    league_abbr: string | null;
    role: "batter" | "pitcher";
  };
  const byYear = new Map<number, Candidate[]>();
  for (const r of batting) {
    if (r.b_war === null) continue;
    const arr = byYear.get(r.year) ?? [];
    arr.push({
      war: r.b_war,
      level_id: r.level_id,
      league_abbr: r.league_abbr,
      role: "batter",
    });
    byYear.set(r.year, arr);
  }
  for (const r of pitching) {
    if (r.p_war === null) continue;
    const arr = byYear.get(r.year) ?? [];
    arr.push({
      war: r.p_war,
      level_id: r.level_id,
      league_abbr: r.league_abbr,
      role: "pitcher",
    });
    byYear.set(r.year, arr);
  }
  const points: YearPoint[] = [];
  for (const [year, candidates] of byYear) {
    if (candidates.length === 0) continue;
    // Sort: highest WAR first, MLB-level first as tiebreaker.
    candidates.sort((a, b) => {
      if (a.war !== b.war) return b.war - a.war;
      return a.level_id - b.level_id;
    });
    const best = candidates[0];
    const hasBoth =
      candidates.some((c) => c.role === "batter") &&
      candidates.some((c) => c.role === "pitcher");
    points.push({
      year,
      war: best.war,
      level_id: best.level_id,
      league_abbr: best.league_abbr,
      team_abbr: null,
      role: hasBoth ? "both" : best.role,
    });
  }
  points.sort((a, b) => a.year - b.year);
  return points;
}

// WAR-to-color (matches heatscale warSeasonClass bands but as raw
// fill colors since we're filling SVG circles, not text). Kept
// inline rather than depending on heatscale.ts to avoid leaking
// the SVG-fill semantics into a CSS-class-typed module.
function dotFillClass(war: number): string {
  if (war >= 8.0) return "fill-emerald-600 dark:fill-emerald-400";
  if (war >= 5.0) return "fill-emerald-500 dark:fill-emerald-400";
  if (war >= 3.0) return "fill-emerald-500/80 dark:fill-emerald-500";
  if (war >= 1.0) return "fill-emerald-500/60 dark:fill-emerald-500/80";
  if (war >= 0) return "fill-content-muted";
  if (war >= -1.0) return "fill-rose-500 dark:fill-rose-400";
  return "fill-rose-600 dark:fill-rose-500";
}

const PEAK_TIER = 8.0;
const FLOOR_TIER = -1.0;

export interface CareerArcProps {
  batting: PlayerAdvancedBattingRow[];
  pitching: PlayerAdvancedPitchingRow[];
  /** SVG dimensions; defaults sized for the player-page header strip. */
  width?: number;
  height?: number;
}

export function CareerArc({
  batting,
  pitching,
  width = 480,
  height = 110,
}: CareerArcProps) {
  const points = buildYearPoints(batting, pitching);

  if (points.length === 0) {
    // No advanced data — render an empty placeholder strip rather
    // than absent. The page still scaffolds visually for players
    // with counting-only minor-league careers.
    return (
      <div
        className="flex h-[110px] items-center justify-center rounded-md border border-dashed border-border text-xs text-content-muted"
        style={{ width, height }}
      >
        No career-WAR data
      </div>
    );
  }

  // Compute career totals + peak season for the header line.
  const careerWar = points.reduce((s, p) => s + p.war, 0);
  const peak = points.reduce((best, p) => (p.war > best.war ? p : best), points[0]);

  const minYear = points[0].year;
  const maxYear = points[points.length - 1].year;
  const yearSpan = Math.max(1, maxYear - minYear);

  // Build a dense year axis (every year between min and max),
  // even if the player didn't accumulate WAR in some seasons
  // (injuries / minor-league time / sit-outs). This keeps spacing
  // proportional to time, not to number-of-recorded-seasons.
  const allYears: number[] = [];
  for (let y = minYear; y <= maxYear; y++) allYears.push(y);
  const pointsByYear = new Map(points.map((p) => [p.year, p]));

  const padTop = 12;
  const padBottom = 22; // room for year-axis labels
  const padX = 16;
  const drawW = width - 2 * padX;
  const drawH = height - padTop - padBottom;

  // Y-range — symmetric is overkill; use 0-aware bounds with a touch
  // of padding. Always include 0 for the baseline. Cap the floor at
  // -1 if no negatives, so the chart doesn't shrink the positive
  // range.
  const wars = points.map((p) => p.war);
  const yMaxRaw = Math.max(...wars, 1);
  const yMinRaw = Math.min(...wars, 0);
  const yMax = yMaxRaw * 1.1;
  const yMin = yMinRaw < 0 ? yMinRaw * 1.15 : 0;
  const yRange = yMax - yMin || 1;

  const xOf = (year: number) =>
    padX + ((year - minYear) / yearSpan) * drawW;
  const yOf = (war: number) =>
    padTop + drawH * (1 - (war - yMin) / yRange);
  const baselineY = yOf(0);

  // Path string connecting all defined points. Years with no data
  // produce gaps (split paths) so the line doesn't lie about
  // missing time.
  const segments: string[] = [];
  let current: string[] = [];
  for (const year of allYears) {
    const p = pointsByYear.get(year);
    if (!p) {
      if (current.length > 0) {
        segments.push(current.join(" "));
        current = [];
      }
      continue;
    }
    const cmd = current.length === 0 ? "M" : "L";
    current.push(`${cmd} ${xOf(year).toFixed(2)} ${yOf(p.war).toFixed(2)}`);
  }
  if (current.length > 0) segments.push(current.join(" "));
  const pathD = segments.join(" ");

  // Year-axis ticks — first, last, and at most 4 evenly-spaced
  // intermediate years so the strip stays uncluttered.
  const tickYears = pickTickYears(minYear, maxYear);

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          Career Arc
        </p>
        <div className="flex items-baseline gap-3 font-mono text-xs">
          <span className="text-content-muted">
            {minYear}–{maxYear}
          </span>
          <span className="text-content-secondary">
            {points.length} season{points.length === 1 ? "" : "s"}
          </span>
          <span className="text-content-primary">
            <span className="font-semibold">{careerWar.toFixed(1)}</span>{" "}
            <span className="text-[10px] uppercase tracking-wider text-content-muted">
              WAR
            </span>
          </span>
          <span
            className="text-content-secondary"
            title={`Peak: ${peak.year} ${peak.league_abbr ?? ""} ${peak.role}`}
          >
            peak{" "}
            <span className="font-semibold text-content-primary">
              {peak.war.toFixed(1)}
            </span>{" "}
            <span className="text-content-muted">({peak.year})</span>
          </span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        className="block overflow-visible rounded border border-border bg-surface-card"
        role="img"
        aria-label={`Career WAR by year, ${minYear} through ${maxYear}`}
      >
        {/* Reference bands — peak tier (8 WAR) + floor tier (-1).
            Drawn faintly so they orient the eye without competing
            with the line. */}
        {yMax >= PEAK_TIER && (
          <line
            x1={padX}
            y1={yOf(PEAK_TIER)}
            x2={width - padX}
            y2={yOf(PEAK_TIER)}
            className="stroke-emerald-300 dark:stroke-emerald-700"
            strokeDasharray="3 4"
            strokeWidth={0.75}
          />
        )}
        {yMin <= FLOOR_TIER && (
          <line
            x1={padX}
            y1={yOf(FLOOR_TIER)}
            x2={width - padX}
            y2={yOf(FLOOR_TIER)}
            className="stroke-rose-300 dark:stroke-rose-700"
            strokeDasharray="3 4"
            strokeWidth={0.75}
          />
        )}
        {/* Zero baseline */}
        <line
          x1={padX}
          y1={baselineY}
          x2={width - padX}
          y2={baselineY}
          className="stroke-border-strong"
          strokeWidth={1}
        />
        {/* Career-WAR path */}
        <path
          d={pathD}
          className="stroke-content-secondary"
          fill="none"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {/* Per-season dots, colored by WAR magnitude */}
        {points.map((p) => (
          <g key={p.year}>
            <circle
              cx={xOf(p.year)}
              cy={yOf(p.war)}
              r={p.level_id === 1 ? 3.2 : 2.2}
              className={dotFillClass(p.war)}
              stroke="white"
              strokeOpacity={0.6}
              strokeWidth={0.75}
            >
              <title>
                {p.year} · {p.war.toFixed(1)} WAR ·{" "}
                {p.role === "both"
                  ? "two-way"
                  : p.role === "pitcher"
                    ? "pitching"
                    : "batting"}
                {p.league_abbr ? ` · ${p.league_abbr}` : ""}
              </title>
            </circle>
          </g>
        ))}
        {/* Year-axis ticks */}
        {tickYears.map((y) => (
          <text
            key={y}
            x={xOf(y)}
            y={height - 6}
            textAnchor="middle"
            className="fill-content-muted font-mono text-[9px]"
          >
            {y}
          </text>
        ))}
      </svg>
    </div>
  );
}

// Pick at most 6 evenly-spaced year ticks (always including first
// and last).
function pickTickYears(min: number, max: number): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  if (span <= 6) {
    // Show every year for short spans (most save-only careers).
    const out: number[] = [];
    for (let y = min; y <= max; y++) out.push(y);
    return out;
  }
  const ticks: number[] = [];
  const stride = Math.ceil(span / 5);
  for (let y = min; y <= max; y += stride) ticks.push(y);
  if (ticks[ticks.length - 1] !== max) ticks.push(max);
  return ticks;
}
