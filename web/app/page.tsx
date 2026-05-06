// Landing page — the front door to the app.
//
// Identifies the active save (org + season + warehouse health) and
// surfaces the tools that exist as a structured list. Replaces the
// previous three-link placeholder. Per the user's pulse-check on
// 2026-05-08: build the screens where these tools live before piling
// on more standalone routes.
//
// Future surfaces (UI_DESIGN.md §1 Front-Office Cockpit):
// - Roster grid → enables player-page navigation without typing IDs
// - Decisions queue → top regret signals + promotion candidates
// - Anomaly flags → AI-tier "what changed since last sync"
// - Standings + Pythag
//
// Each of those plugs into the layout below as a new section once
// its data source lands. The grouping into "Tools" and "What's next"
// is meant to tolerate that growth without re-architecting.

import Link from "next/link";

import { getSave } from "@/lib/api";

export const metadata = {
  title: "Diamond",
};

// Force dynamic rendering — Diamond is local-first and every fetch
// hits the live FastAPI backend at request time. Without this, Next's
// build-time prerender calls the API while uvicorn isn't running and
// the build fails with ECONNREFUSED.
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (iso === null) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtCount(n: number): string {
  return n.toLocaleString("en-US");
}

// ─────────────────────────────────────────────────────────────────────
// Tool catalog — single source of truth for the landing's nav list.
// Each entry is a card; status drives whether it links and how it's
// described. Tools land here as routes ship; "soon" entries describe
// what they'll do without a target href.
// ─────────────────────────────────────────────────────────────────────

type ToolStatus = "live" | "soon";
type Tool = {
  status: ToolStatus;
  title: string;
  href: string | null;
  blurb: string;
};

const TOOLS: Tool[] = [
  {
    status: "live",
    title: "Movement ledger",
    href: "/movements",
    blurb:
      "Promotions, demotions, acquisitions, and departures with verdict glyphs that flag the moves that worked and the ones to reconsider. Outgoing moves invert the verdict — a player thriving elsewhere reads as 🔴.",
  },
  {
    status: "live",
    title: "Glossary",
    href: "/glossary",
    blurb:
      "60 stats with formulas (KaTeX-rendered), categories, and interpretation. The shared vocabulary every column header, chart axis, and AI prompt reads from.",
  },
  {
    status: "live",
    title: "Roster",
    href: "/roster",
    blurb:
      "Every active player in the org tree, grouped by current level (MLB / AAA / AA / A+ / A / Rk / DSL). Filter by level, role, or hand; toggle between basic and advanced stats; click any name for the full player page.",
  },
  {
    status: "live",
    title: "Player page",
    // Now reachable via the roster — kept here as a direct link so the
    // demo path still works (and so the cockpit cards aren't 1×N).
    href: "/player/26166",
    blurb:
      "Bref-shaped player card with a Stats tab (batting / pitching / fielding / advanced sections, multi-stint disclosure rows). Demo path: Gunnar Henderson.",
  },
  {
    status: "soon",
    title: "Pressure board",
    href: null,
    blurb:
      "Who *should* move — companion to the movement ledger. For each level, players mashing relative to the level median vs. players struggling at the next level up. Decisions-queue input.",
  },
  {
    status: "soon",
    title: "Charts tab",
    href: null,
    blurb:
      "On the player page — radial career arc plus the Savant-style EV/LA scatter and trajectory lines, powered by Vega-Lite.",
  },
];

// ─────────────────────────────────────────────────────────────────────
// Subcomponents
// ─────────────────────────────────────────────────────────────────────

function StatusPill({ status }: { status: ToolStatus }) {
  if (status === "live") {
    return (
      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
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

function ToolCard({ tool }: { tool: Tool }) {
  const inner = (
    <div className="flex h-full flex-col gap-2 rounded-md border border-border bg-surface-card p-4 transition hover:border-border-strong hover:bg-surface-elevated">
      <div className="flex items-baseline gap-2">
        <h3 className="text-base font-semibold text-content-primary">{tool.title}</h3>
        <StatusPill status={tool.status} />
      </div>
      <p className="text-sm text-content-secondary">{tool.blurb}</p>
    </div>
  );
  if (tool.status === "soon" || tool.href === null) {
    // Render as a non-interactive card with reduced opacity so the
    // visual weight matches its disabled state.
    return <div className="opacity-60">{inner}</div>;
  }
  return (
    <Link href={tool.href} className="block">
      {inner}
    </Link>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default async function HomePage() {
  const save = await getSave();
  const orgLabel = save.org_team_nickname
    ? `${save.org_team_abbr ?? ""} ${save.org_team_nickname}`.trim()
    : (save.org_team_abbr ?? `Team ${save.org_team_id}`);

  return (
    <div className="space-y-10">
      {/* ── Header — save identity ───────────────────────────────── */}
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          Front office
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {orgLabel}
          {save.latest_season !== null && (
            <span className="ml-3 text-2xl font-medium text-content-secondary">
              · {save.latest_season} season
            </span>
          )}
        </h1>
        <p className="font-mono text-sm text-content-muted">{save.save_name}</p>
      </header>

      {/* ── Warehouse status row ─────────────────────────────────── */}
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Dumps tracked"
          value={fmtCount(save.dump_count)}
          sub={
            save.latest_dump_name
              ? `Latest: ${save.latest_dump_name.replace("dump_", "")}`
              : "—"
          }
        />
        <Stat
          label="Last sync"
          value={fmtDate(save.latest_dump_date)}
          sub={save.latest_dump_date ? "Most recent dump" : "No ingests yet"}
        />
        <Stat
          label="Players in scope"
          value={fmtCount(save.scoped_player_count)}
          sub={`Across ${fmtCount(save.scoped_team_count)} teams`}
        />
        <Stat
          label="Seasons covered"
          value={
            save.earliest_season !== null && save.latest_season !== null
              ? `${save.earliest_season}–${save.latest_season}`
              : "—"
          }
          sub="Pre-save history + in-save"
        />
      </section>

      {/* ── Tools section ────────────────────────────────────────── */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-content-primary">Tools</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {TOOLS.map((tool) => (
            <ToolCard key={tool.title} tool={tool} />
          ))}
        </div>
      </section>

      {/* ── Footer note ──────────────────────────────────────────── */}
      <p className="border-t border-border pt-4 text-xs text-content-muted">
        Diamond is a local-first single-user app per Decision D16. Phase 3
        UI build is in progress — expect this landing to grow into a
        front-office cockpit (UI_DESIGN.md §1) as the cockpit&apos;s data
        sources land.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="space-y-1 rounded-md border border-border bg-surface-card p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        {label}
      </p>
      <p className="text-xl font-semibold tabular-nums text-content-primary">
        {value}
      </p>
      <p className="text-xs text-content-muted">{sub}</p>
    </div>
  );
}
