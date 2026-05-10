// Root layout — every page renders inside this shell.
//
// 2026-05-13: refactored for an LSEG-Workspace-style information-dense
// terminal feel (per docs/ui_examples reference shots). Concrete shifts
// from the previous max-w-6xl center-column design:
//
//   - **Full-width content**: `<main>` fills the viewport with a small
//     responsive horizontal pad (px-3 sm:px-4 lg:px-6). On a 1920+
//     monitor this is ~700 extra pixels of usable real estate per page.
//   - **Compact two-band header**: tight 36px brand+nav row + a
//     secondary controls row. Total chrome height ~56px (down from
//     ~72px) and visually denser.
//   - **Sharp corners + thin borders**: the LSEG aesthetic is
//     utilitarian. Components keep their existing rounded-md tokens
//     for v1; future polish pass tightens this further.
//
// The inline script in <head> still reads `localStorage["diamond.theme"]`
// and stamps `data-theme` on <html> before body paints — flash-free
// theme on reload.

import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";

import { AISidebar } from "@/components/AISidebar";
import { PagePayloadProvider } from "@/components/PagePayloadProvider";
import { QuitButton } from "@/components/QuitButton";
import { RefreshButton } from "@/components/RefreshButton";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

export const metadata: Metadata = {
  title: "Diamond",
  description:
    "OOTP 27 monthly-dump warehouse + analytics. Bloomberg-terminal-meets-Fangraphs for franchise mode.",
};

// No-flash theme init. Synchronous; runs before body paint.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var t = localStorage.getItem('diamond.theme');
    if (t !== 'light' && t !== 'neutral' && t !== 'cb' && t !== 'dark') t = 'dark';
    document.documentElement.setAttribute('data-theme', t);
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full" data-theme="dark">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="h-full bg-surface-page text-content-primary text-sm antialiased">
        <PagePayloadProvider>
        <header className="sticky top-0 z-30 border-b border-border bg-surface-card/95 backdrop-blur-sm">
          {/* Compact single-row chrome — full bleed with small horizontal pad. */}
          <div className="flex items-center gap-4 px-3 py-2 sm:px-4 lg:px-6">
            <Link
              href="/"
              className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-content-primary"
            >
              <span aria-hidden="true">💎</span>
              <span>Diamond</span>
            </Link>
            <span className="h-4 w-px bg-border" aria-hidden="true" />
            <nav className="flex flex-1 items-center gap-1 text-xs uppercase tracking-wide text-content-secondary">
              <NavLink href="/" label="Club" />
              <NavLink href="/league" label="League" />
              <NavLink href="/world" label="World" />
              <NavLink href="/history" label="History" />
              <NavLink href="/explore" label="Explore" />
              <span className="ml-auto" />
              <NavLink href="/glossary" label="Glossary" />
              <NavLink href="/settings" label="Settings" />
            </nav>
            <div className="flex items-center gap-1.5">
              <RefreshButton />
              <ThemeSwitcher />
              <QuitButton />
            </div>
          </div>
        </header>
        <main className="px-3 py-4 sm:px-4 lg:px-6">{children}</main>
        {/* D33: AI sidebar — floating launcher button + slide-out panel.
            Reachable from every page; sends current pathname + the
            page's published payload (via PagePayloadProvider) so the
            model knows what the user is looking at. */}
        <AISidebar />
        </PagePayloadProvider>
      </body>
    </html>
  );
}

function NavLink({ href, label }: { href: string; label: string }) {
  // Compact LSEG-style nav button: tight padding, hover surface fill,
  // low text weight. The inline divider above separates the brand
  // from the nav cluster.
  return (
    <Link
      href={href}
      className="rounded px-2 py-1 transition-colors hover:bg-surface-elevated hover:text-content-primary"
    >
      {label}
    </Link>
  );
}
