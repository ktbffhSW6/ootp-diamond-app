// Active-save picker (D3 v2 / setup wizard).
//
// URL: /settings/save
//
// Server fetches the saves list; client form lets the user pick a
// new active save. Saves without a warehouse render with an
// "ingest first" hint — the user can still pick them, but the app
// will fail to read until they run `diamond ingest` in their terminal.

import { SaveSwitcher } from "@/components/SaveSwitcher";
import { getSaves } from "@/lib/api";

export const metadata = { title: "Save — Diamond" };
export const dynamic = "force-dynamic";

export default async function SaveSettingsPage() {
  const data = await getSaves();
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          Active save
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          Diamond opens one warehouse at a time, picked from the saves
          under your OOTP saved_games folder. Switching here persists
          to <code className="rounded bg-surface-elevated px-1 py-0.5 font-mono text-xs">~/.diamond/active_save.toml</code>{" "}
          so the next launch resumes against the same save.
        </p>
        <p className="mt-2 text-xs text-content-muted">
          Looking in: <code className="font-mono">{data.saves_root}</code>
        </p>
      </header>
      <SaveSwitcher initial={data} />
    </main>
  );
}
