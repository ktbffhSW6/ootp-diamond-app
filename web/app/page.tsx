// Home page — placeholder until the cockpit lands. Per UI_DESIGN.md
// build order, the cockpit is item 8; we need most other pages to
// exist before its anomaly-flag widgets have something to point at.

import Link from "next/link";

export default function HomePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">Diamond</h1>
      <p className="max-w-2xl text-slate-600">
        OOTP 27 monthly-dump warehouse + analytics. The full app surfaces
        here as Phase 3 lands — for now, the only live page is the
        stat-dictionary glossary, which validates the FastAPI ↔ Next.js
        pipeline end-to-end.
      </p>
      <div className="flex flex-col gap-2">
        <Link
          href="/glossary"
          className="text-blue-600 underline-offset-2 hover:underline"
        >
          → Glossary
        </Link>
      </div>
      <p className="text-xs text-slate-400">
        Phase 3 build order:{" "}
        <span className="font-mono">
          glossary ✓ · player · demotion/promotion · leaderboards · universes
          · AI overlay · cockpit · reviews · setup wizard
        </span>
      </p>
    </div>
  );
}
