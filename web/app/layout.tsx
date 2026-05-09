// Root layout — every page renders inside this shell.
//
// Per D16: minimal v1 chrome, page content owns the bulk of the real
// estate. Top nav reflects the IA committed in conversation: Club /
// League / World / History / Explore are the scope-and-purpose tabs;
// Glossary is the cross-cutting reference. ThemeSwitcher + Quit live
// in the corner.
//
// The inline script in <head> reads `localStorage["diamond.theme"]`
// and stamps the resulting `data-theme` onto <html> before the body
// paints — without it, every reload flashes the default light theme
// for ~50ms before the chosen theme takes over.

import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";

import { QuitButton } from "@/components/QuitButton";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

export const metadata: Metadata = {
  title: "Diamond",
  description:
    "OOTP 27 monthly-dump warehouse + analytics. Bloomberg-terminal-meets-Fangraphs for franchise mode.",
};

// No-flash theme init. Runs synchronously before the body renders;
// reads localStorage and sets the attribute, falling back to "dark"
// on first load or any read error. Dark is the default per the
// 2026-05-08 user preference — light/neutral/cb still selectable
// from the ThemeSwitcher.
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
      <body className="h-full bg-surface-page text-content-primary antialiased">
        <header className="border-b border-border bg-surface-card">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <Link
              href="/"
              className="text-lg font-semibold tracking-tight text-content-primary"
            >
              💎 Diamond
            </Link>
            <nav className="flex flex-1 items-center gap-5 text-sm text-content-secondary">
              <NavLink href="/" label="Club" />
              <NavLink href="/league" label="League" />
              <NavLink href="/world" label="World" />
              <NavLink href="/history" label="History" />
              <NavLink href="/explore" label="Explore" />
              <span className="ml-auto" />
              <NavLink href="/glossary" label="Glossary" />
              <NavLink href="/settings" label="⚙" />
            </nav>
            <div className="flex items-center gap-2">
              <ThemeSwitcher />
              <QuitButton />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}

function NavLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="hover:text-content-primary transition-colors"
    >
      {label}
    </Link>
  );
}
