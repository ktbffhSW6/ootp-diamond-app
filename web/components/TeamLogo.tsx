// TeamLogo — square OOTP-rendered team logo with abbreviation fallback.
//
// Mirrors PlayerAvatar's pattern: tries to load the OOTP-pre-rendered
// PNG via `/api/photos/teams/{team_id}.png` (size-snapped to the nearest
// available variant); on 404 / network failure, falls back to a
// monospace pill with the team abbreviation. Keeps the layout stable
// when a team's logo file isn't on disk yet (rare on healthy saves —
// OOTP writes them automatically).
//
// Sizes:
//   - "xs" 16px — table inline-cell prefix
//   - "sm" 20px — dense rows
//   - "md" 28px — standings rows / movement ledger
//   - "lg" 40px — card primary
//   - "xl" 64px — header / hero
//
// The size param is forwarded as `?size=N` to the API so we hit the
// closest pre-rendered variant on disk (16/25/40/50/110/full). Smaller
// payload + no client-side downscaling.

"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Size = "xs" | "sm" | "md" | "lg" | "xl";

const SIZE_PX: Record<Size, number> = {
  xs: 16,
  sm: 20,
  md: 28,
  lg: 40,
  xl: 64,
};

const SIZE_TEXT_CLASS: Record<Size, string> = {
  xs: "text-[8px]",
  sm: "text-[9px]",
  md: "text-[10px]",
  lg: "text-xs",
  xl: "text-base",
};

export interface TeamLogoProps {
  teamId: number | null | undefined;
  /** Team abbreviation — used for the fallback pill + the alt attribute. */
  abbr?: string | null;
  size?: Size;
  className?: string;
}

export function TeamLogo({
  teamId,
  abbr,
  size = "md",
  className = "",
}: TeamLogoProps) {
  const [errored, setErrored] = useState(false);
  const px = SIZE_PX[size];
  const textCls = SIZE_TEXT_CLASS[size];

  // No team_id at all — render the abbr pill directly.
  if (teamId == null) {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center rounded-sm border border-border bg-surface-elevated px-1 font-mono uppercase tabular-nums text-content-muted ${textCls} ${className}`}
        style={{ minWidth: px, height: px }}
      >
        {(abbr ?? "—").slice(0, 4)}
      </span>
    );
  }

  if (errored) {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center rounded-sm border border-border bg-surface-elevated px-1 font-mono uppercase tabular-nums text-content-secondary ${textCls} ${className}`}
        style={{ minWidth: px, height: px }}
        aria-label={abbr ?? `team ${teamId}`}
      >
        {(abbr ?? `T${teamId}`).slice(0, 4)}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: px, height: px }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${API_URL}/api/photos/teams/${teamId}.png?size=${px}`}
        alt={abbr ?? `team ${teamId}`}
        width={px}
        height={px}
        loading="lazy"
        decoding="async"
        onError={() => setErrored(true)}
        className="h-full w-full object-contain"
      />
    </span>
  );
}
