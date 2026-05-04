// AUTO-GENERATED FROM PYDANTIC SCHEMAS — DO NOT EDIT BY HAND.
// Source of truth: src/diamond/api/schemas/ (Pydantic v2 models)
// Regenerate via: make types  (or python scripts/generate_types.py)
// See docs/DECISIONS.md D16 for the type-gen pipeline contract.

/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * One stat dictionary entry, serialized for HTTP.
 *
 * Field-for-field mirror of :class:`diamond.dictionary.Stat`. See
 * ``src/diamond/dictionary/__init__.py`` for the canonical
 * descriptions of each field.
 */
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
  refs: {
    [k: string]: string;
  };
}
/**
 * ``GET /api/glossary`` envelope.
 *
 * Carries the full entry list plus the canonical category ordering
 * (so the frontend doesn't have to maintain a parallel CATEGORIES
 * constant). ``count`` is convenience for the client.
 */
export interface GlossaryListResponse {
  entries: GlossaryEntry[];
  categories: string[];
  count: number;
}
/**
 * Liveness-probe envelope. Returned by ``GET /api/health``.
 *
 * `status` is a fixed-vocabulary string ("ok" today; future values
 * might include "degraded" / "warehouse_missing" once we surface
 * warehouse-connectivity probes).
 */
export interface HealthResponse {
  status: string;
  api_version: string;
}
