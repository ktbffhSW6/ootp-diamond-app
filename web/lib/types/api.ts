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
 * One award type with its display label + which sources have data
 * for it in the current league. Used by the frontend to render the
 * award picker and grey out era filters that would yield zero rows.
 */
export interface AwardCategoryRef {
  award_id: number;
  label: string;
  available_sources: ("save" | "merged")[];
}
/**
 * One trophy-case row.
 *
 * ``rank`` is the in-render rank (1-based). Ties broken by
 * ``last_year DESC`` (recency over depth) — matches the existing
 * ``diamond awards`` CLI behavior. ``n_won`` is the career trophy
 * count for this (player, league, award) combination.
 *
 * ``player_id`` populated → name renders as a link to
 * ``/player/<id>``. Otherwise plain text (real-life player not
 * in the save). ``external_id`` is the bbref_id when ``source =
 * 'merged'`` — kept for traceability + tooltip.
 *
 * ``first_team_abbr`` / ``last_team_abbr`` may be null for merged
 * rows (Lahman team mapping isn't bijective with OOTP teams) and
 * for save rows where the underlying snapshot didn't carry team
 * metadata at the time of the win (rare).
 */
export interface AwardHolderRow {
  rank: number;
  source: "save" | "merged";
  player_id: number | null;
  external_id: string | null;
  display_name: string;
  n_won: number;
  first_year: number | null;
  last_year: number | null;
  first_team_abbr: string | null;
  last_team_abbr: string | null;
}
/**
 * Lightweight league handle for the picker. ``league_level``
 * mirrors OOTP's level numeric (1 = MLB, 2 = AAA, 3 = AA, etc.)
 * so the frontend can group / order leagues by tier.
 */
export interface AwardLeagueRef {
  league_id: number;
  abbr: string | null;
  name: string | null;
  league_level: number;
}
/**
 * Whole payload for one rendered awards leaderboard.
 *
 * The picker payload (``available_leagues`` + ``available_awards``
 * + the active league/award/era) lets the frontend render every
 * control without round-trips.
 *
 * ``rows`` is sorted by rank ASC (n_won DESC, last_year DESC tie-
 * break), already era-filtered, already capped at the route's
 * limit. ``total_in_source`` is the count *before* the limit was
 * applied so the UI can show "showing top 25 of 173" hints.
 */
export interface AwardsResponse {
  league: AwardLeagueRef;
  award_id: number;
  era: "all" | "save" | "real";
  available_leagues: AwardLeagueRef[];
  available_awards: AwardCategoryRef[];
  rows: AwardHolderRow[];
  total_in_source: number;
}
/**
 * Slimmed-down ledger row for the recent-moves strip.
 */
export interface CockpitMovementRow {
  movement_id: number;
  player_id: number;
  display_name: string;
  movement_type: string;
  direction: string;
  from_team_abbr: string | null;
  to_team_abbr: string | null;
  movement_date: string;
}
/**
 * One pressure-summary row — slimmer than ``/api/pressure``'s
 * ``PressurePlayer`` since the cockpit only needs name + headline
 * metric + level for at-a-glance scanning.
 */
export interface CockpitPressureRow {
  player_id: number;
  display_name: string;
  role: "batter" | "pitcher";
  level_name: string;
  metric: number;
  sample: string;
  team_abbr: string | null;
}
/**
 * Top 3 promotion candidates + top 3 pressure cases at MLB level.
 *
 * The cockpit intentionally limits to MLB to keep the strip tight —
 * the full per-level board lives on ``/pressure``. A user landing
 * on the cockpit asks "what does my big-league roster need?";
 * minor-league pressure is one click away.
 */
export interface CockpitPressureSummary {
  promotion: CockpitPressureRow[];
  pressure: CockpitPressureRow[];
}
/**
 * Whole dashboard payload — one round-trip composes everything.
 *
 * ``year`` is the current cockpit year (defaults to latest with
 * data; ``available_years`` is omitted because the cockpit is
 * intentionally fixed to "now" — historical snapshots live on
 * ``/league`` / ``/pressure`` / ``/movements`` per their own pickers).
 */
export interface CockpitResponse {
  year: number;
  org_team_id: number;
  standings: CockpitStandingsBlock | null;
  pressure: CockpitPressureSummary;
  spotlight: CockpitSpotlightCard[];
  recent_movements: CockpitMovementRow[];
}
/**
 * The user's division standings only — single block, no
 * sub-league / cross-division clutter on the landing.
 *
 * ``division_name`` may be null for leagues without divisions; the
 * UI hides the header in that case. ``snapshot_date`` is the
 * resolved MAX(dump_date) within the cockpit's chosen year so the
 * user knows which monthly cut they're seeing.
 */
export interface CockpitStandingsBlock {
  division_name: string | null;
  snapshot_date: string;
  rows: CockpitStandingsRow[];
}
/**
 * One team line in the user's division standings.
 *
 * ``is_user_org`` flags the row for the audit team (Boston) so the
 * UI highlights it without having to know the team_id.
 */
