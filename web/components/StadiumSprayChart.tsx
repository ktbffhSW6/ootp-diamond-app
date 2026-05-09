"use client";

// StadiumSprayChart — Savant-style hit-scatter overlay on a real
// ballpark silhouette.
//
// Per-BIP coordinates are synthesized from OOTP's (hit_xy, exit_velo,
// launch_angle) triple: hit_xy → field-absolute spray angle, EV+LA →
// estimated distance via projectile physics with drag (lib/stadiums).
// Dots are colored by outcome (out muted / hit saturated / HR loud).
//
// Stadium dimensions are hand-coded for all 30 MLB parks (lib/stadiums)
// from official wall distances. Renderer draws:
//   - Foul lines from home plate to LF / RF foul poles
//   - Outfield wall as a Catmull-Rom spline through 5 anchor points
//     (LF / LCF / CF / RCF / RF)
//   - Outfield grass + infield dirt fills
//   - Wall-height annotations at LF / CF / RF
//   - Park-specific feature flair: Green Monster (extra-thick LF
//     segment + label), Yankees short porch (notched RF wall),
//     Wrigley ivy (textured fill), Oracle splash hits (cove behind
//     RF), Daikin train (CF rail), retractable-dome label
//
// Coordinate system: home plate at (0, 0); +y to CF; +x to RF.
// SVG flips y so home plate sits at the bottom of the viewBox.

import { useState } from "react";

import {
  DEFAULT_STADIUM,
  estimateDistance,
  fieldAngleDeg,
  MLB_STADIUMS,
  type Stadium,
} from "@/lib/stadiums";
import type { BattedBallEvent } from "@/lib/types/api";

// Result-code → label / color (out muted, hit saturated, HR loud).
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
const RESULT_ORDER = [4, 5, 6, 7, 8, 9]; // out → hit → HR (z-order)

// SVG viewBox: 500 wide × 480 tall; home plate at (250, 460); 1 ft = 1
// SVG unit (so distances ~ 0-450 map naturally to the viewBox).
const VIEW_W = 500;
const VIEW_H = 480;
const HOME_X = 250;
const HOME_Y = 460;

interface Props {
  rows: BattedBallEvent[];
  handedness: "L" | "R" | "S";
  defaultStadium?: string;
  pickerEnabled?: boolean;
}

