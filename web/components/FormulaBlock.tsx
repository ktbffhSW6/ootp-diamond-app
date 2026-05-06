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
          // `text-content-primary` makes KaTeX inherit the theme's
          // foreground color — the .katex spans use `color: inherit`
          // for symbols and operators, so this single class is what
          // makes formulas legible across light / dark / neutral / cb.
          className ??
          "rounded-md border border-border bg-surface-elevated px-4 py-3 text-content-primary"
        }
      >
        <BlockMath math={tex} />
      </div>
    );
  } catch {
    return (
      <pre className="overflow-x-auto rounded-md border border-rose-500/30 bg-rose-500/10 px-4 py-3 font-mono text-xs text-rose-300">
        {tex}
      </pre>
    );
  }
}
