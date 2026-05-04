// FormulaBlock — renders a KaTeX block-level formula.
//
// Per D15 the dictionary's formula_tex field is KaTeX-renderable
// LaTeX. `react-katex`'s `BlockMath` is the canonical wrapper; we
// thin-wrap it here so future style tweaks land in one place.
//
// Falls back gracefully if KaTeX fails to parse (e.g., malformed
// formula slipped past the smoke test): displays the raw string
// monospaced rather than crashing the page.

"use client";

import { BlockMath } from "react-katex";

interface FormulaBlockProps {
  tex: string;
  className?: string;
}

export function FormulaBlock({ tex, className }: FormulaBlockProps) {
  if (!tex) return null;
  try {
    return (
      <div
        className={
          className ??
          "rounded-md border border-slate-200 bg-slate-50 px-4 py-3"
        }
      >
        <BlockMath math={tex} />
      </div>
    );
  } catch {
    return (
      <pre className="overflow-x-auto rounded-md border border-red-200 bg-red-50 px-4 py-3 font-mono text-xs text-red-800">
        {tex}
      </pre>
    );
  }
}
