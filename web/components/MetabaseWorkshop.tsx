// MetabaseWorkshop — embedded Metabase iframe.
//
// The user's Metabase instance runs at http://localhost:3000 (Pattern A
// — single Database #1 follows the active Diamond save). We iframe it
// directly. The user's existing Metabase login cookie carries through,
// so they don't auth twice.
//
// Liveness probe: client-side fetch to /api/health on mount. If
// Metabase isn't running, we render a cold-start guide instead of the
// iframe (avoids the broken-iframe state where the embed shows a
// "can't connect" browser page).
//
// Why client component: the iframe URL is fixed but we want a runtime
// check on Metabase liveness, and we want graceful "not running" UX
// without round-tripping through FastAPI.

"use client";

import { useEffect, useState } from "react";

// Port 3001 to avoid colliding with Diamond's Next.js dev server (3000)
// and FastAPI (8000). Override via NEXT_PUBLIC_METABASE_URL in
// `web/.env.local` if you've moved Metabase elsewhere.
const METABASE_URL =
  process.env.NEXT_PUBLIC_METABASE_URL ?? "http://localhost:3001";

type LivenessState = "checking" | "up" | "down";

export function MetabaseWorkshop() {
  const [state, setState] = useState<LivenessState>("checking");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const r = await fetch(`${METABASE_URL}/api/health`, {
          // No-cors mode: we can't read the response body but a successful
          // fetch (any status) means Metabase responded. If Metabase is
          // down, the fetch rejects with a TypeError.
          mode: "no-cors",
          cache: "no-store",
        });
        if (!cancelled) setState("up");
      } catch {
        if (!cancelled) setState("down");
      }
    };
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "checking") {
    return (
      <div className="rounded-md border border-border bg-surface-card p-6 text-sm text-content-muted">
        Probing Metabase at {METABASE_URL}...
      </div>
    );
  }

  if (state === "down") {
    return <ColdStartGuide />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-content-muted">
        <span>
          Embedded Metabase ·{" "}
          <a
            href={METABASE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:text-link-hover hover:underline"
          >
            Open full-screen ↗
          </a>
        </span>
        <span className="font-mono text-[10px]">
          localhost:3000 · same DuckDB as Diamond · save-aware
        </span>
      </div>
      {/* Tall iframe — Metabase's UI is dense and benefits from height.
          85vh leaves a sliver of Diamond chrome visible at the top so
          you don't lose context. */}
      <iframe
        src={`${METABASE_URL}/`}
        title="Metabase"
        className="w-full rounded-md border border-border bg-surface-card"
        style={{ height: "85vh" }}
        // Allow forms (login), scripts (Metabase's React app), same-origin
        // for cookie-based auth. No top-navigation so the iframe can't
        // navigate the parent window away.
        sandbox="allow-forms allow-scripts allow-same-origin allow-popups allow-downloads"
      />
    </div>
  );
}

function ColdStartGuide() {
  return (
    <div className="space-y-3 rounded-md border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
      <h2 className="text-base font-semibold">Metabase isn&apos;t running</h2>
      <p>
        The Workshop tab embeds Metabase at{" "}
        <code className="rounded bg-amber-100 px-1 font-mono dark:bg-amber-900/60">
          http://localhost:3000
        </code>
        . Start it once and it stays up across Diamond reloads.
      </p>
      <ol className="ml-4 list-decimal space-y-1.5">
        <li>
          Open a terminal, run:
          <pre className="mt-1 rounded bg-amber-100 px-2 py-1.5 font-mono text-xs dark:bg-amber-900/60">
            ~/.diamond/metabase/metabase.bat /b
          </pre>
        </li>
        <li>
          Wait ~30 seconds for Metabase to boot (first start takes longest)
        </li>
        <li>Reload this tab</li>
      </ol>
      <p className="border-t border-amber-300 pt-2 text-xs dark:border-amber-700">
        First-time setup? See <code>docs/METABASE.md</code> for install +
        config (one-time, ~10 min).
      </p>
    </div>
  );
}
