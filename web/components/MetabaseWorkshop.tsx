// MetabaseWorkshop — launcher card for Metabase (separate window).
//
// **Why launcher, not iframe**: Metabase OSS sends `X-Frame-Options:
// DENY` and `frame-ancestors 'none'`. Allowing iframe embedding from a
// different origin requires Metabase Pro's "interactive embedding"
// feature (paid). Diamond's local-first model is incompatible with
// upgrading to Pro for a single-user OOTP tool.
//
// The pragmatic path is the same shape as every other BI-sidecar
// integration (Power BI Desktop, Tableau Desktop alongside any web
// app): Metabase opens full-screen in its own window. Diamond stays
// the curated UI, Metabase is the analyst console — same warehouse,
// two surfaces.
//
// This component:
//   - Probes Metabase liveness via Diamond's FastAPI (same-origin,
//     no CORS dance).
//   - On up: shows the launcher (links to Metabase home, sample
//     spike-built dashboard, recent questions).
//   - On down: shows the cold-start guide (run metabase.bat /b).

"use client";

import { useEffect, useState } from "react";

// Port 3001 to avoid colliding with Diamond's Next.js dev server (3000)
// and FastAPI (8000). Override via NEXT_PUBLIC_METABASE_URL in
// `web/.env.local` if you've moved Metabase elsewhere.
const METABASE_URL =
  process.env.NEXT_PUBLIC_METABASE_URL ?? "http://localhost:3001";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type LivenessState = "checking" | "up" | "down";

interface MetabaseStatus {
  running: boolean;
  configured: boolean;
  active_save_db?: string | null;
  message?: string | null;
}

export function MetabaseWorkshop() {
  const [state, setState] = useState<LivenessState>("checking");
  const [status, setStatus] = useState<MetabaseStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const check = async () => {
      try {
        // Probe via Diamond's FastAPI — same-origin, reliable. The
        // FastAPI hits Metabase server-side and returns the result.
        // Falls back to direct probe (no-cors, may be unreliable on
        // localhost across ports) if Diamond's endpoint isn't there
        // yet.
        const r = await fetch(`${API_URL}/api/admin/metabase-status`, {
          cache: "no-store",
        });
        if (cancelled) return;
        if (r.ok) {
          const data: MetabaseStatus = await r.json();
          setStatus(data);
          setState(data.running ? "up" : "down");
          schedule(data.running ? null : 5000);
          return;
        }
      } catch {
        // Diamond's API is also down — fall through to direct probe.
      }
      // Last-resort direct probe.
      try {
        await fetch(`${METABASE_URL}/api/health`, {
          mode: "no-cors",
          cache: "no-store",
        });
        if (!cancelled) {
          setState("up");
          schedule(null);
        }
      } catch {
        if (!cancelled) {
          setState("down");
          schedule(5000);
        }
      }
    };

    // Poll every 5s while Metabase is down (D32 ext: launcher now
    // boots Metabase as a sidecar; the user sees the cold-start
    // morph to "ready" without manually reloading). Stop once up.
    const schedule = (delay: number | null) => {
      if (cancelled || delay === null) return;
      timer = setTimeout(check, delay);
    };

    check();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (state === "checking") {
    return (
      <div className="rounded-md border border-border bg-surface-card p-6 text-sm text-content-muted">
        Checking Metabase status…
      </div>
    );
  }

  if (state === "down") {
    return <ColdStartGuide />;
  }

  return <Launcher status={status} />;
}

function Launcher({ status }: { status: MetabaseStatus | null }) {
  return (
    <div className="space-y-4">
      {/* Headline launcher */}
      <a
        href={METABASE_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="block rounded-lg border border-border bg-surface-card p-6 transition hover:border-accent hover:bg-surface-elevated"
      >
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              Open Metabase Workshop ↗
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              Full BI surface — drag-and-drop chart builder, every chart
              type, dashboards, save + share. Opens in a new tab.
            </p>
          </div>
          <div className="text-right text-xs text-content-muted">
            <div className="font-mono">localhost:3001</div>
            <div>same DuckDB · save-aware</div>
          </div>
        </div>
      </a>

      {/* Quick links to specific places in Metabase */}
      <div className="grid gap-2 sm:grid-cols-3">
        <DeepLink
          href={`${METABASE_URL}/question/new`}
          title="New question"
          hint="Empty editor → drag fields"
        />
        <DeepLink
          href={`${METABASE_URL}/dashboard/1`}
          title="Sample dashboard"
          hint="2029 MLB Production · 5 cards"
        />
        <DeepLink
          href={`${METABASE_URL}/browse/databases/1`}
          title="Browse warehouse"
          hint="All ~220 tables · drill in"
        />
      </div>

      {/* Architecture footnote */}
      <div className="rounded-md border border-border bg-surface-elevated p-3 text-xs text-content-muted">
        <p>
          <strong className="text-content-secondary">
            Why a separate window, not iframe:
          </strong>{" "}
          Metabase OSS blocks iframe embedding from other origins
          (interactive embedding is a paid Pro feature). The launcher
          pattern is functionally equivalent — same warehouse via
          Pattern A, same save-switch wiring, just a separate browser
          tab. Mirrors how Tableau Desktop / Power BI Desktop integrate
          with web apps.
        </p>
        {status?.active_save_db && (
          <p className="mt-2 font-mono text-[10px] text-content-muted">
            Active save DB: {status.active_save_db}
          </p>
        )}
      </div>
    </div>
  );
}

function DeepLink({
  href,
  title,
  hint,
}: {
  href: string;
  title: string;
  hint: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-md border border-border bg-surface-card p-3 transition hover:border-border-strong hover:bg-surface-elevated"
    >
      <div className="text-sm font-medium text-link">{title} ↗</div>
      <div className="mt-0.5 text-xs text-content-muted">{hint}</div>
    </a>
  );
}

function ColdStartGuide() {
  return (
    <div className="space-y-3 rounded-md border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
      <h2 className="text-base font-semibold">Metabase isn&apos;t running</h2>
      <p>
        The Workshop launches Metabase at{" "}
        <code className="rounded bg-amber-100 px-1 font-mono dark:bg-amber-900/60">
          {METABASE_URL}
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
