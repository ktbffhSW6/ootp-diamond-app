// MLB ballpark dimensions catalog.
//
// Distances are in feet from home plate to the outfield wall, measured
// at five anchor points: LF foul pole / left-center power alley /
// dead-center / right-center power alley / RF foul pole. Wall heights
// are in feet at LF / CF / RF (averaged across the listed segment for
// parks with stepped walls — Fenway gets its 37 ft Green Monster, but
// that's only the LF wall up to ~LCF; the data here is "what's the
// wall doing roughly here?" not a millimeter-accurate stadium model).
//
// `feature` flags signature visual flair we render specially:
//   - "green_monster" — Fenway's 37 ft LF wall (extra-thick LF segment)
//   - "short_porch"   — Yankee Stadium's 314 ft RF + low wall
//   - "ivy"           — Wrigley's outfield ivy (textured wall fill)
//   - "splash_hits"   — Oracle Park's McCovey Cove behind RF
//   - "the_train"     — Daikin Park's CF train track
//   - "dome"          — Rogers Centre / Tropicana retractable / fixed roof
//
// Sources: each park's Wikipedia article + MLB.com park-info pages
// (publicly listed dimensions, stable enough for a v1 silhouette).
//
// Convention: home plate is at coordinate (0, 0); +y points to dead
// center; +x to RF, -x to LF. Foul lines run at 45° (RF) and 135° (LF)
// from +x. The catalog stores DISTANCES; angles are computed in the
// renderer from the standard 5-point geometry.

export type StadiumFeature =
  | "green_monster"
  | "short_porch"
  | "ivy"
  | "splash_hits"
  | "the_train"
  | "dome";

export interface Stadium {
  team_abbr: string;
  name: string;
  // Wall distances (ft from home plate)
  lf_line: number;
  lcf: number;
  cf: number;
  rcf: number;
  rf_line: number;
  // Wall heights (ft)
  lf_wall_h: number;
  cf_wall_h: number;
  rf_wall_h: number;
  feature?: StadiumFeature;
  // Optional flavor text shown in the picker / chart caption
  blurb?: string;
}

// ─────────────────────────────────────────────────────────────────────
// All 30 MLB parks. Sorted alphabetically by team_abbr.
// ─────────────────────────────────────────────────────────────────────

