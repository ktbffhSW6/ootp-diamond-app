# Diamond — frontend

Next.js (App Router) consumer of the Diamond FastAPI backend. See
[`docs/DEV.md`](../docs/DEV.md) at the repo root for the full setup
and dev workflow.

## Quick start

```bash
# From repo root, install Python deps:
.venv/Scripts/pip install -e ".[dev]"

# Install Node deps:
cd web
pnpm install

# Start the backend (separate terminal, from repo root):
make api

# Start this dev server:
pnpm dev
# → http://localhost:3000
```

## Layout

- `app/` — file-system routes (App Router). `page.tsx` for the home
  placeholder, `glossary/page.tsx` for the list, `glossary/[id]/page.tsx`
  for single-entry detail.
- `components/` — shared React components (`FormulaBlock` wraps KaTeX).
- `lib/api.ts` — typed fetch helpers.
- `lib/types/api.ts` — **auto-generated** from Pydantic schemas. Do
  not hand-edit. Regenerate via `make types` from repo root.

## Conventions

- Server components by default. Drop to `"use client"` only when a
  component needs hooks / browser APIs (e.g., the KaTeX renderer).
- Every visible label / formula / column header sources from the D15
  stat dictionary via the `/api/glossary` endpoint. Never hand-code
  stat names.
- Tailwind-only for styling. Custom CSS lives in `app/globals.css`
  for cross-cutting concerns (KaTeX font import).
