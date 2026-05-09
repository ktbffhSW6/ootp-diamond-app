// PlayerAvatar — circular headshot with initials fallback.
//
// Tries to load the OOTP-generated face from the API
// (`/api/photos/players/{id}.png`); on 404 / network failure, falls
// back to a deterministic-color initials disc. Keeps rendering
// consistent for players whose photos OOTP didn't generate (most
// pre-1990 imported real-history players).
//
// Sizes are presets so the component looks right at every callsite
// without per-call style math:
//   - "xs" 20px — table row inline
//   - "sm" 32px — card secondary
//   - "md" 48px — card primary / spotlight
//   - "lg" 80px — player page hero
//
// Initials are first-letter-first-name + first-letter-last-name
// from the display name. Color is picked deterministically from
// the player_id so the same player always gets the same fallback
// color (instead of flickering across reloads).

"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Size = "xs" | "sm" | "md" | "lg";

const SIZE_PX: Record<Size, number> = {
  xs: 20,
  sm: 32,
  md: 48,
  lg: 80,
};

const SIZE_TEXT_CLASS: Record<Size, string> = {
  xs: "text-[8px]",
  sm: "text-[10px]",
  md: "text-sm",
  lg: "text-xl",
};

// Eight stable hue rotations for the initials fallback. Hash the
// player_id to pick one — same player always gets the same color
// across reloads / pages.
const FALLBACK_PALETTE = [
  "bg-sky-200 text-sky-900 dark:bg-sky-800/60 dark:text-sky-100",
  "bg-emerald-200 text-emerald-900 dark:bg-emerald-800/60 dark:text-emerald-100",
  "bg-amber-200 text-amber-900 dark:bg-amber-800/60 dark:text-amber-100",
  "bg-rose-200 text-rose-900 dark:bg-rose-800/60 dark:text-rose-100",
  "bg-violet-200 text-violet-900 dark:bg-violet-800/60 dark:text-violet-100",
  "bg-indigo-200 text-indigo-900 dark:bg-indigo-800/60 dark:text-indigo-100",
  "bg-teal-200 text-teal-900 dark:bg-teal-800/60 dark:text-teal-100",
  "bg-fuchsia-200 text-fuchsia-900 dark:bg-fuchsia-800/60 dark:text-fuchsia-100",
];

function pickFallbackColor(playerId: number): string {
  return FALLBACK_PALETTE[playerId % FALLBACK_PALETTE.length];
}

function initialsFor(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export interface PlayerAvatarProps {
  playerId: number;
  displayName: string;
  size?: Size;
  /** Optional className to merge (e.g., to add a ring on the active player). */
  className?: string;
}

export function PlayerAvatar({
  playerId,
  displayName,
  size = "sm",
  className = "",
}: PlayerAvatarProps) {
  const [errored, setErrored] = useState(false);
  const px = SIZE_PX[size];
  const textCls = SIZE_TEXT_CLASS[size];
  const baseCls = `inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full ring-1 ring-border ${className}`;

  if (errored) {
    const palette = pickFallbackColor(playerId);
    return (
      <span
        className={`${baseCls} ${palette} ${textCls} font-semibold uppercase tabular-nums`}
        style={{ width: px, height: px }}
        aria-label={displayName}
      >
        {initialsFor(displayName)}
      </span>
    );
  }

  // OOTP photos are 100×100 PNG; the rounded-full container crops
  // them to a circle. Setting decoding=async + loading=lazy keeps
  // dense rosters/spotlight grids from blocking on a wave of
  // simultaneous photo loads.
  return (
    <span
      className={`${baseCls} bg-surface-elevated`}
      style={{ width: px, height: px }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${API_URL}/api/photos/players/${playerId}.png`}
        alt={displayName}
        width={px}
        height={px}
        loading="lazy"
        decoding="async"
        onError={() => setErrored(true)}
        className="h-full w-full object-cover"
      />
    </span>
  );
}
