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
/**
 * Per-(year, league_id, level_id) advanced batting stats.
 *
 * One row per league-year-level a player accumulated PA in. Multi-team
 * stints within the same level collapse to one row (the dominant
 * team's park factor applies). Cross-level rollups are intentionally
 * omitted — league constants differ by level so cross-level wRC+
 * isn't a well-defined number.
 */
export interface PlayerAdvancedBattingRow {
  year: number;
  age: number | null;
  level_id: number;
  level_name: string;
  league_id: number;
  league_abbr: string | null;
  pa: number;
  woba: number | null;
  wraa: number | null;
  wrc: number | null;
  wrc_plus: number | null;
  ops_plus: number | null;
  o_war: number | null;
  park_avg: number | null;
}
/**
 * Per-(year, league_id, level_id) advanced pitching stats.
 *
 * Only pitchers with ≥ 30 outs (≥ 10 IP) at the level appear — matches
 * the audit's quality threshold. Park factor is the dominant team's
 * (most outs at this level).
 */
export interface PlayerAdvancedPitchingRow {
  year: number;
  age: number | null;
  level_id: number;
  level_name: string;
  league_id: number;
  league_abbr: string | null;
  outs: number;
  ip_display: number;
  fip: number | null;
  era_plus: number | null;
  pit_war: number | null;
  park_avg: number | null;
}
/**
 * A year's worth of batting — one or more stints + optional TOT row.
 *
 * `stints` always has 1+ rows (sorted by level then team). `combined`
 * is populated only when there were multiple stints; equal to None
 * when a single stint covers the whole year.
 */
export interface PlayerBattingSeason {
  year: number;
  age: number | null;
  stints: PlayerBattingStint[];
  combined: PlayerBattingStint | null;
}
/**
 * One batter row at (year, league, level, team) grain.
 *
 * Counting fields come straight from `f_player_season_batting`; rate
 * fields are computed in the route. `is_combined=True` flags the
 * synthesized per-season "TOT" row (team_id is null on those).
 */
export interface PlayerBattingStint {
  year: number;
  age: number | null;
  is_combined: boolean;
  team: TeamRef | null;
  g: number;
  pa: number;
  ab: number;
  r: number;
  h: number;
  d: number;
  t: number;
  hr: number;
  rbi: number;
  sb: number;
  cs: number;
  bb: number;
  so: number;
  hbp: number;
  sf: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  ops: number | null;
}
/**
 * Slim team reference embedded in stints + bio.
 *
 * Carries enough to render a column without round-tripping the team list:
 * abbr (short label), nickname (long label), league_abbr (e.g. "AL/NL"
 * or affiliate league), and level_id (mapped to MLB/AAA/AA/etc. via
 * `LEVEL_NAMES` on the frontend or via the `level_name` convenience).
 */
export interface TeamRef {
  team_id: number;
  abbr: string | null;
  nickname: string | null;
  league_id: number | null;
  league_abbr: string | null;
  level_id: number | null;
  level_name: string | null;
}
/**
 * Identifying / display fields for the player header.
 *
 * `position_name` is the resolved display string ("1B", "RHP", etc.)
 * via `POSITION_NAMES`. `bats_throws` collapses bats + throws to
 * Bref-style "L/R" / "R/R" / "S/R" — three letters of useful signal
 * in one line of the header.
 */
export interface PlayerBio {
  player_id: number;
  bbref_id: string | null;
  first_name: string;
  last_name: string;
  nick_name: string | null;
  full_name: string;
  age: number | null;
  date_of_birth: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  bats: number | null;
  throws: number | null;
  bats_throws: string;
  position: number | null;
  position_name: string;
  uniform_number: number | null;
  retired: boolean;
  free_agent: boolean;
  hall_of_fame: boolean;
  current_team: TeamRef | null;
}
/**
 * Cross-season cross-level batting career totals (counting + slash).
 *
 * Computed by SUMing every stint with split_id=1 (the overall split),
 * matching the convention in `f_player_career`. Restricted to
 * counting-stat fields per Decision D11 — rate stats are derivable.
 */
export interface PlayerCareerBatting {
  g: number;
  pa: number;
  ab: number;
  r: number;
  h: number;
  d: number;
  t: number;
  hr: number;
  rbi: number;
  sb: number;
  cs: number;
  bb: number;
  so: number;
  hbp: number;
  sf: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  ops: number | null;
}
/**
 * Career rollup per position.
 *
 * One row per position the player ever played; sums G/GS/INN/PO/A/E/
 * DP across years. Career-summary FPCT is the position-rollup ratio.
 * Career-across-positions totals aren't included — see PlayerFieldingRow
 * for why combining across positions is semantically fraught.
 */
export interface PlayerCareerFielding {
  position: number;
  position_name: string;
  g: number;
  gs: number;
  inn_outs: number;
  inn_display: number;
  po: number;
  a: number;
  e: number;
  dp: number;
  fpct: number | null;
}
export interface PlayerCareerPitching {
  g: number;
  gs: number;
  w: number;
  l: number;
  sv: number;
  outs: number;
  ip_display: number;
  h: number;
  r: number;
  er: number;
  hr: number;
  bb: number;
  so: number;
  bf: number;
  era: number | null;
  whip: number | null;
  k_per_9: number | null;
  bb_per_9: number | null;
}
/**
 * One fielding row at (year, league, level, team, position) grain.
 *
 * `inn_outs` is the total defensive outs (`ip*3 + ipf`); `inn_display`
 * is the Bref-style "147.1" form (147⅓). Use `inn_outs` for any
 * arithmetic; display form is lossy.
 */
export interface PlayerFieldingRow {
  year: number;
  age: number | null;
  team: TeamRef | null;
  position: number;
  position_name: string;
  g: number;
  gs: number;
  inn_outs: number;
  inn_display: number;
  po: number;
  a: number;
  e: number;
  dp: number;
  fpct: number | null;
}
export interface PlayerPitchingSeason {
  year: number;
  age: number | null;
  stints: PlayerPitchingStint[];
  combined: PlayerPitchingStint | null;
}
/**
 * One pitcher row at (year, league, level, team) grain.
 *
 * `ip_display` is the Bref-style innings-pitched representation
 * (172.1 = 172⅓ IP = 517 outs); the frontend renders it as-is. Use
 * `outs` for any computation — display-form IP is lossy across
 * arithmetic.
 */
export interface PlayerPitchingStint {
  year: number;
  age: number | null;
  is_combined: boolean;
  team: TeamRef | null;
  g: number;
  gs: number;
  w: number;
  l: number;
  sv: number;
  outs: number;
  ip_display: number;
  h: number;
  r: number;
  er: number;
  hr: number;
  bb: number;
  so: number;
  bf: number;
  era: number | null;
  whip: number | null;
  k_per_9: number | null;
  bb_per_9: number | null;
}
/**
 * ``GET /api/players/{player_id}`` response.
 *
 * Fields are nullable when the player never accumulated stats of that
 * type — e.g. a position player has `pitching_seasons=[]` and
 * `pitching_career=None`. The frontend uses these nulls to decide
 * which subsections of the page to render.
 */
export interface PlayerResponse {
  bio: PlayerBio;
  batting_seasons: PlayerBattingSeason[];
  pitching_seasons: PlayerPitchingSeason[];
  fielding_rows: PlayerFieldingRow[];
  advanced_batting: PlayerAdvancedBattingRow[];
  advanced_pitching: PlayerAdvancedPitchingRow[];
  batting_career: PlayerCareerBatting | null;
  pitching_career: PlayerCareerPitching | null;
  fielding_career: PlayerCareerFielding[];
}
