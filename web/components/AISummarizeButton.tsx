"use client";

// Per-page "Summarize" trigger.
//
// Renders a small button that, on click, POSTs to /api/ai/summarize
// with the current target. Shows a loading shimmer during the call
// and the generated text + provider/model footer when done.
//
// Errors surface inline. The most common — "no key set" — links the
// user to /settings/ai inline.

import Link from "next/link";
import { useState } from "react";

import { aiSummarize } from "@/lib/api";
import type { AISummarizeRequest, AISummarizeResponse } from "@/lib/types/api";

interface Props {
  kind: AISummarizeRequest["kind"];
  targetId: number;
  label?: string;
}

export function AISummarizeButton({ kind, targetId, label }: Props) {
  const [state, setState] = useState<
    | { phase: "idle" }
    | { phase: "loading" }
    | { phase: "ok"; data: AISummarizeResponse }
    | { phase: "err"; message: string }
  >({ phase: "idle" });

  async function run() {
    setState({ phase: "loading" });
    try {
      const data = await aiSummarize({ kind, target_id: targetId });
      setState({ phase: "ok", data });
    } catch (e) {
      setState({
        phase: "err",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-card p-4">
      <div className="flex items-center gap-3">
        <button
          onClick={run}
          disabled={state.phase === "loading"}
          className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {state.phase === "loading"
            ? "Generating…"
            : `✨ ${label ?? "Summarize"}`}
        </button>
        <Link
          href="/settings/ai"
          className="text-xs text-link hover:text-link-hover"
        >
          AI settings →
        </Link>
        {state.phase === "ok" && (
          <span className="ml-auto text-xs text-content-muted">
            {state.data.provider}/{state.data.model}
          </span>
        )}
      </div>

      {state.phase === "ok" && (
        <div className="prose prose-sm max-w-none whitespace-pre-wrap text-content-primary dark:prose-invert">
          {state.data.text}
        </div>
      )}
      {state.phase === "err" && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {state.message.includes("No ") && state.message.includes("API key") ? (
            <>
              {state.message}{" "}
              <Link
                href="/settings/ai"
                className="font-semibold underline hover:opacity-80"
              >
                Add a key
              </Link>
              .
            </>
          ) : (
            state.message
          )}
        </div>
      )}
    </div>
  );
}
