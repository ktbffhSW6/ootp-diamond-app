// Tab pills for /explore mode switching.
//
// Two modes:
//   - quick    — Diamond's curated ChartBuilder (scatter + histogram)
//   - workshop — embedded Metabase iframe (full BI surface)
//
// Mirrors the History `<ViewPill>` pattern — same look, same hover/
// active treatment, URL-driven (?mode=). Server component renders
// both states; no client JS needed for the picker itself.

import Link from "next/link";

interface Props {
  current: "quick" | "workshop";
}

export function ExploreModeTabs({ current }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <Pill
        href="/explore"
        active={current === "quick"}
        label="Quick chart"
        hint="Diamond curated · fast"
      />
      <Pill
        href="/explore?mode=workshop"
        active={current === "workshop"}
        label="Metabase Workshop"
        hint="Full BI · every chart · save + share"
      />
    </div>
  );
}

function Pill({
  href,
  active,
  label,
  hint,
}: {
  href: string;
  active: boolean;
  label: string;
  hint: string;
}) {
  return (
    <Link
      href={href}
      className={
        active
          ? "flex items-baseline gap-2 rounded-md border border-accent bg-accent/10 px-3 py-1.5 text-sm text-accent"
          : "flex items-baseline gap-2 rounded-md border border-border bg-surface-card px-3 py-1.5 text-sm text-content-secondary hover:border-border-strong hover:bg-surface-elevated"
      }
    >
      <span className="font-medium">{label}</span>
      <span className="text-[10px] text-content-muted">{hint}</span>
    </Link>
  );
}
