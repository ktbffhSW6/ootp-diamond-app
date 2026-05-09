// PlayerTabNav — query-string-driven tab strip for /player/[id].
//
// Tab state lives in `?tab=`; the player page server component reads
// it and conditionally renders the active tab's content. Server-only
// (just <Link>s) so we don't need a client component for nav state.
//
// Disabled tabs render as muted spans with `title="Coming soon"`. The
// "Charts" tab gates on whether the player has any MLB BIP data —
// pitchers / non-MLB call-ups don't get a tab they can't see anything
// in.

import Link from "next/link";

export type PlayerTab =
  | "stats"
  | "charts"
  | "ai"
  | "game-log"
  | "comparisons"
  | "scouting";

interface Tab {
  id: PlayerTab;
  label: string;
  enabled: boolean;
  hint?: string;
}

interface Props {
  active: PlayerTab;
  playerId: number;
  hasBip: boolean;
}

export function PlayerTabNav({ active, playerId, hasBip }: Props) {
  const tabs: Tab[] = [
    { id: "stats", label: "Stats", enabled: true },
    {
      id: "charts",
      label: "Charts",
      enabled: hasBip,
      hint: hasBip ? undefined : "No BIP at MLB",
    },
    { id: "ai", label: "AI Summary", enabled: true },
    { id: "game-log", label: "Game log", enabled: false, hint: "Coming soon" },
    {
      id: "comparisons",
      label: "Comparisons",
      enabled: false,
      hint: "Coming soon",
    },
    { id: "scouting", label: "Scouting", enabled: false, hint: "Coming soon" },
  ];

  return (
    <nav className="flex flex-wrap items-center gap-1 border-b border-border text-sm">
      {tabs.map((t) => {
        const isActive = t.id === active;
        if (!t.enabled) {
          return (
            <span
              key={t.id}
              className="cursor-not-allowed px-3 py-1.5 text-content-muted"
              title={t.hint ?? "Coming soon"}
            >
              {t.label}
            </span>
          );
        }
        const className = isActive
          ? "border-b-2 border-content-primary px-3 py-1.5 font-semibold text-content-primary"
          : "px-3 py-1.5 text-content-secondary hover:text-content-primary";
        return (
          <Link
            key={t.id}
            href={`/player/${playerId}?tab=${t.id}`}
            className={className}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
