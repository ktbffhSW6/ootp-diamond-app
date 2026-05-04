// AUTO-GENERATED FROM PYDANTIC SCHEMAS — DO NOT EDIT BY HAND.
//
// This file is the target of `make types` (or `pnpm types`), which
// runs `pydantic-to-typescript` against `src/diamond/api/schemas/`
// and writes the result here. Pydantic models are the single source
// of truth per D16; this TypeScript mirror exists so the frontend
// gets autocomplete and type-checking for API payloads.
//
// CURRENT STATE (2026-05-07): hand-written mirror for the v1
// scaffolding session. The first `make types` run will overwrite
// this file with auto-generated content of the same shape. The
// hand-written version is here so the frontend can compile before
// Node is installed.
//
// To regenerate manually:
//   pip install pydantic-to-typescript
//   pnpm install        # in web/, gets json2ts
//   make types          # at repo root

export interface GlossaryEntry {
  id: string;
  display_name: string;
  short_label: string;
  category: string;
  formula_tex: string;
  formula_plain: string;
  description: string;
  units: string;
  typical_range: string;
  interpretation: string;
  caveats: string | null;
  source: string;
  formula_source: string;
  related: string[];
  refs: Record<string, string>;
}

export interface GlossaryListResponse {
  entries: GlossaryEntry[];
  categories: string[];
  count: number;
}

export interface HealthResponse {
  status: string;
  api_version: string;
}
