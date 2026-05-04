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
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Stat glossary</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">
          {data.count} stats across {data.categories.length} categories.
          Single source of truth at{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">
            diamond.dictionary.STATS
          </code>{" "}
          (Decision D15). Click any stat for full formula + interpretation.
        </p>
      </div>

      {data.categories.map((cat) => {
        const entries = grouped[cat] ?? [];
        if (entries.length === 0) return null;
        return (
          <section key={cat}>
            <h2 className="mb-3 text-lg font-semibold capitalize text-slate-900">
              {cat}{" "}
              <span className="text-sm font-normal text-slate-400">
                ({entries.length})
              </span>
            </h2>
            <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {entries.map((e) => (
                <li key={e.id}>
                  <Link
                    href={`/glossary/${encodeURIComponent(e.id)}`}
                    className="flex items-baseline gap-3 px-4 py-2 hover:bg-slate-50"
                  >
                    <span className="w-24 shrink-0 font-mono text-sm font-semibold text-slate-900">
                      {e.short_label}
                    </span>
                    <span className="w-56 shrink-0 text-sm text-slate-700">
                      {e.display_name}
                    </span>
                    <span className="truncate text-xs text-slate-500">
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