export interface CockpitStandingsRow {
  team_id: number;
  abbr: string | null;
  nickname: string | null;
  w: number;
  l: number;
  pct: number;
  gb: number;
  streak: number;
  is_user_org: boolean;
}
/**
 * One marquee Sox player. The card combines a current-year
 * headline metric, a career WAR sparkline, and a one-line auto-
 * generated insight.
 *
 * ``career_war_by_year`` is a parallel-list pair of (year, war)
 * aligned by index. Years with no advanced data render as nulls
 * in the WAR list so the sparkline draws gaps cleanly.
 *
 * ``insight`` is server-generated NLG ("Career year — 9.3 WAR
 * blows past prior 6.1 peak") and is null when no comparable can
 * be computed (e.g., rookie season). The UI renders it as a small
 * italic line under the name.
 */
export interface CockpitSpotlightCard {
  player_id: number;
  display_name: string;
  position: number;
  role: "batter" | "pitcher" | "two-way";
  team_abbr: string | null;
  headline_metric_label: string;
  headline_metric_value: number;
  sample: string;
  war_current: number;
  career_years: number[];
  career_war: (number | null)[];
  insight: string | null;
}
/**
 * One player's compare card payload.
 *
 * All career counters are sums across stints. ``career_avg/obp/slg``
 * are recomputed from totals (not averaged from per-season rates),
 * which matches the canonical Bref career line.
 *
 * ``career_years`` + ``career_war`` are parallel arrays for the
 * overlay sparkline — same shape as
 * ``CockpitSpotlightCard.career_*`` so the frontend can reuse
 * Sparkline directly. Years with no advanced data render as null
 * in the WAR list (gap in the line).
 *
 * ``latest_year`` is the most recent season the player appeared
 * in. ``latest_ops_plus`` / ``latest_era_plus`` are the headline
 * rate metric for that year (when populated); the frontend picks
 * one based on which is non-null.
 */
export interface ComparePlayer {
  player_id: number;
  display_name: string;
  position_name: string;
  bats_throws: string | null;
  age: number | null;
  current_team_abbr: string | null;
  is_retired: boolean;
  is_hall_of_fame: boolean;
  career_g_bat: number;
  career_pa: number;
  career_ab: number;
  career_h: number;
  career_hr: number;
  career_rbi: number;
  career_sb: number;
  career_avg: number | null;
  career_obp: number | null;
  career_slg: number | null;
  career_g_pit: number;
  career_w: number;
  career_l: number;
  career_sv: number;
  career_outs: number;
  career_so: number;
  career_era: number | null;
  career_whip: number | null;
  career_years: number[];
  career_war: (number | null)[];
  career_total_war: number;
  latest_year: number | null;
  latest_ops_plus: number | null;
  latest_era_plus: number | null;
  latest_war: number | null;
}
/**
 * Whole compare payload.
 *
 * ``players`` is in the same order the user passed IDs; missing
 * IDs surface in ``not_found`` so the frontend can render an
 * "X not in scope" hint without breaking the layout.
 */
export interface CompareResponse {
  players: ComparePlayer[];
  not_found: number[];
}
/**
 * One year of a multi-year deal.
 *
 * ``year`` is the actual season; ``season_index`` is 0-based offset
 * from contract start (useful for the UI's bar-chart x-axis).
 * Option flags are mutually exclusive across the three types but
 * co-exist with ``has_buyout`` when the option is bought out
 * instead of exercised.
 */
export interface ContractYear {
  year: number;
  season_index: number;
  salary: number;
  is_current: boolean;
  is_team_option: boolean;
  is_player_option: boolean;
  is_vesting_option: boolean;
  has_buyout: boolean;
  buyout_amount: number;
  can_opt_out: boolean;
}
/**
 * One outcome bucket, with its picks ordered by overall pick ASC.
 *
 * Per-bucket count surfaced separately so the UI can render
 * section headers with size hints ("MLB Regulars · 7") without
 * counting client-side.
 */
export interface DraftBucket {
  outcome: "mlb_regular" | "mlb_callup" | "in_draft_org" | "traded_away" | "released" | "retired";
  label: string;
  count: number;
  rows: DraftPick[];
}
/**
 * One drafted player + their current outcome.
 *
 * ``draft_overall_pick`` is the global pick number (1.1 = 1, 1.2 = 2,
 * ..., 2.1 = 31, etc. — depends on round size). ``draft_round`` is
 * the round number, kept for display ("Rd 4, Pick 124").
 *
 * ``career_mlb_war`` is the canonical "how did this pick turn out?"
 * number — sums batting + pitching WAR across the player's MLB
 * career. Always populated (zeros for players who never made MLB).
 *
 * ``mlb_g`` / ``mlb_pa`` / ``mlb_outs`` are batting/pitching career
 * counters; the UI picks one to display based on the player's
 * primary discipline.
 *
 * ``current_team_name`` is the team they're on now (could be the
 * drafting org for ``in_draft_org`` outcomes, a different MLB org
 * for ``traded_away``, or null for retired/released). ``current_level_id``
 * 1=MLB, 2=AAA, 3=AA, 4=A+/A, 6=Rk/DSL — same convention as
 * elsewhere.
 */
export interface DraftPick {
  player_id: number;
  display_name: string;
  position: number;
  bats: number | null;
  throws: number | null;
  draft_age: number | null;
  draft_round: number | null;
  draft_overall_pick: number | null;
  draft_team_name: string | null;
  current_team_name: string | null;
  current_level_id: number | null;
  outcome: "mlb_regular" | "mlb_callup" | "in_draft_org" | "traded_away" | "released" | "retired";
  ever_made_mlb: boolean;
  first_mlb_date: string | null;
  mlb_g: number;
  mlb_pa: number;
  mlb_hr: number;
  mlb_war_bat: number;
  mlb_g_pit: number;
  mlb_outs: number;
  mlb_w: number;
  mlb_s: number;
  mlb_war_pit: number;
  career_mlb_war: number;
}
/**
 * Whole payload for one rendered draft year.
 *
 * ``available_years`` lists every year with picks (used by the
 * year picker). ``summary`` is the headline counts for the rendered
 * year. ``buckets`` is the actual roster, grouped + ordered.
 */
