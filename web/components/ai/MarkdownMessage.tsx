"use client";

// MarkdownMessage — renders an assistant text block as proper GFM
// markdown (D35 Tier A). Replaces the old whitespace-pre-wrap raw
// dump that was showing tables as `| Stat | ... |` and bolds as
// `**asterisks**`.
//
// Styling is inline rather than via @tailwindcss/typography because
// the prose plugin pulls a lot of CSS we don't need and would have
// to be re-themed across our four themes anyway. Each markdown
// element gets its own theme-aware className. The result is denser
// + lighter than `prose-invert`, sized for the 520px panel.

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Components } from "react-markdown";

const COMPONENTS: Components = {
  // Headings — used sparingly. h1 is reserved for our chrome; the
  // model usually uses h2/h3 to split an answer into sections.
  h1: ({ children }) => (
    <h1 className="mt-4 mb-2 text-lg font-semibold text-content-primary">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-4 mb-2 text-base font-semibold text-content-primary">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-3 mb-1.5 text-sm font-semibold uppercase tracking-wide text-content-secondary">
      {children}
    </h3>
  ),

  // Paragraphs + inline emphasis
  p: ({ children }) => (
    <p className="my-2 leading-[1.65] text-content-primary">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-content-primary">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,

  // Lists
  ul: ({ children }) => (
    <ul className="my-2 ml-5 list-disc space-y-1 text-content-primary marker:text-content-muted">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 ml-5 list-decimal space-y-1 text-content-primary marker:text-content-muted">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-[1.55]">{children}</li>,

  // Blockquote
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-border-strong pl-3 text-content-secondary italic">
      {children}
    </blockquote>
  ),

  // Inline + block code
  code: ({ className, children, ...props }) => {
    // ReactMarkdown distinguishes by parent: inline if no code-block
    // language class. We treat anything without `language-` prefix
    // as inline.
    const isInline = !/language-/.test(className ?? "");
    if (isInline) {
      return (
        <code
          className="rounded border border-border bg-surface-elevated px-1 py-[1px] font-mono text-[0.85em] text-content-primary"
          {...props}
        >
          {children}
        </code>
      );
    }
    // Block code — wrap in <pre> via the `pre` component below; this
    // just passes through. The lang is still on className for future
    // syntax-highlighting extension.
    return (
      <code
        className={`font-mono text-[12px] text-content-primary ${className ?? ""}`}
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded border border-border bg-surface-elevated px-3 py-2 text-[12px] leading-[1.5]">
      {children}
    </pre>
  ),

  // Tables — the headline reason for adding GFM. Striped rows, sticky
  // header style, compact cells.
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded border border-border">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-surface-elevated text-content-secondary">
      {children}
    </thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-border/60 last:border-b-0 even:bg-surface-card/30">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="px-2 py-1.5 text-left font-medium uppercase tracking-wide text-[10px]">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-2 py-1.5 align-top text-content-primary">{children}</td>
  ),

  // Links — open in new tab (we're embedded in the desktop shell;
  // the launcher's ExternalLinkPage routes target=_blank to the
  // system browser).
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-link underline-offset-2 hover:underline hover:text-link-hover"
    >
      {children}
    </a>
  ),

  // Horizontal rule
  hr: () => <hr className="my-3 border-t border-border" />,
};

export function MarkdownMessage({ text }: { text: string }) {
  return (
    <div className="text-[15px] text-content-primary [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={COMPONENTS}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
