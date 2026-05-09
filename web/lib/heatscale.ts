// Heat-scale color helpers — central source of truth for "how vivid
// should this stat cell be?" across roster, player Advanced, pressure
// board, cockpit, and any future leaderboard view.
//
// Two scales exist:
//
// 1. **Hundred-relative** — for OPS+ / wRC+ / ERA+ / FIP+ where 100 =
//    league average and higher = better. Used everywhere a metric has
//    been park-adjusted + league-normalized.
//
// 2. **WAR-magnitude** — for any single-season WAR figure. Independent
//    of league baseline; sub-replacement is rose, MVP-ish is blazing
//    emerald. Same buckets every year; doesn't try to normalize across
//    eras (modern WAR distributions are stable enough).
//
// Both functions return a Tailwind class string. Callers just spread
// it onto a `<td>` or `<span>` className. Per Decision D18, dark-mode
// variants are paired explicitly so contrast holds in dark / neutral
// themes. The CB theme inherits the chrome but not the verdict colors —
// that's a known v1 limitation tracked in BACKLOG.
//
// Bucket philosophy: five intensities per side (mild / moderate /
// strong / vivid / blazing) plus a neutral band around average. The
// neutral band intentionally covers ~20 points around 100 so the eye
// only catches genuinely above- or below-average performance — small
// deviations stay quiet.

// ─────────────────────────────────────────────────────────────────────
// 100-relative scale
// ─────────────────────────────────────────────────────────────────────

/**
 * Tailwind class string for a metric where 100 = league average and
 * higher = better (OPS+ / wRC+ / ERA+ / FIP+).
 *
 * Bands:
 *   ≥ 200          blazing emerald   (Bonds 2001 / Pedro 2000 territory)
 *   ≥ 160          vivid emerald     (MVP-tier season)
 *   ≥ 130          strong emerald    (All-Star)
 *   ≥ 110          moderate emerald  (above average)
 *    91 – 109      neutral
 *   ≤  89          moderate rose
 *   ≤  70          strong rose       (replacement-level red flag)
 *   ≤  40          vivid rose
 *   ≤  20          blazing rose      (Mendoza-line + park penalty)
 *
 * Returns an empty string for null inputs so the cell can stay blank.
 */
export function plusMinusClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  if (value >= 200)
    return "bg-emerald-200 text-emerald-900 font-semibold dark:bg-emerald-900/60 dark:text-emerald-100";
  if (value >= 160)
    return "bg-emerald-100 text-emerald-900 font-semibold dark:bg-emerald-900/40 dark:text-emerald-200";
  if (value >= 130)
    return "text-emerald-700 font-semibold dark:text-emerald-400";
  if (value >= 110) return "text-emerald-600 dark:text-emerald-400";
  if (value <= 20)
    return "bg-rose-200 text-rose-900 font-semibold dark:bg-rose-900/60 dark:text-rose-100";
  if (value <= 40)
    return "bg-rose-100 text-rose-900 font-semibold dark:bg-rose-900/40 dark:text-rose-200";
  if (value <= 70) return "text-rose-700 font-semibold dark:text-rose-400";
  if (value <= 89) return "text-rose-600 dark:text-rose-400";
  return "text-content-secondary";
}

// ─────────────────────────────────────────────────────────────────────
// WAR-magnitude scale
// ─────────────────────────────────────────────────────────────────────

/**
 * Tailwind class for a single-season WAR figure. Bands chosen to
 * roughly match Fangraphs' WAR scale convention:
 *
 *   ≥ 8.0     MVP-tier        — blazing emerald
 *   ≥ 5.0     All-Star        — vivid emerald
 *   ≥ 3.0     solid starter   — strong emerald
 *   ≥ 1.0     role player     — moderate emerald
 *   0 – 0.99  scrub / depth   — neutral
 *   < 0       sub-replacement — rose intensity scales with how negative
 *
 * Career-WAR cells should use `plusMinusClass` semantics adapted by
 * caller, since career WAR has a different range; this fn is for
 * single-season cells only.
 */
export function warSeasonClass(war: number | null | undefined): string {
  if (war === null || war === undefined || Number.isNaN(war)) return "";
  if (war >= 8.0)
    return "bg-emerald-100 text-emerald-900 font-semibold dark:bg-emerald-900/40 dark:text-emerald-200";
  if (war >= 5.0) return "text-emerald-700 font-semibold dark:text-emerald-400";
  if (war >= 3.0) return "text-emerald-600 dark:text-emerald-400";
  if (war >= 1.0) return "text-emerald-600/80 dark:text-emerald-500";
  if (war <= -2.0)
    return "bg-rose-100 text-rose-900 font-semibold dark:bg-rose-900/40 dark:text-rose-200";
  if (war <= -1.0) return "text-rose-700 font-semibold dark:text-rose-400";
  if (war < 0) return "text-rose-600 dark:text-rose-400";
  return "text-content-secondary";
}

// ─────────────────────────────────────────────────────────────────────
// Delta scale (for pressure-board "delta vs 100" view)
// ─────────────────────────────────────────────────────────────────────

/**
 * Same buckets as `plusMinusClass` but driven by a delta (metric −
 * 100). Keeps pressure-board semantics aligned with the rest of the
 * heat scale. Equivalent to `plusMinusClass(100 + delta)`; provided as
 * a separate fn so call sites read clearly.
 */
export function deltaClass(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return "";
  return plusMinusClass(100 + delta);
}