export interface DraftClassResponse {
  year: number;
  available_years: number[];
  summary: DraftClassSummary;
  buckets: DraftBucket[];
}
/**
 * Year-level summary for the page header.
 *
 * ``total_picks`` is the count of all rows in the class (≈573-599
 * per year in this save). ``ever_made_mlb`` is the cumulative
 * promote-to-MLB count across the class — the headline "x% of this
 * class has made the show" stat.
 */
export interface DraftClassSummary {
  year: number;
  total_picks: number;
  ever_made_mlb: number;
  mlb_regular: number;
  mlb_callup: number;
  in_draft_org: number;
  traded_away: number;
  released: number;
  retired: number;
}
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
 * One Hall row — same shape for inductees + candidates so the
 * table component is uniform.
 *
 * For inductees, ``inducted_year`` is populated and ``rank`` is
 * null (inductees are ordered by year, not WAR rank).
 *
 * For candidates, ``inducted_year`` is null and ``rank`` is the
 * 1-based career-WAR rank within the non-inducted cohort.
 *
 * ``career_war`` is OOTP's directly-supplied combined WAR (sum of
 * ``f_player_season_advanced_batting.b_war`` across the player's
 * seasons — same value the player page Advanced view shows). May
 * be null for pure-pitcher inductees from the pre-fWAR era; the UI
 * renders a dash in that case.
 *
 * ``last_team_abbr`` is the most recent team the player wore;
 * blank for ancient retirees whose final team didn't survive
 * OOTP's team-history tracking.
 */
export interface HofPlayer {
  player_id: number;
  display_name: string;
  inducted_year: number | null;
  rank: number | null;
  career_war: number | null;
  last_team_abbr: string | null;
  retired: boolean;
}
/**
 * Whole payload — inductees-or-candidates rows + the counts so
 * the toggle pill can show "·N" hints on each side without a second
 * round-trip.
 */
export interface HofResponse {
  view: "inductees" | "candidates";
  rows: HofPlayer[];
  inductees_count: number;
  candidates_count: number;
}
/**
 * An entry in the stat picker — one of the supported leaderboard stats.
 *
 * The frontend uses this to build a grouped dropdown ("Batting / Pitching
 * / Statcast"). `qualifier_label` ("PA" / "IP" / "BIP") tells the picker
 * UI what the default minimum gates against.
 */
export interface LeaderboardOption {
  id: string;
  label: string;
  discipline: string;
  direction: string;
  decimals: number;
  default_min: number;
  qualifier_label: string;
}
/**
 * All supported leaderboard stats — used to build the picker.
 */
export interface LeaderboardOptionsResponse {
  options: LeaderboardOption[];
}
/**
 * A single leaderboard request's payload.
 *
 * Echoes the resolved stat spec + filters so the frontend doesn't
 * have to re-derive labels / direction from the URL alone. `rows`
 * is already pre-sorted by the requested direction.
 */
export interface LeaderboardResponse {
  stat: LeaderboardStatSpec;
  year: number | null;
  level_id: number | null;
  league_id: number | null;
  pa_min: number;
  qualifier_label: string;
  rows: LeaderboardRow[];
}
/**
 * Description of the requested stat — echoed in the response.
 *
 * `discipline` is "batting" / "pitching" / "statcast_b" / "statcast_p"
 * so the frontend can render appropriate column headers (PA vs IP vs
 * BIP qualifier). `direction` is "desc" (higher is better — HR, OPS+,
 * bWAR) or "asc" (lower is better — ERA, FIP, SIERA).
 */
export interface LeaderboardStatSpec {
  id: string;
  label: string;
  discipline: string;
  direction: string;
  decimals: number;
}
/**
 * One row in the leaderboard.
 *
 * `value` is the headline stat (formatted to `stat.decimals` on the
 * frontend). `qualifier_value` is the PA / outs / BIP threshold the
 * row passed (rendered as a secondary column for context). `team_abbr`
 * is the dominant-team abbreviation at this level — null for players
 * whose dominant team isn't in the active save's `teams` reference
 * table (e.g., defunct historical franchises pre-2026).
 */
export interface LeaderboardRow {
  rank: number;
  player_id: number;
  player_name: string;
  team_id: number | null;
  team_abbr: string | null;
  league_id: number | null;
  level_id: number | null;
  year: number | null;
  value: number | null;
  qualifier_value: number;
}
/**
 * Headline batting line shown in the before / after columns.
 *
 * ``ops_plus`` is the verdict driver (already park-adjusted, league-
 * relative, scale 100 = average). ``wrc_plus`` is shown alongside
 * for the wOBA-leaning reader; both come from the same L3 fact row.
 * ``pa`` is the sample size — also drives the ``too_small`` verdict
 * when below 30 at the new level.
 */