export function StadiumSprayChart({
  rows,
  handedness,
  defaultStadium = DEFAULT_STADIUM,
  pickerEnabled = true,
}: Props) {
  const [stadiumKey, setStadiumKey] = useState(defaultStadium);
  const [showOuts, setShowOuts] = useState(true);
  const stadium = MLB_STADIUMS[stadiumKey] ?? MLB_STADIUMS[DEFAULT_STADIUM];

  // Compute (x, y) coords in baseball feet for each BIP, then convert
  // to SVG coords once. Filter to in-arc events; outliers (hit_xy >
  // 130) are excluded.
  const points = rows
    .filter((r) => r.hit_xy !== null && r.hit_xy >= 0 && r.hit_xy <= 130)
    .map((r) => {
      const angleDeg = fieldAngleDeg(r.hit_xy!, handedness);
      const distance = estimateDistance(
        r.exit_velo,
        r.launch_angle,
        r.result,
        stadium.lf_line,
      );
      const angleRad = (angleDeg * Math.PI) / 180;
      // Baseball coords: x_bb = distance·cos(angle), y_bb = distance·sin(angle)
      const xBb = distance * Math.cos(angleRad);
      const yBb = distance * Math.sin(angleRad);
      // SVG coords: home plate at (HOME_X, HOME_Y); +y goes up (toward
      // CF), so SVG y = HOME_Y - y_bb.
      return {
        ...r,
        svg_x: HOME_X + xBb,
        svg_y: HOME_Y - yBb,
        distance,
      };
    });

  const filteredPoints = showOuts
    ? points
    : points.filter((p) => p.result === 6 || p.result === 7 || p.result === 8 || p.result === 9);

  const totalBy = (codes: number[]) =>
    points.filter((p) => codes.includes(p.result)).length;

  return (
    <div className="space-y-3">
      {/* Picker bar */}
      {pickerEnabled && (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface-card p-3">
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              Stadium overlay
            </label>
            <select
              value={stadiumKey}
              onChange={(e) => setStadiumKey(e.target.value)}
              className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
            >
              {Object.values(MLB_STADIUMS)
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((s) => (
                  <option key={s.team_abbr} value={s.team_abbr}>
                    {s.team_abbr} · {s.name}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              Show outs
            </label>
            <button
              onClick={() => setShowOuts((s) => !s)}
              className={`rounded px-3 py-1.5 text-xs ${
                showOuts
                  ? "bg-accent text-white"
                  : "border border-border bg-surface-page text-content-secondary hover:border-border-strong"
              }`}
            >
              {showOuts ? "On" : "Off"}
            </button>
          </div>
          <div className="ml-auto text-right">
            <p className="text-xs uppercase tracking-wide text-content-muted">
              {stadium.name}
            </p>
            <p className="text-xs text-content-secondary">
              {stadium.lf_line}–{stadium.cf}–{stadium.rf_line} ft (LF/CF/RF)
              {stadium.feature && (
                <span className="ml-2 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/25 dark:text-amber-300">
                  {featureLabel(stadium.feature)}
                </span>
              )}
            </p>
          </div>
        </div>
      )}

      {/* Chart — capped at 720px wide so the field doesn't balloon
          on ultrawide monitors (the 500×480 viewBox at full container
          width would be 1500px+ tall on a 1920 panel). The aspectRatio
          style + max-w give us a faithful field shape that doesn't
          eat the whole page. */}
      <div className="mx-auto max-w-[720px] rounded-md border border-border bg-surface-card p-2">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="block w-full"
          style={{ aspectRatio: `${VIEW_W} / ${VIEW_H}` }}
        >
          <FieldShape stadium={stadium} />

          {/* Hit-distance reference rings (200 ft, 300 ft, 400 ft) */}
          <DistanceRings />

          {/* Dots — render in z-order so HR sits on top */}
          {RESULT_ORDER.map((code) => (
            <g key={code}>
              {filteredPoints
                .filter((p) => p.result === code)
                .map((p, i) => (
                  <circle
                    key={`${code}-${i}`}
                    cx={p.svg_x}
                    cy={p.svg_y}
                    r={code === 9 ? 4.5 : 3.5}
                    fill={RESULT_COLORS[code]}
                    fillOpacity={code <= 5 ? 0.6 : 0.85}
                    stroke="rgba(15, 23, 42, 0.4)"
                    strokeWidth={0.5}
                  >
                    <title>
                      {RESULT_LABELS[code]} · {Math.round(p.distance)} ft
                      {p.exit_velo !== null
                        ? ` · ${p.exit_velo.toFixed(1)} mph`
                        : ""}
                      {p.launch_angle !== null ? ` · ${p.launch_angle}°` : ""}
                    </title>
                  </circle>
                ))}
            </g>
          ))}
        </svg>
      </div>

      {/* Legend + summary */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {RESULT_ORDER.map((code) => (
          <span key={code} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: RESULT_COLORS[code] }}
            />
            <span className="text-content-secondary">
              {RESULT_LABELS[code]}
              <span className="ml-1 text-content-muted">
                {totalBy([code])}
              </span>
            </span>
          </span>
        ))}
        <span className="ml-auto text-content-muted">
          {filteredPoints.length}/{points.length} BIP shown · distance
          synthesized from EV+LA
        </span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────

function featureLabel(f: string): string {
  return {
    green_monster: "Green Monster",
    short_porch: "Short porch",
    ivy: "Ivy",
    splash_hits: "Splash hits",
    the_train: "Train",
    dome: "Dome",
  }[f] ?? f;
}

// FieldShape — draws the stadium silhouette: foul ground, infield
// dirt, outfield grass, foul lines, outfield wall, wall-height
// annotations + park feature flair.
function FieldShape({ stadium }: { stadium: Stadium }) {
  // Anchor points in baseball coords (ft from home plate).
  // LF foul = 135°, LCF = 112.5°, CF = 90°, RCF = 67.5°, RF foul = 45°
  const anchors = [
    { name: "LF", deg: 135, dist: stadium.lf_line, height: stadium.lf_wall_h },
    { name: "LCF", deg: 112.5, dist: stadium.lcf, height: stadium.cf_wall_h },
    { name: "CF", deg: 90, dist: stadium.cf, height: stadium.cf_wall_h },
    { name: "RCF", deg: 67.5, dist: stadium.rcf, height: stadium.cf_wall_h },
    { name: "RF", deg: 45, dist: stadium.rf_line, height: stadium.rf_wall_h },
  ];
  const pts = anchors.map((a) => {
    const r = (a.deg * Math.PI) / 180;
    return {
      ...a,
      x: HOME_X + a.dist * Math.cos(r),
      y: HOME_Y - a.dist * Math.sin(r),
    };
  });

  // Smooth Catmull-Rom curve through the wall anchor points, converted
  // to cubic Bezier segments (standard CR→Bezier formula). Falls back
  // to straight lines if there are fewer than 3 anchors.
  const wallPath = catmullRomToBezier(pts.map((p) => [p.x, p.y]));

  // Closed field path: LF foul → wall → RF foul → home
  const fieldPath = `M ${HOME_X} ${HOME_Y} L ${pts[0].x} ${pts[0].y} ${wallPath} L ${HOME_X} ${HOME_Y} Z`;

  // Infield diamond (90 ft basepaths). Arc + foul corners.
  const infieldR = 90 * Math.SQRT2; // 90 ft × √2 = ~127 ft to 2B
  const infieldPath = (() => {
    const left = HOME_X - 90;
    const right = HOME_X + 90;
    const top = HOME_Y - infieldR;
    return `M ${HOME_X} ${HOME_Y} L ${left} ${HOME_Y - 90} L ${HOME_X} ${top} L ${right} ${HOME_Y - 90} Z`;
  })();

  return (
    <g>
      {/* Foul ground (subtle) */}
      <rect
        x={0}
        y={HOME_Y - stadium.lf_line - 30}
        width={VIEW_W}
        height={stadium.lf_line + 60}
        fill="rgba(148, 163, 184, 0.05)"
      />

      {/* Outfield + foul-line-bounded fair territory */}
      <path
        d={fieldPath}
        fill="rgba(34, 197, 94, 0.08)"
        stroke="none"
      />

      {/* Park feature: extra-thick LF segment for Green Monster, etc. */}
      <FeatureOverlay stadium={stadium} pts={pts} />

      {/* Outfield wall — drawn last so it sits on top */}
      <path
        d={`M ${pts[0].x} ${pts[0].y} ${wallPath}`}
        fill="none"
        stroke="rgba(71, 85, 105, 0.85)"
        strokeWidth={2}
      />

      {/* Foul lines */}
      <line
        x1={HOME_X}
        y1={HOME_Y}
        x2={pts[0].x}
        y2={pts[0].y}
        stroke="rgba(148, 163, 184, 0.65)"
        strokeWidth={1.2}
      />
      <line
        x1={HOME_X}
        y1={HOME_Y}
        x2={pts[4].x}
        y2={pts[4].y}
        stroke="rgba(148, 163, 184, 0.65)"
        strokeWidth={1.2}
      />

      {/* Infield diamond */}
      <path
        d={infieldPath}
        fill="rgba(245, 158, 11, 0.12)"
        stroke="rgba(148, 163, 184, 0.5)"
        strokeWidth={1}
      />

      {/* Wall-distance labels at LF / CF / RF */}
      {[0, 2, 4].map((idx) => {
        const p = pts[idx];
        const label = p.name === "CF" ? `${p.dist} ft` : `${p.dist}`;
        // Push the label outward so it sits beyond the wall
        const r = (p.deg * Math.PI) / 180;
        const labelX = HOME_X + (p.dist + 14) * Math.cos(r);
        const labelY = HOME_Y - (p.dist + 14) * Math.sin(r);
        return (
          <text
            key={p.name}
            x={labelX}
            y={labelY}
            textAnchor="middle"
            fontSize="10"
            className="fill-content-secondary"
          >
            {label}
          </text>
        );
      })}

      {/* Wall-height labels — only render where height ≥ 12 ft (i.e.,
          worth pointing out; everything else is the standard ~8 ft
          modern-era wall) */}
      {pts
        .filter((p) => p.height >= 12 && (p.name === "LF" || p.name === "CF" || p.name === "RF"))
        .map((p) => {
          const r = (p.deg * Math.PI) / 180;
          const labelX = HOME_X + (p.dist - 18) * Math.cos(r);
          const labelY = HOME_Y - (p.dist - 18) * Math.sin(r);
          return (
            <text
              key={`h-${p.name}`}
              x={labelX}
              y={labelY}
              textAnchor="middle"
              fontSize="9"
              className="fill-content-muted"
            >
              {p.height}&apos;
            </text>
          );
        })}

      {/* Home plate */}
      <circle cx={HOME_X} cy={HOME_Y} r={3} fill="rgba(100, 116, 139, 0.9)" />
    </g>
  );
}

// FeatureOverlay — park-specific visual flair.
function FeatureOverlay({
  stadium,
  pts,
}: {
  stadium: Stadium;
  pts: { name: string; deg: number; dist: number; x: number; y: number }[];
}) {
  if (!stadium.feature) return null;
  if (stadium.feature === "green_monster") {
    // Thicken the LF→LCF segment to evoke the Monster's bulk
    return (
      <g>
        <path
          d={`M ${pts[0].x} ${pts[0].y} Q ${(pts[0].x + pts[1].x) / 2} ${(pts[0].y + pts[1].y) / 2} ${pts[1].x} ${pts[1].y}`}
          fill="none"
          stroke="rgba(34, 197, 94, 0.7)"
          strokeWidth={6}
          strokeLinecap="round"
        />
        <text
          x={(pts[0].x + pts[1].x) / 2 - 12}
          y={(pts[0].y + pts[1].y) / 2 - 8}
          fontSize="9"
          fontWeight="600"
          className="fill-emerald-700 dark:fill-emerald-400"
        >
          MONSTER
        </text>
      </g>
    );
  }
  if (stadium.feature === "ivy") {
    // Stippled green along the wall to evoke ivy
    return (
      <path
        d={`M ${pts[0].x} ${pts[0].y} ${catmullRomToBezier(pts.map((p) => [p.x, p.y]))}`}
        fill="none"
        stroke="rgba(34, 197, 94, 0.55)"
        strokeWidth={4}
        strokeDasharray="2,2"
      />
    );
  }
  if (stadium.feature === "short_porch") {
    // Highlight RF segment in indigo to evoke the porch
    return (
      <g>
        <path
          d={`M ${pts[3].x} ${pts[3].y} Q ${(pts[3].x + pts[4].x) / 2} ${(pts[3].y + pts[4].y) / 2} ${pts[4].x} ${pts[4].y}`}
          fill="none"
          stroke="rgba(99, 102, 241, 0.55)"
          strokeWidth={4}
        />
        <text
          x={pts[4].x - 4}
          y={pts[4].y + 14}
          fontSize="9"
          fontWeight="600"
          className="fill-indigo-700 dark:fill-indigo-400"
        >
          PORCH
        </text>
      </g>
    );
  }
  if (stadium.feature === "splash_hits") {
    // Blue band beyond RF to evoke McCovey Cove
    return (
      <g>
        <path
          d={`M ${pts[4].x - 8} ${pts[4].y - 4} L ${pts[4].x + 30} ${pts[4].y - 24} L ${pts[4].x + 24} ${pts[4].y + 18} L ${pts[4].x - 8} ${pts[4].y + 14} Z`}
          fill="rgba(59, 130, 246, 0.25)"
          stroke="rgba(59, 130, 246, 0.4)"
          strokeWidth={1}
        />
        <text
          x={pts[4].x + 12}
          y={pts[4].y - 4}
          fontSize="9"
          fontWeight="600"
          className="fill-sky-700 dark:fill-sky-400"
        >
          COVE
        </text>
      </g>
    );
  }
  if (stadium.feature === "the_train") {
    // CF rail line
    return (
      <line
        x1={pts[1].x - 8}
        y1={pts[2].y - 6}
        x2={pts[3].x + 8}
        y2={pts[2].y - 6}
        stroke="rgba(120, 113, 108, 0.7)"
        strokeWidth={2}
        strokeDasharray="6,3"
      />
    );
  }
  if (stadium.feature === "dome") {
    // Faint roof arc
    return (
      <path
        d={`M ${pts[0].x - 10} ${pts[0].y} Q ${HOME_X} ${pts[2].y - 60} ${pts[4].x + 10} ${pts[4].y}`}
        fill="none"
        stroke="rgba(148, 163, 184, 0.4)"
        strokeWidth={1.5}
        strokeDasharray="4,4"
      />
    );
  }
  return null;
}

// DistanceRings — concentric arcs at 200 / 300 / 400 ft for spatial
// reference. Drawn in fair territory only (between foul lines).
function DistanceRings() {
  const rings = [200, 300, 400];
  return (
    <g>
      {rings.map((d) => (
        <g key={d}>
          <path
            d={`M ${HOME_X - d * Math.cos(Math.PI / 4)} ${HOME_Y - d * Math.sin(Math.PI / 4)} A ${d} ${d} 0 0 1 ${HOME_X + d * Math.cos(Math.PI / 4)} ${HOME_Y - d * Math.sin(Math.PI / 4)}`}
            fill="none"
            stroke="rgba(148, 163, 184, 0.18)"
            strokeWidth={0.7}
            strokeDasharray="3,4"
          />
          <text
            x={HOME_X + 4}
            y={HOME_Y - d}
            fontSize="8"
            className="fill-content-muted"
          >
            {d}
          </text>
        </g>
      ))}
    </g>
  );
}

// Catmull-Rom → cubic Bezier conversion. Returns the trailing portion
// of an SVG path string starting after the initial M — caller
// pre-pends `M ${pts[0].x} ${pts[0].y}` as the starting point.
function catmullRomToBezier(pts: number[][]): string {
  if (pts.length < 2) return "";
  const out: string[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
    out.push(`C ${cp1x} ${cp1y} ${cp2x} ${cp2y} ${p2[0]} ${p2[1]}`);
  }
  return out.join(" ");
}
