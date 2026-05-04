import type { Config } from "tailwindcss";

// Tailwind config — minimal v1. shadcn/ui's `init` will mutate this
// file when added (it adds the design-token color palette + plugin
// list). For now, plain Tailwind defaults are enough to build the
// glossary page.

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Bloomberg/Fangraphs ambition (per UI_DESIGN.md): dense data
      // tables with monospace numerics. Default font stack is fine
      // for prose; the `font-mono` utility on numeric cells keeps
      // columns aligned without per-cell spacing tweaks.
      fontFamily: {
        // Use system font stack as the default; override per-page if needed.
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
    },
  },
  plugins: [],
};

export default config;