export interface MovementBattingStats {
  pa: number;
  ops_plus: number | null;
  wrc_plus: number | null;
  woba: number | null;
  o_war: number | null;
}
/**
 * Headline pitching line. Mirrors the batting model but for
 * pitchers. ``era_plus`` is the verdict driver (same 100=avg
 * convention). ``fip`` is included for a peripheral cross-check;
 * ``ip_display`` uses the OOTP convention (FLOOR(outs/3) + (outs%3)*0.1)
 * rather than decimal. ``outs`` is the raw sample size used in the
 * too_small check (< 30 outs = < 10 IP).
 */
export interface MovementPitchingStats {
  outs: number;
  ip_display: number | null;
  era_plus: number | null;
  fip: number | null;
  pit_war: number | null;
}
/**
 * One movement event with before/after stats and a verdict.
 */
export interface MovementRow {
  movement_id: number;
  player_id: number;
  player_name: string;
  primary_position: string;
  role: "batter" | "pitcher";
  movement_type: "promotion" | "demotion" | "trade" | "signed" | "waiver_or_other" | "released";
  direction: "internal" | "incoming" | "outgoing";
  dump_date_observed: string;
  from_team: MovementTeamRef;
  to_team: MovementTeamRef;
  before_batting: MovementBattingStats | null;
  after_batting: MovementBattingStats | null;
  before_pitching: MovementPitchingStats | null;
  after_pitching: MovementPitchingStats | null;
  verdict: "working" | "reconsider" | "struggling" | "too_small";
  verdict_note: string;
}
/**
 * The from-team or to-team side of a move. Slimmer than the player
 * page's ``TeamRef`` since we don't carry the league_abbr — the
 * headline display is "MLB → AAA Worcester" so we need level + nickname,
 * not league. Kept distinct so the contract for movements is self-contained.
 */
export interface MovementTeamRef {
  team_id: number;
  abbr: string | null;
  nickname: string | null;
  level_id: number | null;
  level_name: string | null;
}
/**
 * Whole payload for the movements page.
 *
 * ``available_seasons`` lets the page render a year picker without a
 * second round-trip; ``org_team_*`` lets the header show the user's
 * team. ``rows`` is sorted DESC by date — most recent moves first.
 */
