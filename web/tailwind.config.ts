import type { Config } from "tailwindcss";

// Tailwind config. Themes are driven via CSS variables in
// `app/globals.css` (one `:root` block per theme, switched via
// `data-theme` on `<html>`). The `colors.surface` / `colors.content`
// / `colors.border` tokens below let components write semantic
// classes (`bg-surface-page`, `text-content-primary`,
// `border-border-default`) that automatically follow whatever
// theme is active.
//
// Verdict-tinted accents (emerald / rose / amber / etc.) still use
// the named Tailwind palette — full theming for those is queued for
// the color-blind-mode follow-up.

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  // Class strategy on data-theme means we can still write `dark:`
  // utilities if it ever helps for one-off tweaks, but the primary
  // mechanism is the CSS variable extension below.
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        surface: {
          page: "rgb(var(--surface-page) / <alpha-value>)",
          card: "rgb(var(--surface-card) / <alpha-value>)",
          elevated: "rgb(var(--surface-elevated) / <alpha-value>)",
        },
        content: {
          primary: "rgb(var(--content-primary) / <alpha-value>)",
          secondary: "rgb(var(--content-secondary) / <alpha-value>)",
          muted: "rgb(var(--content-muted) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--border-default) / <alpha-value>)",
          strong: "rgb(var(--border-strong) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
        },
        link: {
          DEFAULT: "rgb(var(--link) / <alpha-value>)",
          hover: "rgb(var(--link-hover) / <alpha-value>)",
        },
      },
    },
  },
  plugins: [],
};

export default config;
