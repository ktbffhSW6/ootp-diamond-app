// Settings landing — links to per-feature settings pages.
//
// v1: AI (keyring + use-level) and Save (active save picker, set
// in slice 5). Theme + Quit live in the header, not here.

import Link from "next/link";

export const metadata = { title: "Settings — Diamond" };

const PANELS = [
  {
    title: "AI overlay",
    href: "/settings/ai",
    blurb:
      "Provider / model / use level + per-provider API keys (stored in OS keyring). v1 supports Anthropic + OpenAI.",
  },
  {
    title: "Active save",
    href: "/settings/save",
    blurb:
      "Switch between saves under your OOTP saved_games folder. Picker + warehouse status per save.",
  },
];

export default function SettingsLanding() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-bold text-content-primary">Settings</h1>
      <p className="mt-1 text-sm text-content-secondary">
        Per-feature configuration. Theme and Quit are in the header.
      </p>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {PANELS.map((p) => (
          <Link
            key={p.href}
            href={p.href}
            className="rounded-lg border border-border bg-surface-card p-4 hover:border-border-strong"
          >
            <div className="font-semibold text-content-primary">{p.title}</div>
            <div className="mt-1 text-xs text-content-muted">{p.blurb}</div>
          </Link>
        ))}
      </div>
    </main>
  );
}
