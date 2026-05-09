// Glossary list page — server-rendered. Fetches all entries at
// request time and groups them by category.
//
// First real page in Diamond. Validates the FastAPI ↔ Next.js ↔
// type-gen pipeline. Per D15 maintenance contract: every label
// here is sourced from the dictionary (via `STATS[id]` on the
// backend, surfaced through the `/api/glossary` endpoint), never
// hand-coded.

import Link from "next/link";

import { getGlossary } from "@/lib/api";
import type { GlossaryEntry } from "@/lib/types/api";

export const metadata = {
  title: "Glossary — Diamond",
};

// Force dynamic rendering — Diamond is a local-first app where every
// data fetch hits the live FastAPI backend at request time. Skip
// Next.js's default static prerender (which would call the API at
// `next build` time, but uvicorn isn't running during builds).
export const dynamic = "force-dynamic";

function groupByCategory(
  entries: GlossaryEntry[],
  categories: string[],
): Record<string, GlossaryEntry[]> {
  const out: Record<string, GlossaryEntry[]> = {};
  for (const cat of categories) {
    out[cat] = [];
  }
  for (const e of entries) {
    if (!(e.category in out)) {
      // Defensive: the API should never return an entry whose
      // category isn't in CATEGORIES, but if it does we surface it
      // under an "other" bucket rather than dropping it silently.
      out[e.category] = [];
    }
    out[e.category].push(e);
  }
  return out;
}

export default async function GlossaryPage() {
  const data = await getGlossary();
  const grouped = groupByCategory(data.entries, data.categories);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] font-medium uppercase tracking-wider text-content-muted">
            Reference
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-content-primary">
            Stat glossary
            <span className="ml-2 text-sm font-normal text-content-secondary">
              · {data.count} stats / {data.categories.length} categories
            </span>
          </h1>
        </div>
        <p className="text-xs text-content-muted">
          D15 dictionary at <code className="font-mono">diamond.dictionary.STATS</code> · click for formula
        </p>
      </header>

      {data.categories.map((cat) => {
        const entries = grouped[cat] ?? [];
        if (entries.length === 0) return null;
        return (
          <section key={cat}>
            <h2 className="mb-3 text-lg font-semibold capitalize text-content-primary">
              {cat}{" "}
              <span className="text-sm font-normal text-content-muted">
                ({entries.length})
              </span>
            </h2>
            <ul className="divide-y divide-border rounded-md border border-border bg-surface-card">
              {entries.map((e) => (
                <li key={e.id}>
                  <Link
                    href={`/glossary/${encodeURIComponent(e.id)}`}
                    className="flex items-baseline gap-3 px-4 py-2 hover:bg-surface-elevated"
                  >
                    <span className="w-24 shrink-0 font-mono text-sm font-semibold text-content-primary">
                      {e.short_label}
                    </span>
                    <span className="w-56 shrink-0 text-sm text-content-secondary">
                      {e.display_name}
                    </span>
                    <span className="truncate text-xs text-content-muted">
                      {e.description.split(".")[0]}.
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
