// Single-stat detail page. Renders the full Stat dataclass with
// KaTeX-rendered formula. Server-rendered; 404 propagates from the
// API to a Next.js notFound().

import Link from "next/link";
import { notFound } from "next/navigation";

import { FormulaBlock } from "@/components/FormulaBlock";
import { getGlossaryEntry } from "@/lib/api";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  return { title: `${id} — Glossary — Diamond` };
}

export default async function GlossaryDetailPage({ params }: Props) {
  const { id } = await params;
  const decoded = decodeURIComponent(id);

  let entry;
  try {
    entry = await getGlossaryEntry(decoded);
  } catch (err) {
    // The API returns 404 for unknown ids; the fetch helper throws.
    // Surface it as a Next.js notFound rather than re-throwing.
    if (err instanceof Error && err.message.includes("404")) {
      notFound();
    }
    throw err;
  }

  return (
    <article className="space-y-6">
      <nav className="text-sm text-slate-500">
        <Link href="/glossary" className="hover:text-slate-900">
          ← Glossary
        </Link>
      </nav>

      <header>
        <p className="text-sm uppercase tracking-wide text-slate-400">
          {entry.category}
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">
          {entry.display_name}{" "}
          <span className="ml-2 font-mono text-xl font-normal text-slate-500">
            ({entry.short_label})
          </span>
        </h1>
      </header>

      <p className="max-w-2xl text-slate-700">{entry.description}</p>

      {entry.formula_tex && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Formula
          </h2>
          <FormulaBlock tex={entry.formula_tex} />
          <p className="mt-2 font-mono text-xs text-slate-500">
            {entry.formula_plain}
          </p>
        </section>
      )}

      <dl className="grid max-w-2xl grid-cols-[max-content_1fr] gap-x-6 gap-y-3 text-sm">
        <dt className="font-semibold text-slate-500">Units</dt>
        <dd className="text-slate-800">{entry.units}</dd>

        <dt className="font-semibold text-slate-500">Typical range</dt>
        <dd className="text-slate-800">{entry.typical_range}</dd>

        <dt className="font-semibold text-slate-500">How to read</dt>
        <dd className="text-slate-800">{entry.interpretation}</dd>

        {entry.caveats && (
          <>
            <dt className="font-semibold text-slate-500">Caveats</dt>
            <dd className="text-slate-800">{entry.caveats}</dd>
          </>
        )}

        <dt className="font-semibold text-slate-500">Source</dt>
        <dd className="font-mono text-xs text-slate-700">{entry.source}</dd>

        <dt className="font-semibold text-slate-500">Formula source</dt>
        <dd className="text-slate-700">{entry.formula_source}</dd>
      </dl>

      {entry.related.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Related
          </h2>
          <ul className="flex flex-wrap gap-2">
            {entry.related.map((rid) => (
              <li key={rid}>
                <Link
                  href={`/glossary/${encodeURIComponent(rid)}`}
                  className="rounded-md bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-700 hover:bg-slate-200"
                >
                  {rid}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {Object.keys(entry.refs).length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            External glossaries
          </h2>
          <ul className="flex flex-wrap gap-3 text-sm">
            {Object.entries(entry.refs).map(([name, url]) => (
              <li key={name}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  {name} ↗
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