export const MLB_STADIUMS: Record<string, Stadium> = {
  ARI: {
    team_abbr: "ARI", name: "Chase Field",
    lf_line: 330, lcf: 374, cf: 407, rcf: 374, rf_line: 334,
    lf_wall_h: 8, cf_wall_h: 25, rf_wall_h: 8,
    blurb: "Retractable roof, swimming pool in CF.",
  },
  ATH: {
    team_abbr: "ATH", name: "Sutter Health Park",
    lf_line: 330, lcf: 388, cf: 403, rcf: 388, rf_line: 326,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    blurb: "Athletics' temporary home in West Sacramento.",
  },
  ATL: {
    team_abbr: "ATL", name: "Truist Park",
    lf_line: 335, lcf: 375, cf: 400, rcf: 375, rf_line: 325,
    lf_wall_h: 8, cf_wall_h: 16, rf_wall_h: 8,
  },
  BAL: {
    team_abbr: "BAL", name: "Camden Yards",
    lf_line: 333, lcf: 410, cf: 410, rcf: 373, rf_line: 318,
    lf_wall_h: 7, cf_wall_h: 19, rf_wall_h: 21,
    blurb: "Eutaw Street + B&O Warehouse beyond RF.",
  },
  BOS: {
    team_abbr: "BOS", name: "Fenway Park",
    lf_line: 310, lcf: 379, cf: 390, rcf: 380, rf_line: 302,
    lf_wall_h: 37, cf_wall_h: 17, rf_wall_h: 5,
    feature: "green_monster",
    blurb: "Green Monster (37 ft LF wall) + Pesky's Pole.",
  },
  CHC: {
    team_abbr: "CHC", name: "Wrigley Field",
    lf_line: 355, lcf: 368, cf: 400, rcf: 368, rf_line: 353,
    lf_wall_h: 11, cf_wall_h: 11, rf_wall_h: 11,
    feature: "ivy",
    blurb: "Ivy-covered brick outfield walls.",
  },
  CIN: {
    team_abbr: "CIN", name: "Great American Ball Park",
    lf_line: 328, lcf: 379, cf: 404, rcf: 370, rf_line: 325,
    lf_wall_h: 12, cf_wall_h: 12, rf_wall_h: 12,
  },
  CLE: {
    team_abbr: "CLE", name: "Progressive Field",
    lf_line: 325, lcf: 370, cf: 405, rcf: 375, rf_line: 325,
    lf_wall_h: 19, cf_wall_h: 19, rf_wall_h: 9,
    blurb: "19 ft mini-Monster in LF.",
  },
  COL: {
    team_abbr: "COL", name: "Coors Field",
    lf_line: 347, lcf: 390, cf: 415, rcf: 375, rf_line: 350,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 14,
    blurb: "Largest outfield in MLB; mile-high air.",
  },
  CWS: {
    team_abbr: "CWS", name: "Rate Field",
    lf_line: 330, lcf: 377, cf: 400, rcf: 372, rf_line: 335,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
  },
  DET: {
    team_abbr: "DET", name: "Comerica Park",
    lf_line: 345, lcf: 370, cf: 420, rcf: 365, rf_line: 330,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    blurb: "Deep CF (420) — pitcher's park.",
  },
  HOU: {
    team_abbr: "HOU", name: "Daikin Park",
    lf_line: 315, lcf: 362, cf: 409, rcf: 373, rf_line: 326,
    lf_wall_h: 21, cf_wall_h: 9, rf_wall_h: 7,
    feature: "the_train",
    blurb: "Crawford Boxes (LF), train atop LF wall.",
  },
  KC: {
    team_abbr: "KC", name: "Kauffman Stadium",
    lf_line: 330, lcf: 387, cf: 410, rcf: 387, rf_line: 330,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    blurb: "Symmetric park, fountains beyond OF wall.",
  },
  LAA: {
    team_abbr: "LAA", name: "Angel Stadium",
    lf_line: 330, lcf: 372, cf: 396, rcf: 376, rf_line: 330,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 18,
    blurb: "California rocks beyond CF.",
  },
  LAD: {
    team_abbr: "LAD", name: "Dodger Stadium",
    lf_line: 330, lcf: 386, cf: 395, rcf: 386, rf_line: 330,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    blurb: "Pitcher's park, marine layer.",
  },
  MIA: {
    team_abbr: "MIA", name: "loanDepot park",
    lf_line: 344, lcf: 386, cf: 407, rcf: 392, rf_line: 335,
    lf_wall_h: 7, cf_wall_h: 7, rf_wall_h: 7,
    feature: "dome",
    blurb: "Retractable roof, deep dimensions.",
  },
  MIL: {
    team_abbr: "MIL", name: "American Family Field",
    lf_line: 344, lcf: 371, cf: 400, rcf: 374, rf_line: 345,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    feature: "dome",
    blurb: "Fan-shaped retractable roof.",
  },
  MIN: {
    team_abbr: "MIN", name: "Target Field",
    lf_line: 339, lcf: 377, cf: 404, rcf: 367, rf_line: 328,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 23,
    blurb: "Limestone façade, 23 ft RF wall.",
  },
  NYM: {
    team_abbr: "NYM", name: "Citi Field",
    lf_line: 335, lcf: 379, cf: 408, rcf: 383, rf_line: 330,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
  },
  NYY: {
    team_abbr: "NYY", name: "Yankee Stadium",
    lf_line: 318, lcf: 399, cf: 408, rcf: 385, rf_line: 314,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    feature: "short_porch",
    blurb: "Short RF porch — 314 ft + 8 ft wall.",
  },
  PHI: {
    team_abbr: "PHI", name: "Citizens Bank Park",
    lf_line: 329, lcf: 374, cf: 401, rcf: 369, rf_line: 330,
    lf_wall_h: 19, cf_wall_h: 13, rf_wall_h: 19,
  },
  PIT: {
    team_abbr: "PIT", name: "PNC Park",
    lf_line: 325, lcf: 389, cf: 399, rcf: 375, rf_line: 320,
    lf_wall_h: 6, cf_wall_h: 10, rf_wall_h: 21,
    blurb: "Roberto Clemente Wall (21 ft) in RF.",
  },
  SD: {
    team_abbr: "SD", name: "Petco Park",
    lf_line: 336, lcf: 384, cf: 396, rcf: 391, rf_line: 322,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
  },
  SEA: {
    team_abbr: "SEA", name: "T-Mobile Park",
    lf_line: 331, lcf: 378, cf: 401, rcf: 386, rf_line: 326,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    feature: "dome",
  },
  SF: {
    team_abbr: "SF", name: "Oracle Park",
    lf_line: 339, lcf: 382, cf: 399, rcf: 421, rf_line: 309,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 25,
    feature: "splash_hits",
    blurb: "McCovey Cove behind 25 ft RF wall; cavernous RCF.",
  },
  STL: {
    team_abbr: "STL", name: "Busch Stadium",
    lf_line: 336, lcf: 375, cf: 400, rcf: 372, rf_line: 335,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
  },
  TB: {
    team_abbr: "TB", name: "Tropicana Field",
    lf_line: 315, lcf: 370, cf: 404, rcf: 370, rf_line: 322,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    feature: "dome",
    blurb: "Fixed dome; catwalks (in-play).",
  },
  TEX: {
    team_abbr: "TEX", name: "Globe Life Field",
    lf_line: 329, lcf: 372, cf: 407, rcf: 374, rf_line: 326,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 8,
    feature: "dome",
    blurb: "Retractable roof.",
  },
  TOR: {
    team_abbr: "TOR", name: "Rogers Centre",
    lf_line: 328, lcf: 375, cf: 400, rcf: 375, rf_line: 328,
    lf_wall_h: 10, cf_wall_h: 10, rf_wall_h: 10,
    feature: "dome",
  },
  WSH: {
    team_abbr: "WSH", name: "Nationals Park",
    lf_line: 336, lcf: 377, cf: 402, rcf: 370, rf_line: 335,
    lf_wall_h: 8, cf_wall_h: 8, rf_wall_h: 14,
  },
};

