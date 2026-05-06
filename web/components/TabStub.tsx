// Generic stub for top-level tabs whose content hasn't been built yet
// (League / World / History / Explore as of 2026-05-08). Renders a
// header + a grid of "what will go here" sections, each with a status
// pill. Keeps the IA visible to the user without pretending features
// exist before they ship.
//
// All sections currently render as `soon` — when an entry goes live,
// flip its `status` to `"live"` and add an `href`, and the card
// becomes click-through.

import Link from "next/link";

export type StubSectionStatus = "live" | "soon";
export type StubSection = {
  title: string;
  status: StubSectionStatus;
  blurb: string;
  href?: string | null;
};

export function TabStub({
  title,
  blurb,
  sections,
}: {
  title: string;
  blurb: string;
  sections: StubSection[];
}) {
  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          Section
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {title}
        </h1>
        <p className="max-w-2xl text-sm text-content-secondary">{blurb}</p>
      </header>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-content-primary">
          What goes here
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {sections.map((s) => (
            <SectionCard key={s.title} section={s} />
          ))}
        </div>
      </section>

      <p className="border-t border-border pt-4 text-xs text-content-muted">
        These cards are placeholders &mdash; each lights up as its data source
        ships. The IA is committed; only content is pending.
      </p>
    </div>
  );
}

function SectionCard({ section }: { section: StubSection }) {
  const inner = (
    <div className="flex h-full flex-col gap-2 rounded-md border border-border bg-surface-card p-4 transition hover:border-border-strong hover:bg-surface-elevated">
      <div className="flex items-baseline gap-2">
        <h3 className="text-base font-semibold text-content-primary">
          {section.title}
        </h3>
        <StatusPill status={section.status} />
      </div>
      <p className="text-sm text-content-secondary">{section.blurb}</p>
    </div>
  );
  if (section.status === "soon" || !section.href) {
    return <div className="opacity-60">{inner}</div>;
  }
  return (
    <Link href={section.href} className="block">
      {inner}
    </Link>
  );
}

function StatusPill({ status }: { status: StubSectionStatus }) {
  if (status === "live") {
    return (
      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700">
        Live
      </span>
    );
  }
  return (
    <span className="rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-content-muted">
      Soon
    </span>
  );
}