export interface MovementsResponse {
  season: number;
  available_seasons: number[];
  org_team_id: number;
  org_team_abbr: string | null;
  org_team_nickname: string | null;
  rows: MovementRow[];
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
  b_war: number | null;
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
  p_war: number | null;
  p_ra9_war: number | null;
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
 * The active contract for a player.
 *
 * Aggregate fields (``total_value``, ``remaining_value``) are
 * server-computed sums so the UI doesn't have to sum across the
 * rows array. Both are in raw USD.
 *
 * ``contract_team_abbr`` is the team that's actually paying the
 * salary (the team that signed the deal); usually equals the
 * player's current team but can differ after a trade with retained
 * salary — captured in the ``retained`` flag.
 */
export interface PlayerContract {
  contract_team_id: number | null;
  contract_team_abbr: string | null;
  start_year: number;
  years: number;
  current_year_index: number;
  no_trade: boolean;
  retained_by_prior_team: boolean;
  total_value: number;
  remaining_value: number;
  rows: ContractYear[];
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
 * One row in the per-position fielding cube — current rating +
 * ceiling + experience for a single defensive spot.
 *
 * Materialized from ``players_fielding_current`` (the latest
 * ``players_fielding_snapshot`` row). Per-position columns are the
 * OOTP-scouted 20-80 ratings — ``fielding_rating_pos1..9`` for current
 * skill, ``fielding_rating_pos1..9_pot`` for ceiling. Position
 * indexing follows the standard OOTP convention (1=P, 2=C, 3=1B,
 * 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF — no DH at the fielding grain).
 *
 * ``experience`` comes from ``fielding_experience1..9`` (the
 * 1-indexed columns; index 0 is unused / DH-bucket and isn't
 * surfaced). Units are OOTP "play attempts" — useful as a relative
 * weight ("this guy has 200 plays at 1B vs 4 at 2B") rather than a
 * sample-size threshold.
 *
 * Conventions:
 * - All three fields are nullable. A zero rating means "the player
 *   has never been rated at this position in scouting"; we surface
 *   it as ``None`` rather than ``0`` so the UI can render an
 *   em-dash without ambiguity.
 * - Zero experience also surfaces as ``None`` for the same reason
 *   — distinguishes "never tried" from "tried briefly with 0 plays
 *   somehow logged."
 *
 * Why surface this at all: the `fielding_rating_pos*` cube answers
 * the GM-side question "where should this player actually play?"
 * That info is fully populated in every dump but never reads in any
 * L2/L3/UI surface today (highest-value find from the 2026-05-09
 * dump-CSV audit — see PROJECT_STATUS / DATA_NOTES).
 */
export interface PlayerPositionFielding {
  position: number;
  position_name: string;
  rating_current: number | null;
  rating_potential: number | null;
  experience: number | null;
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
  position_fielding: PlayerPositionFielding[];
  roster_status: PlayerRosterStatus | null;
  contract: PlayerContract | null;
  situational_batting: PlayerSituationalRow[];
  situational_pitching: PlayerSituationalRow[];
}
/**
 * Service-time / arbitration / options / roster-status block.
 *
 * Sourced from the latest ``roster_status_current`` row. The
 * canonical "when does this guy hit FA?" answer + the GM-side
 * flags (active / DL / DFA / waivers) used to read player
 * availability at a glance.
 *
 * Semantics:
 * - **MLB service time** — OOTP credits 172 days per season-year.
 *   ``mlb_service_days`` is total accumulated days; whole years =
 *   ``mlb_service_years`` (= ``floor(days / 172)``); leftover days =
 *   ``mlb_service_days - 172 * mlb_service_years``. The header
 *   conventionally displays "Xy Yd" where Y is leftover days
 *   (Bref / MLBPA convention).
 * - **Service class** is computed in the route: ``pre_arb`` (<3y),
 *   ``arb_y1`` / ``arb_y2`` / ``arb_y3`` (3-6y, by full year), or
 *   ``fa_eligible`` (≥6y). 6.000 = free-agent eligible at end of
 *   season unless extended.
 * - **Days-to-FA** = max(0, 6 × 172 - mlb_service_days). The
 *   remaining service days the player needs before reaching free
 *   agency. Zero when already FA-eligible.
 * - **Options** — minor-league options. OOTP's convention matches
 *   MLB's: a player has 3 option years; ``options_used`` counts how
 *   many have been burned career-to-date (0-3+). Once exhausted, a
 *   player can no longer be sent to AAA/MiLB without DFA.
 * - **Status flags** — ``is_active`` is on the active 26-man;
 *   ``is_on_secondary`` is the 40-man / reserve placeholder;
 *   ``is_on_dl`` / ``_dl60`` mark IL placements (10-day / 60-day);
 *   ``designated_for_assignment`` / ``is_on_waivers`` are the
 *   transactional out-of-roster states. Most flags are zero in the
 *   November end-of-season snapshot — they light up in mid-season
 *   ingests.
 *
 * Fields not surfaced (semantics unclear without further audit):
 * ``years_protected_from_rule_5``, ``has_received_arbitration``.
 * Add when needed.
 */
export interface PlayerRosterStatus {
  mlb_service_years: number;
  mlb_service_days: number;
  mlb_service_days_this_year: number;
  service_display: string;
  service_class: string;
  service_class_label: string;
  days_to_free_agency: number;
  is_free_agent_eligible: boolean;
  options_used: number;
  options_used_this_year: number;
  options_remaining: number;
  is_active: boolean;
  is_on_secondary: boolean;
  is_on_dl: boolean;
  is_on_dl60: boolean;
  designated_for_assignment: boolean;
  is_on_waivers: boolean;
}
/**
 * Per-(year, level, split) situational stats from `f_pa_event`.
 *
 * Same row shape for both batter and pitcher views — the difference
 * is the dimension used to filter the PA log:
 *
 * - **Batter view** (``situational_batting``): keyed on ``batter_id``.
 *   Slash line is what the player hit. Higher OPS in clutch = good.
 * - **Pitcher view** (``situational_pitching``): keyed on ``pitcher_id``.
 *   Slash line is what the player ALLOWED. Lower OPS in clutch = good
 *   (the UI inverts the color hint accordingly).
 *
 * Splits cover the canonical clutch / leverage / platoon / count /
 * spray cuts (14 in total, organized into five clusters):
 *
 * Leverage:
 *
 * - ``all``          — every regular-season PA (parity row vs the
 *   regular batting/pitching season totals).
 * - ``risp``         — runner on 2nd OR 3rd at start of PA (`risp_flag`).
 * - ``risp_2out``    — RISP AND outs ≥ 2 (the highest-leverage RBI chance).
 * - ``late_close``   — 7th inning or later AND OOTP `Close` flag (Bref-style
 *   "Late & Close": tying / go-ahead run on / at-bat / on-deck).
 *
 * Bases:
 *
 * - ``bases_empty``  — base1=base2=base3=0 (low-leverage baseline).
 * - ``bases_loaded`` — base1>0 AND base2>0 AND base3>0 (max RBI chance).
 *
 * Platoon:
 *
 * - ``vs_left`` / ``vs_right`` — opposing hand (LHP/RHP for batter
 *   view, LHB/RHB for pitcher view). Switch-hitters resolve to the
 *   opposite of the pitcher's throwing hand for the pitcher view.
 *
 * Counts (count BEFORE the resolving pitch):
 *
 * - ``first_pitch`` — 0-0 result (PA resolved on pitch 1).
 * - ``two_strike``  — strikes=2 when resolved.
 * - ``full_count``  — 3-2 when resolved.
 *
 * Spray (BIP only — K/BB/HBP excluded; AVG within these splits is
 * hits-per-BIP since AB ≈ COUNT(*) within the BIP filter; OBP
 * collapses to AVG since BB/HBP are zero):
 *
 * - ``pull`` / ``center`` / ``oppo`` — based on `hit_xy` packed
 *   coord (`x = hit_xy / 16`). Empirically batter-relative — same
 *   `x ≤ 5 → pull`, `6..9 → center`, `x ≥ 10 → oppo` rule for
 *   both hands.
 *
 * Sanity invariants (verified live): bases_empty + (bases-with-runners)
 * = all; vs_left + vs_right = all when handedness is fully populated;
 * pull + center + oppo = total BIP for that (year, level).
 *
 * Slash line is computed server-side so the frontend doesn't have to
 * re-derive it. ``split_label`` is the display string ("RISP, 2 out" /
 * "Late & Close"); ``split`` is the stable id for sort + frontend cases.
 *
 * OOTP's looser ``close_flag`` (~80% of all PAs at MLB) is intentionally
 * NOT surfaced as a split — it's too permissive to mean "clutch" in the
 * Bref sense; ``late_close_flag`` (the strict 7th+ tying-run window) is
 * the right analog and what we use here. See DATA_NOTES.
 *
 * **Multi-year coverage**: ``f_pa_event`` is sourced from L0 with
 * cross-dump dedup (the L0 layer retains every previously-ingested
 * dump's rows by ``dump_date``, so historical seasons survive the OOTP
 * rollover that overwrites ``at_bats_event.csv``). Splits cover every
 * year the warehouse has ingested (2026-2029 in this save).
 */
export interface PlayerSituationalRow {
  year: number;
  level_id: number;
  level_name: string | null;
  split: string;
  split_label: string;
  pa: number;
  ab: number;
  h: number;
  doubles: number;
  triples: number;
  hr: number;
  bb: number;
  k: number;
  hbp: number;
  sf: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  ops: number | null;
}
/**
 * One level's pressure-board card.
 *
 * ``promotion_candidates`` is sorted by ``metric DESC`` (best
 * performers first). ``pressure_cases`` is sorted by ``metric
 * ASC`` (worst first). Each is capped to a small N (configurable
 * via the route's ``limit``; default 6) so the per-level card
 * stays scannable.
 *
 * ``level_name`` is the display label (MLB / AAA / AA / A+ / A /
 * Rk / DSL). ``level_id`` mirrors OOTP's level numeric.
 */
export interface PressureLevelGroup {
  level_id: number;
  level_name: string;
  qualifying_count: number;
  promotion_candidates: PressurePlayer[];
  pressure_cases: PressurePlayer[];
}
/**
 * One player-row on a pressure-board card.
 *
 * ``role`` distinguishes batters vs pitchers (their metric column
 * + sample-volume column are different). Batter rows surface
 * ``ops_plus`` + ``pa``; pitcher rows surface ``era_plus`` + ``ip``.
 * The frontend picks the right column based on ``role``.
 *
 * ``team_abbr`` is the team where the player accumulated the
 * most volume at this level — matches the dominant-team rollup
 * in ``f_player_season_advanced_*``.
 *
 * ``war`` is OOTP's directly-supplied combined WAR (b_war for
 * batters, p_war for pitchers). Useful as a value sanity-check
 * alongside the rate stat.
 */
export interface PressurePlayer {
  player_id: number;
  display_name: string;
  role: "batter" | "pitcher";
  pa: number | null;
  ip: number | null;
  metric: number;
  delta: number;
  war: number;
  team_abbr: string | null;
  position: number | null;
}
/**
 * Whole payload — every level with org rows above the sample bar.
 *
 * Levels with no qualifying players drop out (an A-ball complex
 * with three pre-call-up rookies hits zero qualifiers and is
 * skipped). ``available_years`` lets the year picker render
 * without a second round-trip.
 */
export interface PressureResponse {
  year: number;
  available_years: number[];
  org_team_id: number;
  levels: PressureLevelGroup[];
}
/**
 * Lightweight category handle for the picker.
 *
 * ``available_sources`` lists which sources have data for this
 * (scope, discipline, category). Used by the frontend to hide the
 * Era filter when only one source exists (Career WAR is save-only,
 * for example) or to grey out an Era option that won't return rows.
 * ``label`` is the human-readable name ("Home Runs" / "Wins Above
 * Replacement"); ``unit_label`` is the suffix to append after the
 * value ("mph", "%", "ft", or empty for counters + WAR).
 */
export interface RecordCategoryRef {
  category: string;
  label: string;
  unit_label: string;
  direction: "asc" | "desc";
  available_sources: ("save" | "lahman" | "bref" | "merged" | "statcast")[];
}
/**
 * One leaderboard line.
 *
 * ``rank`` is the in-render rank — when ``era='all'`` the route
 * re-ranks across the merged source list, so this can differ from
 * ``rank_in_source`` (the original within-source rank, kept for
 * traceability + tooltip).
 *
 * ``player_id`` populated → the UI renders the name as a link to
 * ``/player/<id>``. When null (most lahman/bref/statcast rows for
 * real players who aren't in the save), the name renders as plain
 * text. ``external_id`` is the source's own ID (bbref_id for
 * lahman/bref, mlb_id for statcast) — surfaced for completeness
 * but not clickable.
 *
 * ``year`` is null for career-scope rows; ``team_abbr`` is the
 * team at peak (career) or season team (season). Nullable in
 * edge cases (early-1880s pre-team-tracking rows in Lahman).
 */
export interface RecordRow {
  rank: number;
  rank_in_source: number;
  source: "save" | "lahman" | "bref" | "merged" | "statcast";
  player_id: number | null;
  external_id: string | null;
  display_name: string;
  year: number | null;
  team_abbr: string | null;
  value: number;
}
/**
 * Whole payload for one rendered leaderboard.
 *
 * The picker payload (``available_categories`` + the active
 * scope/discipline/category/era) lets the frontend render every
 * control without round-trips. Switching axes is a Link change —
 * no client-side state.
 *
 * ``rows`` is already sorted (by ``rank`` ascending), already
 * rank-stamped, already era-filtered. The frontend renders straight
 * from this list with no additional sort/filter logic — keeps the
 * server as the single source of ordering truth.
 *
 * ``total_in_source`` is the count *before* the limit was applied,
 * so the page can show "showing top 25 of 150" hints when more
 * rows exist (full top-50 / top-150 still surfaceable via the CLI
 * or a future "show all" toggle).
 */
export interface RecordsResponse {
  scope: "season" | "career";
  discipline: "batting" | "pitching";
  category: string;
  era: "all" | "save" | "real" | "statcast";
  direction: "asc" | "desc";
  available_categories: RecordCategoryRef[];
  rows: RecordRow[];
  total_in_source: number;
}
/**
 * Latest-season batting line at the player's current level.
 *
 * Counting stats come from ``f_player_season_batting`` filtered to
 * ``(year=latest, league_id=current, level_id=current, team_id=current,
 * split_id=1)``. Rate stats are computed in the route. Advanced fields
 * (``woba`` / ``wrc_plus`` / ``ops_plus`` / ``o_war``) come from
 * ``f_player_season_advanced_batting`` joined on (year, league, level)
 * — the advanced fact table already collapses stints within a level.
 *
 * Every numeric is nullable when the denominator is zero or the
 * advanced row didn't materialize (sub-threshold sample, pre-2026
 * seasons with no league baselines, etc.).
 */
export interface RosterBattingLine {
  g: number;
  pa: number;
  ab: number;
  h: number;
  hr: number;
  rbi: number;
  sb: number;
  bb: number;
  so: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  ops: number | null;
  woba: number | null;
  wraa: number | null;
  wrc: number | null;
  wrc_plus: number | null;
  ops_plus: number | null;
  o_war: number | null;
  b_war: number | null;
  park_avg: number | null;
  statcast_bip: number | null;
  statcast_max_ev: number | null;
  statcast_avg_ev: number | null;
  statcast_hard_hit_pct: number | null;
  statcast_barrel_pct: number | null;
  statcast_sweet_spot_pct: number | null;
}
/**
 * All active org players currently at one level.
 *
 * ``level_id`` follows ``LEVEL_NAMES`` (1=MLB, 2=AAA, ...);
 * ``level_name`` is pre-resolved for display. Sorted MLB first then
 * descending by level. Within the group, ``position_players`` and
 * ``pitchers`` are each sorted by position then descending overall
 * rating then last name.
 */
export interface RosterLevelGroup {
  level_id: number;
  level_name: string;
  position_players: RosterPlayer[];
  pitchers: RosterPlayer[];
}
/**
 * One player on the user's org-tree roster.
 *
 * Bio fields come from ``players_current``; ``overall_rating`` (20-80
 * scale per D6) from ``players_ratings_current`` (filtered to user-org
 * scouted view per D12). ``team`` is the current team's identity;
 * ``batting`` and ``pitching`` carry the latest-season stats at that
 * team's level. Both stat blocks may be null — pitchers usually have
 * ``batting=None``, position players ``pitching=None``.
 */
export interface RosterPlayer {
  player_id: number;
  full_name: string;
  primary_position: string;
  role: "batter" | "pitcher";
  age: number | null;
  bats: string;
  throws: string;
  overall_rating: number | null;
  team: RosterTeamRef | null;
  batting: RosterBattingLine | null;
  pitching: RosterPitchingLine | null;
}
/**
 * Slim team reference — current team for a roster row.
 *
 * Carries league + level identifiers so the frontend can render
 * "MLB Boston (AL)" without a second lookup. Mirrors ``TeamRef``
 * from the player schema but stays distinct so the roster contract
 * is self-contained (per the schemas convention).
 */
export interface RosterTeamRef {
  team_id: number;
  abbr: string | null;
  nickname: string | null;
  league_id: number | null;
  league_abbr: string | null;
  level_id: number | null;
  level_name: string | null;
}
/**
 * Latest-season pitching line at the player's current level.
 *
 * Same pattern as the batting line: counting + rate stats from
 * ``f_player_season_pitching``, advanced (FIP / ERA+ / pit_WAR) from
 * ``f_player_season_advanced_pitching``. ``ip_display`` follows the
 * OOTP convention (517 outs → 172.1 = 172⅓); use ``outs`` for any
 * arithmetic.
 */
export interface RosterPitchingLine {
  g: number;
  gs: number;
  w: number;
  l: number;
  sv: number;
  outs: number;
  ip_display: number;
  era: number | null;
  whip: number | null;
  k_per_9: number | null;
  bb_per_9: number | null;
  fip: number | null;
  siera: number | null;
  era_plus: number | null;
  pit_war: number | null;
  p_war: number | null;
  p_ra9_war: number | null;
  park_avg: number | null;
  statcast_bip: number | null;
  statcast_max_ev: number | null;
  statcast_avg_ev: number | null;
  statcast_hard_hit_pct: number | null;
  statcast_barrel_pct: number | null;
  statcast_sweet_spot_pct: number | null;
}
/**
 * ``GET /api/roster`` response.
 *
 * Whole org snapshot in one round-trip; the frontend handles all
 * filter / sort / toggle interactions client-side over this payload.
 * With ~150-200 players in a typical org, the JSON is small enough
 * (~50KB uncompressed) that streaming or pagination would be
 * premature.
 */
export interface RosterResponse {
  season: number;
  org_team_id: number;
  org_team_abbr: string | null;
  org_team_nickname: string | null;
  groups: RosterLevelGroup[];
}
/**
 * Active-save identity + ingest health + scope counts.
 */
export interface SaveResponse {
  save_name: string;
  org_team_id: number;
  org_team_abbr: string | null;
  org_team_nickname: string | null;
  dump_count: number;
  latest_dump_date: string | null;
  latest_dump_name: string | null;
  latest_season: number | null;
  earliest_season: number | null;
  scoped_player_count: number;
  scoped_team_count: number;
}
/**
 * A division — a list of team rows ordered by ``pos`` ascending.
 *
 * For leagues with no divisions (AFL) the route still emits a single
 * placeholder division with ``division_id=0`` and ``division_name=None``
 * so the rendering stays uniform.
 */
export interface StandingsDivision {
  division_id: number;
  division_name: string | null;
  teams: StandingsTeamRow[];
}
/**
 * One team line in the standings table.
 *
 * ``pos`` is the position within division (1 = leader). ``gb`` is
 * games behind the division leader (0.0 for the leader). ``streak``
 * is signed: positive integer = current win streak length, negative
 * = loss streak length, zero = no streak (e.g., season hasn't started
 * or last result was a tie).
 *
 * ``magic_number`` is null when OOTP's "1000" sentinel applied
 * (out of contention / not yet meaningful); ``clinched`` is true
 * when OOTP's "-1" sentinel applied (division clinched). The two
 * flags are mutually exclusive — at most one is set on any row.
 * ``is_user_org`` flags the row for the audit team (Boston) so the
 * UI can highlight it without needing to know the team_id.
 */
export interface StandingsTeamRow {
  team_id: number;
  abbr: string | null;
  nickname: string | null;
  g: number;
  w: number;
  l: number;
  t: number;
  pct: number;
  gb: number;
  streak: number;
  magic_number: number | null;
  clinched: boolean;
  pos: number;
  is_user_org: boolean;
}
/**
 * Lightweight league handle — used in both the headline and the
 * league-picker payload. ``league_level`` mirrors OOTP's level numeric
 * (1 = MLB, 2 = AAA, 3 = AA, 4 = A+/A, 6 = Rk/Complex/DSL, 9 = AFL).
 */
export interface StandingsLeagueRef {
  league_id: number;
  abbr: string | null;
  name: string | null;
  league_level: number;
}
/**
 * Whole payload for the standings tab.
 *
 * ``available_leagues`` and ``available_years`` let the page render
 * both pickers without round-trips. ``dump_date`` is the resolved
 * snapshot date (MAX dump within the chosen year) — shown in the
 * header so the user knows whether they're looking at end-of-season
 * or a mid-season cut.
 */
export interface StandingsResponse {
  league: StandingsLeagueRef;
  year: number;
  dump_date: string;
  available_leagues: StandingsLeagueRef[];
  available_years: number[];
  org_team_id: number;
  sub_leagues: StandingsSubLeague[];
}
/**
 * A sub-league — one or more divisions stacked vertically in the UI.
 *
 * For leagues with no sub-leagues (AAA / AA / A* / DSL etc.) the route
 * emits a single placeholder sub-league with ``sub_league_id=0`` and
 * ``sub_league_name=None``. The frontend hides the sub-league header
 * in that case to avoid an empty band.
 */
export interface StandingsSubLeague {
  sub_league_id: number;
  sub_league_name: string | null;
  divisions: StandingsDivision[];
}
/**
 * Lightweight streak handle for the picker. ``available_scopes``
 * lists which scopes have data for this streak type — every code
 * has both in our build, but the field is present in case a future
 * save loses one (e.g., zero active games-played streaks because
 * the season just rolled over).
 */
export interface StreakCategoryRef {
  streak_id: number;
  label: string;
  available_scopes: ("active" | "all_time")[];
}
/**
 * One streak-leaderboard row.
 *
 * ``rank`` mirrors ``rank_in_scope`` (no re-ranking needed; the
 * L3 build already top-50'd per (streak_id, scope)).
 *
 * ``has_ended`` distinguishes active vs ended streaks. When
 * ``scope='active'``, ``has_ended`` is always false; when
 * ``scope='all_time'``, it can be either (active streaks
 * naturally appear in both scopes — same player, same value).
 *
 * ``ended`` is the date string from the dump (e.g., ``"2028-7-29"``
 * or ``"NULL"`` for active rows). The L3 builder leaves it as a
 * string because the dump's date format isn't always parseable
 * (single-digit months don't zero-pad). The UI renders it
 * verbatim when present.
 *
 * ``team_abbr`` is the team at the start of the streak; nullable
 * when the dump didn't carry team metadata for that game (pre-2026
 * real-history streaks).
 */
export interface StreakRow {
  rank: number;
  player_id: number | null;
  display_name: string;
  value: number;
  has_ended: boolean;
  started: string | null;
  ended: string | null;
  league_id: number | null;
  team_abbr: string | null;
}
/**
 * One streak's leaderboard, top-N holders.
 *
 * ``available_streaks`` is the full picker list (all 21 streak_ids
 * in the warehouse, with their labels). ``streak_id`` + ``scope``
 * are the active selection.
 *
 * Like records / awards, the rendered ``rows`` is the source of
 * truth for ordering — server already ordered by rank ASC.
 */
export interface StreaksResponse {
  streak_id: number;
  streak_label: string;
  scope: "active" | "all_time";
  available_streaks: StreakCategoryRef[];
  rows: StreakRow[];
  total_in_scope: number;
}
