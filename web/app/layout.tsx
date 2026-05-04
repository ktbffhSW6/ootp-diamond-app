// Root layout — every page renders inside this shell.
//
// Per D16: minimal v1 chrome, page content owns the bulk of the
// real estate. Top nav surfaces as routes land (player, leaderboards,
// universes, etc.). For now, just a thin header pointing at the
// glossary stub.

import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Diamond",
  description:
    "OOTP 27 monthly-dump warehouse + analytics. Bloomberg-terminal-meets-Fangraphs for franchise mode.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-white text-slate-900 antialiased">
        <header className="border-b border-slate-200 bg-slate-50">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              💎 Diamond
            </Link>
            <nav className="flex gap-6 text-sm text-slate-600">
              <Link href="/glossary" className="hover:text-slate-900">
                Glossary
              </Link>
              {/* Routes land here as Phase 3 builds out: */}
              {/* /cockpit, /player, /leaderboards, /universes, ... */}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