export const DEFAULT_STADIUM = "BOS";

// ─────────────────────────────────────────────────────────────────────
// Distance estimation
//
// OOTP records exit_velo (mph) and launch_angle (degrees) per BIP, but
// not the actual hit distance. We synthesize a distance using a
// projectile model with empirical drag, then floor / cap by outcome
// type so HRs always clear the wall and ground balls don't end up at
// 400 ft from a freak velocity reading.
//
// Formula:
//   distance = (EV² × sin(2·LA)) / g  ×  drag_factor
// where g = 32.2 ft/s², EV in ft/s (= mph × 1.467), LA in radians.
// drag_factor empirically max ~0.65 around LA=28-32° and falls off at
// the extremes (chops, pop-ups).
//
// OOTP's EV scale runs ~5 mph below real Statcast, so distances come
// out shorter than they'd be in real life. We compensate by raising
// the HR floor — every HR clears the wall by at least the LF foul-pole
// distance × 1.05.
// ─────────────────────────────────────────────────────────────────────

const DEFAULT_DISTANCE_BY_RESULT: Record<number, number> = {
  4: 130, // GO
  5: 290, // FO
  6: 220, // 1B
  7: 320, // 2B
  8: 360, // 3B
  9: 380, // HR
};

export function estimateDistance(
  evMph: number | null,
  laDeg: number | null,
  result: number,
  parkLfLine = 310,
): number {
  if (evMph === null || laDeg === null) {
    return DEFAULT_DISTANCE_BY_RESULT[result] ?? 200;
  }

  const evFps = evMph * 1.467;
  const laRad = (laDeg * Math.PI) / 180;
  const noDrag = (evFps * evFps * Math.sin(2 * laRad)) / 32.2;

  // Drag factor: peak at LA ≈ 30°; falls off ~5% per 10° away. Floor
  // at 0.4 so chops + pop-ups don't go negative.
  const dragFactor = Math.max(0.4, 0.65 - 0.005 * Math.abs(laDeg - 30));
  let distance = noDrag * dragFactor;

  // HR floor: must clear at least the foul pole + a buffer.
  if (result === 9) {
    distance = Math.max(distance, parkLfLine * 1.05);
  }

  // Cap to keep extreme outliers on-screen.
  return Math.max(20, Math.min(450, distance));
}

// ─────────────────────────────────────────────────────────────────────
// Spray-angle conversion
//
// OOTP encodes spray as `hit_xy` ∈ [0, 255] (BATTER-RELATIVE per D39
// HR-cluster analysis — LHB and RHB HRs both mean ≈71, confirming low
// hit_xy = pull side regardless of bat hand). Earlier versions of this
// code clamped at 130, which mis-rendered ~30% of events at the oppo
// foul line; fixed in Phase 4a-extended-3 (2026-05-10).
//
//   0   = pull-side foul line
//   128 = center
//   255 = oppo-side foul line
//
// Convert to a "field-absolute" angle in degrees, where 0° = +x (RF
// foul pole direction) and 90° = +y (CF). The result depends on
// handedness because the FIELD orientation depends on bat hand:
//   - RHB: pull = LF, oppo = RF, so hit_xy=0 maps to LF (135°) and
//     hit_xy=255 maps to RF (45°).
//   - LHB: pull = RF, oppo = LF, so hit_xy=0 maps to RF (45°) and
//     hit_xy=255 maps to LF (135°).
//   - SH (switch hitters): we'd need pitcher-handedness to resolve.
//     v1 fallback: render as RHB. The fielding-side resolution lives
//     on the situational-splits side; here we pick a default.
// ─────────────────────────────────────────────────────────────────────

export function fieldAngleDeg(
  hitXy: number,
  handedness: "L" | "R" | "S",
): number {
  const t = Math.max(0, Math.min(255, hitXy)) / 255; // [0, 1]
  if (handedness === "L") {
    // Pull = RF (45°) → oppo = LF (135°)
    return 45 + t * 90;
  }
  // Default RHB / SH: pull = LF (135°) → oppo = RF (45°)
  return 135 - t * 90;
}
