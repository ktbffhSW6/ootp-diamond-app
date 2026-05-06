// Theme switcher — cycles through the four themes defined in
// `globals.css` (light / dark / neutral / cb), persists the choice to
// localStorage, and applies it via the `data-theme` attribute on
// <html>. Tokens in the Tailwind config (`bg-surface-page`,
// `text-content-primary`, etc.) follow the attribute automatically.
//
// The no-flash init script lives in the root layout's <head> — that
// reads localStorage before paint so the page never renders in the
// wrong theme on first load. This component handles user-initiated
// changes after mount.

"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark" | "neutral" | "cb";

const THEMES: { id: Theme; label: string; sub: string }[] = [
  { id: "light", label: "Light", sub: "Default" },
  { id: "neutral", label: "Neutral", sub: "Warm cream — softer than pure white" },
  { id: "dark", label: "Dark", sub: "Slate-based dark mode" },
  { id: "cb", label: "Color-blind", sub: "Wong (2011) safe palette — chrome only in v1" },
];

const STORAGE_KEY = "diamond.theme";

function readTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const fromAttr = document.documentElement.getAttribute("data-theme");
  if (fromAttr === "dark" || fromAttr === "neutral" || fromAttr === "cb") {
    return fromAttr;
  }
  return "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Private browsing or quota — non-fatal.
  }
}

export function ThemeSwitcher() {
  // Initialize from the attribute the no-flash script set, then
  // re-sync after mount in case the script hadn't run yet (it should
  // have, but defensive).
  const [theme, setTheme] = useState<Theme>("light");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setTheme(readTheme());
  }, []);

  // Close the dropdown when clicking outside.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest("[data-theme-switcher]")) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  function pick(t: Theme) {
    applyTheme(t);
    setTheme(t);
    setOpen(false);
  }

  const current = THEMES.find((t) => t.id === theme) ?? THEMES[0];

  return (
    <div className="relative" data-theme-switcher>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded border border-border px-2 py-1 text-xs font-medium text-content-secondary hover:bg-surface-elevated"
        title="Switch theme"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {current.label}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 w-64 rounded-md border border-border bg-surface-card p-1 shadow-lg"
        >
          {THEMES.map((t) => {
            const active = t.id === theme;
            return (
              <button
                key={t.id}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                onClick={() => pick(t.id)}
                className={
                  "flex w-full flex-col items-start rounded px-2 py-1.5 text-left text-sm hover:bg-surface-elevated " +
                  (active ? "bg-surface-elevated" : "")
                }
              >
                <span className="text-content-primary">
                  {t.label}
                  {active && (
                    <span className="ml-2 text-xs text-content-muted">
                      (active)
                    </span>
                  )}
                </span>
                <span className="text-xs text-content-muted">{t.sub}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
