"""L3 derived advanced-stats tables — per-(player, year, league, level).

Materializes the sabermetric stat surface (wOBA / wRAA / wRC / wRC+ /
OPS+ / FIP / ERA+ / oWAR / pit_WAR / bWAR / pWAR) at a stable warehouse
grain so the player API and future leaderboards / AI prompts can SELECT
instead of recomputing on demand.

WAR convention: this table carries **two parallel WAR values per role**:
- ``o_war`` (batters) and ``pit_war`` (pitchers) — Diamond's *custom*
  inspectable formulas (wRAA-based and FIP-based respectively). Useful
  when you want to see "offense-only WAR" or "what FIP-WAR would say
  with a flat 1.13 replacement multiplier."
- ``b_war`` (batters) and ``p_war`` / ``p_ra9_war`` (pitchers) —
  **OOTP's directly-supplied WAR field**, summed across stints.
  Reconciled to IE WAR as A-tier (verified 2026-05-04: Mayer 3.2 = IE
  3.2, Gonzales 2.2 = IE 2.2, Anthony 0.9 = IE 0.9, Crochet within
  0.15). This is the canonical "combined WAR" — includes defensive
  runs (zr + framing + arm), positional adjustment, baserunning, and
  leverage adjustment for relievers. The UI Advanced view surfaces
  these; the custom o_war / pit_war stay in the table for
  transparency + glossary cross-reference.

Why per (player_id, year, league_id, level_id) — not per stint:
- **Park factors** apply per-team; a multi-team-same-level season (e.g.
  a mid-year trade between two NL clubs) gets the dominant team's
  park factor rather than something synthesized across stints.
- **League constants** are per (league_id, year, level_id) — the audit
  decoded this convention (D11). Cross-level WAR / wRC+ isn't a
  well-defined number; computing per-level keeps each row anchored to
  its own constants.
- **Sample size** — per-stint advanced stats on a 3-PA cup of coffee
  aren't useful, and the disclosure UI already exposes per-stint
  counting stats for those cases.

Resulting UI shape:
- The Stats tab renders one batting/pitching/fielding section per
  (year, level, team) — counting + slash, with TOT-row disclosure.
- A separate "Advanced" section renders one row per (year, level)
  pulling from this table — wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR.
- Players who never split a season have a 1:1 mapping; players who
  did get one advanced row per level (e.g. an MLB row + a AAA row).

Build pattern: full DROP/CREATE on every ingest (consistent with the
rest of L3). Depends on L2 being current — specifically
`f_player_season_batting`, `f_player_season_pitching`, plus the L1
reference tables `players` (for park lookup), `teams`, `parks`,
and `league_history_batting_event` / `_pitching_event` for the
league totals.

Dictionary cross-reference (per D15):
  wOBA / wRAA / wRC / wRC_plus / OPS_plus / FIP / ERA_plus / oWAR /
  pit_WAR — every column maps to a `STATS[id]` entry with the formula
  + park-factor convention documented.
"""

from __future__ import annotations

import duckdb
from rich.console import Console

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# League-constants temp view (per (league_id, year, level_id))
#
# Materializes everything `compute_constants` from
# `diamond.advanced.league_constants` produces, but in pure SQL so the
# downstream JOINs stay set-based. Linear weights are the Fangraphs
# canonical base values scaled by `woba_scale`, where:
#
#   base_lg_woba = Σ(base_weights × lg counting) / (AB + nibb + SF + HBP)
#   woba_scale   = lg_obp / base_lg_woba
#   wX           = base_X × woba_scale
#
# By construction this makes lg_woba == lg_obp — convenient for sanity
# checks and matches the implementation in `advanced/league_constants.py`.
# ─────────────────────────────────────────────────────────────────────────────


# Fangraphs base linear weights — pre-scaling. Constants across leagues.
_BASE_W_BB = 0.69
_BASE_W_HBP = 0.72
_BASE_W_1B = 0.89
_BASE_W_2B = 1.27
_BASE_W_3B = 1.62
_BASE_W_HR = 2.10


# Native view — sources from `league_history_*_event` (the OOTP-native
# per-(league_id, year, level_id) aggregates) for completed seasons, with
# an in-progress fallback that aggregates from `f_player_season_*` for any
# (league_id, year, level_id) NOT present in the league_history rollups.
#
# Why the fallback exists: OOTP only writes `league_history_*_stats.csv`
# rows for completed seasons (the post-season writeback step). Mid-season
# dumps therefore lack rollup rows for the active year — e.g. a July 2028
# dump has zero MLB rows in `league_history_batting_event` for year=2028,
# even though every MLB player has 2028 stats on `players_career_*_stats`.
# Without this fallback, the entire in-progress year's wOBA/wRC+/OPS+/FIP/
# ERA+ stack comes out NULL — see the symptoms in `docs/DATA_NOTES.md`
# "In-progress season league constants".
#
# Both sources are scope-filtered identically: league_history_*_event uses
# _SCOPE_LEAGUE_HARDCODED_15; f_player_season_* is sourced from
# players_career_*_event which uses _SCOPE_PLAYER (which itself is gated to
# scoped teams + ≥1 MLB appearance). The fallback uses split_id=1 (overall)
# only — sub-splits would double-count.
_LG_CONSTANTS_NATIVE_VIEW_SQL = f"""
CREATE OR REPLACE VIEW _lg_constants_advanced_native AS
WITH agg_bat_history AS (
    SELECT
        league_id, year, level_id,
        SUM(pa)::DOUBLE  AS lg_pa,
        SUM(ab)::DOUBLE  AS lg_ab,
        SUM(h)::DOUBLE   AS lg_h,
        SUM(d)::DOUBLE   AS lg_d,
        SUM(t)::DOUBLE   AS lg_t,
        SUM(hr)::DOUBLE  AS lg_hr,
        SUM(bb)::DOUBLE  AS lg_bb,
        SUM(ibb)::DOUBLE AS lg_ibb,
        SUM(hp)::DOUBLE  AS lg_hp,
        SUM(sf)::DOUBLE  AS lg_sf,
        SUM(r)::DOUBLE   AS lg_r,
        (SUM(h) - SUM(d) - SUM(t) - SUM(hr))::DOUBLE AS lg_singles
    FROM league_history_batting_event
    GROUP BY league_id, year, level_id
),
agg_bat_fallback AS (
    -- In-progress fallback: aggregate from latest-dump player totals when
    -- league_history hasn't been written yet. f_player_season_batting is
    -- already dump-deduplicated (L1 picks MAX(dump_date) per natural key).
    --
    -- Year filter is critical: this fallback fires ONLY for years that
    -- already have SOME league_history coverage (i.e. the in-save scope).
    -- Pre-save years (Lahman/BREF-imported player rows) have no
    -- league_history rows at all, and their constants come from
    -- `_lg_constants_advanced_imported` (lref_era_stats-backed). Without
    -- the year filter, this CTE would aggregate imported pre-save player
    -- rows into a "native" row and displace the imported source — values
    -- would be nearly identical (both Lahman-sourced), but the precedence
    -- swap would be undocumented and could mask drift if Lahman ↔ OOTP
    -- import-shape ever diverges.
    SELECT
        league_id, year, level_id,
        SUM(pa)::DOUBLE  AS lg_pa,
        SUM(ab)::DOUBLE  AS lg_ab,
        SUM(h)::DOUBLE   AS lg_h,
        SUM(d)::DOUBLE   AS lg_d,
        SUM(t)::DOUBLE   AS lg_t,
        SUM(hr)::DOUBLE  AS lg_hr,
        SUM(bb)::DOUBLE  AS lg_bb,
        SUM(ibb)::DOUBLE AS lg_ibb,
        SUM(hp)::DOUBLE  AS lg_hp,
        SUM(sf)::DOUBLE  AS lg_sf,
        SUM(r)::DOUBLE   AS lg_r,
        (SUM(h) - SUM(d) - SUM(t) - SUM(hr))::DOUBLE AS lg_singles
    FROM f_player_season_batting
    WHERE split_id = 1
      AND year IN (SELECT DISTINCT year FROM league_history_batting_event)
      AND (league_id, year, level_id) NOT IN (
          SELECT DISTINCT league_id, year, level_id
          FROM league_history_batting_event
      )
    GROUP BY league_id, year, level_id
),
agg_bat AS (
    SELECT * FROM agg_bat_history
    UNION ALL
    SELECT * FROM agg_bat_fallback
),
agg_pit_history AS (
    -- league_history_pitching has ip + ipf (full innings + frac outs);
    -- collapse to total outs to match the player-side outs convention.
    SELECT
        league_id, year, level_id,
        (SUM(ip) * 3.0 + SUM(ipf))::DOUBLE AS lg_outs,
        SUM(er)::DOUBLE                    AS lg_er,
        SUM(hra)::DOUBLE                   AS lg_hra,
        SUM(bb)::DOUBLE                    AS lg_pit_bb,
        SUM(hp)::DOUBLE                    AS lg_pit_hp,
        SUM(k)::DOUBLE                     AS lg_pit_k
    FROM league_history_pitching_event
    GROUP BY league_id, year, level_id
),
agg_pit_fallback AS (
    -- Mirror agg_bat_fallback: aggregate from f_player_season_pitching for
    -- (league, year, level) combos not in league_history_pitching_event.
    -- `outs` is pre-computed in f_player_season_pitching as ip*3 + ipf.
    -- Same year-filter rationale as agg_bat_fallback above.
    SELECT
        league_id, year, level_id,
        SUM(outs)::DOUBLE AS lg_outs,
        SUM(er)::DOUBLE   AS lg_er,
        SUM(hra)::DOUBLE  AS lg_hra,
        SUM(bb)::DOUBLE   AS lg_pit_bb,
        SUM(hp)::DOUBLE   AS lg_pit_hp,
        SUM(k)::DOUBLE    AS lg_pit_k
    FROM f_player_season_pitching
    WHERE split_id = 1
      AND year IN (SELECT DISTINCT year FROM league_history_pitching_event)
      AND (league_id, year, level_id) NOT IN (
          SELECT DISTINCT league_id, year, level_id
          FROM league_history_pitching_event
      )
    GROUP BY league_id, year, level_id
),
agg_pit AS (
    SELECT * FROM agg_pit_history
    UNION ALL
    SELECT * FROM agg_pit_fallback
),
joined AS (
    SELECT
        b.league_id, b.year, b.level_id,
        b.lg_pa, b.lg_ab, b.lg_h, b.lg_d, b.lg_t, b.lg_hr,
        b.lg_bb, b.lg_ibb, b.lg_hp, b.lg_sf, b.lg_r, b.lg_singles,
        COALESCE(p.lg_outs, 0.0)   AS lg_outs,
        COALESCE(p.lg_er,   0.0)   AS lg_er,
        COALESCE(p.lg_hra,  0.0)   AS lg_hra,
        COALESCE(p.lg_pit_bb, 0.0) AS lg_pit_bb,
        COALESCE(p.lg_pit_hp, 0.0) AS lg_pit_hp,
        COALESCE(p.lg_pit_k,  0.0) AS lg_pit_k
    FROM agg_bat b
    LEFT JOIN agg_pit p USING (league_id, year, level_id)
),
derived AS (
    SELECT *,
        -- Slash-line league rates (recomputed from totals — mirrors lg_constants_bat)
        (lg_h + lg_bb + lg_hp) / NULLIF(lg_ab + lg_bb + lg_hp + lg_sf, 0) AS lg_obp,
        (lg_singles + 2*lg_d + 3*lg_t + 4*lg_hr) / NULLIF(lg_ab, 0)         AS lg_slg,
        -- IP and ERA
        lg_outs / 3.0 AS lg_ip,
        9.0 * lg_er / NULLIF(lg_outs / 3.0, 0) AS lg_era,
        -- Per-PA run environment
        lg_r / NULLIF(lg_pa, 0) AS runs_per_pa,
        -- nibb (non-intentional walks)
        (lg_bb - lg_ibb) AS lg_nibb,
        -- Base wOBA numerator + denominator (pre-scaling)
        ({_BASE_W_BB} * (lg_bb - lg_ibb)
         + {_BASE_W_HBP} * lg_hp
         + {_BASE_W_1B}  * lg_singles
         + {_BASE_W_2B}  * lg_d
         + {_BASE_W_3B}  * lg_t
         + {_BASE_W_HR}  * lg_hr) AS base_woba_num,
        -- PA-in-denominator per OOTP-canonical wOBA formula (D38). Player-side
        -- player_woba/PA matches OOTP's IE value; lg_woba derived here must
        -- use the same denominator for woba_scale to calibrate correctly.
        lg_pa AS woba_denom
    FROM joined
),
scaled AS (
    SELECT *,
        base_woba_num / NULLIF(woba_denom, 0) AS base_lg_woba
    FROM derived
)
SELECT
    league_id, year, level_id,
    lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
    lg_bb, lg_ibb, lg_hp, lg_sf, lg_r, lg_singles, lg_nibb,
    lg_outs, lg_er, lg_hra, lg_pit_bb, lg_pit_hp, lg_pit_k,
    lg_ip, lg_era, lg_obp, lg_slg, runs_per_pa,
    -- D38: wOBA uses BASE weights with PA denominator (OOTP-canonical).
    -- The scaled weights below are retained for backward-compat with any
    -- consumer that still needs lg-OBP-scaled values, but player_woba in
    -- f_player_season_advanced_batting uses BASE weights directly.
    -- woba_scale stays as lg_obp/base_lg_woba for downstream wRAA-style
    -- conversions; it just doesn't appear in the player_woba formula anymore.
    lg_obp / NULLIF(base_lg_woba, 0) AS woba_scale,
    {_BASE_W_BB}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_bb,
    {_BASE_W_HBP} * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hbp,
    {_BASE_W_1B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_1b,
    {_BASE_W_2B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_2b,
    {_BASE_W_3B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_3b,
    {_BASE_W_HR}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hr,
    -- League wOBA — base weights × counting / lg_pa (matches what
    -- OOTP reports in league_history_batting_stats.woba — verified
    -- 2026-05-10 against MLB 2027 OOTP-supplied .3176 ≈ derived .3202).
    base_lg_woba AS lg_woba,
    -- FIP constant — calibrates so league FIP == league ERA
    lg_era - (13.0 * lg_hra + 3.0 * (lg_pit_bb + lg_pit_hp) - 2.0 * lg_pit_k) / NULLIF(lg_ip, 0) AS fip_constant
FROM scaled
"""


# ─────────────────────────────────────────────────────────────────────────────
# Imported view — fills the pre-save MLB league baselines from real-history
# sources. Lahman 1871-2019 + BREF 2020-2025 cover MLB continuously up to
# the save start year. League_id is hardcoded to 203 (OOTP MLB) and
# level_id to 1 (top level). AL/NL sub-leagues (and pre-1900 NA/AA/PL/UA/FL)
# are summed into the parent MLB row, matching D11.
#
# Why this exists: OOTP imports pre-save player-seasons (Bonds 2001,
# Mantle 1956, etc.) but does NOT emit corresponding league_history rows,
# so without this UNION the advanced builders find no matching constants
# row and emit null wOBA / wRC+ / OPS+ / FIP / ERA+ for those player-
# seasons. Empirically Lahman aggregates and OOTP-imported player-row
# aggregates match exactly (Bonds 2001 NL: AB 87,946 = AB 87,946 etc.),
# since OOTP imports Lahman directly — so the constants are guaranteed
# self-consistent with the player rows that JOIN against them.
#
# Park factors are handled outside this view (in the dominant_team /
# park_lookup CTEs of the per-player builders). Pre-2026 OOTP player
# rows often join successfully to a current-day park (a 2001 Giants row
# resolves to Oracle Park's 1.003), which is a modern-stadium proxy for
# the historical context. Park-aware OPS+/ERA+ for pre-2026 thus uses
# the team's *current* park factor, not 2001-era. wOBA/wRC+/wRAA don't
# use park, so they're unaffected. Documented in DATA_NOTES.md.
#
# Lahman historical sparsity: IBB tracking starts 1955, SF starts 1954,
# HBP starts 1887, SH starts 1894, SO sparse pre-1913. Treated as 0
# for league aggregates (Fangraphs convention; OOTP imports zeros for
# these too, so player-rows + league-rows stay consistent).
_LG_CONSTANTS_IMPORTED_VIEW_SQL = f"""
CREATE OR REPLACE VIEW _lg_constants_advanced_imported AS
WITH
-- ── Slice 5 (MiLB pre-save baselines) ─────────────────────────────────────
-- Map save MiLB league_id → era_stats_minors League name. Names match
-- exactly between the save's `leagues.name` and the file's `League`
-- column for the 11 leagues with substantive Lahman MiLB coverage. The 3
-- save MiLB leagues without a match (DSL=234, ACL=217, FCL=218) have
-- essentially no pre-save Lahman data anyway — Complex/Rookie short-season
-- leagues. Hardcoded crosswalk because (a) names are stable, (b) the user's
-- save might use different league_ids per D3 v2.1 but the level/name pair
-- still resolves correctly via this lookup applied to the save's own data.
milb_xwalk(league_id, era_league) AS (
    VALUES
        -- AAA
        (204, 'International League'),
        (205, 'Pacific Coast League'),
        -- AA
        (206, 'Eastern League'),
        (207, 'Southern League'),
        (208, 'Texas League'),
        -- A+ / A
        (209, 'Northwest League'),
        (210, 'South Atlantic League'),
        (211, 'Midwest League'),
        (212, 'California League'),
        (213, 'Carolina League'),
        (252, 'Florida State League'),
        -- L7 independent (Phase 4a #3, 2026-05-10):
        -- American Association covers 1903-1997 (89 era rows; classic
        -- minor-league AA, NOT the modern indy league of same name —
        -- OOTP routes them by name so the join only fires for the
        -- historical pre-1998 seasons).
        (237, 'American Association'),
        -- Pioneer League 1939-2024 (83 era rows; was MiLB Rookie, now
        -- independent post-2021 reorg — covers both eras).
        (253, 'Pioneer League')
),
-- Resolve level_id from the save itself rather than hardcoding —
-- league_id is *usually* 1:1 with level_id, but the 2021 MiLB reorg
-- (Phase 4a #3 investigation, 2026-05-10) means several leagues appear
-- at BOTH levels in a single save: e.g., league_id=211 (Midwest) sits
-- at L6 for historical 2007-2019 rows and L4 for modern 2021-2028 rows
-- after OOTP's "rebrand to full-season A" classification. Using
-- MIN(level_id) would route every imported baseline to the lower
-- level, leaving the higher-level historical rows orphan (NULL OPS+).
-- Fan out instead — produce one row per (league_id, level_id) where
-- the league appears, so era_stats_minors data feeds every level the
-- league sits at across the save's history.
milb_levels_per_league AS (
    SELECT league_id, level_id
    FROM f_player_season_batting
    WHERE league_id IN (
        SELECT league_id FROM milb_xwalk
    )
    GROUP BY league_id, level_id
),
-- One JOINed row per (save_league_id, year). Derive the same column shape
-- as the MLB CTEs so we can UNION downstream. era_stats_minors carries
-- league-aggregate stats — pitcher-side HR-allowed equals batter-side HR
-- by identity (league total), so we reuse the same fields for both sides.
-- IBB is not in era_stats_minors → 0 (Lahman has the same gap pre-1955;
-- effect on woba_scale is sub-percent).
milb_joined AS (
    SELECT
        x.league_id,
        CAST(esm."Year" AS INTEGER) AS year,
        l.level_id,
        TRY_CAST(esm.BFP AS DOUBLE)      AS lg_pa,
        TRY_CAST(esm.AB AS DOUBLE)       AS lg_ab,
        TRY_CAST(esm.Hits AS DOUBLE)     AS lg_h,
        TRY_CAST(esm.Doubles AS DOUBLE)  AS lg_d,
        TRY_CAST(esm.Triples AS DOUBLE)  AS lg_t,
        TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_hr,
        TRY_CAST(esm.BB AS DOUBLE)       AS lg_bb,
        0.0::DOUBLE                      AS lg_ibb,
        TRY_CAST(esm.HBP AS DOUBLE)      AS lg_hp,
        -- SF recovered from rate × non-K-out denominator
        COALESCE(
            TRY_CAST(esm."SF/(IPouts-K)" AS DOUBLE)
                * (TRY_CAST(esm.IPouts AS DOUBLE) - TRY_CAST(esm.K AS DOUBLE)),
            0.0
        )                                AS lg_sf,
        -- Runs from R/27IPouts × IPouts / 27
        COALESCE(
            TRY_CAST(esm."Runs per 27 IPouts" AS DOUBLE)
                * TRY_CAST(esm.IPouts AS DOUBLE) / 27.0,
            0.0
        )                                AS lg_r,
        -- Singles by subtraction
        TRY_CAST(esm.Hits AS DOUBLE)
            - TRY_CAST(esm.Doubles AS DOUBLE)
            - TRY_CAST(esm.Triples AS DOUBLE)
            - TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_singles,
        TRY_CAST(esm.IPouts AS DOUBLE)   AS lg_outs,
        -- ER = ERA × innings / 9 = ERA × IPouts / 27
        COALESCE(
            TRY_CAST(esm.ERA AS DOUBLE) * TRY_CAST(esm.IPouts AS DOUBLE) / 27.0,
            0.0
        )                                AS lg_er,
        TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_hra,
        TRY_CAST(esm.BB AS DOUBLE)       AS lg_pit_bb,
        TRY_CAST(esm.HBP AS DOUBLE)      AS lg_pit_hp,
        TRY_CAST(esm.K AS DOUBLE)        AS lg_pit_k
    FROM milb_xwalk x
    JOIN lref_era_stats_minors esm
        ON esm."League" = x.era_league
    JOIN milb_levels_per_league l
        ON l.league_id = x.league_id
    WHERE TRY_CAST(esm."Year" AS INTEGER) IS NOT NULL
      AND TRY_CAST(esm.AB AS DOUBLE) > 0
),
-- ── MLB (Slice 4: lref_era_stats — OOTP-canonical, replaces Lahman+BREF UNION) ──
-- One row per (year) covering 1870-2025. Replaces the prior
-- lahman_bat + bref_bat + lahman_pit + bref_pit UNION pattern with a
-- single OOTP-blessed source. Same numerical answer — both Lahman and
-- OOTP era_stats trace to the same MLB-historical aggregates — but no
-- external fetch dependency, no UNION boundary at 2019/2020.
mlb_joined AS (
    SELECT
        203 AS league_id,
        CAST(esm."YEAR" AS INTEGER) AS year,
        1 AS level_id,
        TRY_CAST(esm.BFP AS DOUBLE)      AS lg_pa,
        TRY_CAST(esm.AB AS DOUBLE)       AS lg_ab,
        TRY_CAST(esm.Hits AS DOUBLE)     AS lg_h,
        TRY_CAST(esm.Doubles AS DOUBLE)  AS lg_d,
        TRY_CAST(esm.Triples AS DOUBLE)  AS lg_t,
        TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_hr,
        TRY_CAST(esm.BB AS DOUBLE)       AS lg_bb,
        COALESCE(TRY_CAST(esm.IBB AS DOUBLE), 0.0) AS lg_ibb,
        TRY_CAST(esm.HBP AS DOUBLE)      AS lg_hp,
        COALESCE(
            TRY_CAST(esm."SF/(IPouts-K)" AS DOUBLE)
                * (TRY_CAST(esm.IPouts AS DOUBLE) - TRY_CAST(esm.K AS DOUBLE)),
            0.0
        )                                AS lg_sf,
        COALESCE(
            TRY_CAST(esm."Runs per 27 IPouts" AS DOUBLE)
                * TRY_CAST(esm.IPouts AS DOUBLE) / 27.0,
            0.0
        )                                AS lg_r,
        TRY_CAST(esm.Hits AS DOUBLE)
            - TRY_CAST(esm.Doubles AS DOUBLE)
            - TRY_CAST(esm.Triples AS DOUBLE)
            - TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_singles,
        TRY_CAST(esm.IPouts AS DOUBLE)   AS lg_outs,
        COALESCE(
            TRY_CAST(esm.ERA AS DOUBLE) * TRY_CAST(esm.IPouts AS DOUBLE) / 27.0,
            0.0
        )                                AS lg_er,
        TRY_CAST(esm.Homeruns AS DOUBLE) AS lg_hra,
        TRY_CAST(esm.BB AS DOUBLE)       AS lg_pit_bb,
        TRY_CAST(esm.HBP AS DOUBLE)      AS lg_pit_hp,
        TRY_CAST(esm.K AS DOUBLE)        AS lg_pit_k
    FROM lref_era_stats esm
    WHERE TRY_CAST(esm."YEAR" AS INTEGER) IS NOT NULL
      AND TRY_CAST(esm.AB AS DOUBLE) > 0
      AND CAST(esm."YEAR" AS INTEGER) <= 2025  -- save years take over from 2026
),
joined AS (
    SELECT * FROM mlb_joined
    UNION ALL
    SELECT * FROM milb_joined
),
derived AS (
    SELECT *,
        (lg_h + lg_bb + lg_hp) / NULLIF(lg_ab + lg_bb + lg_hp + lg_sf, 0) AS lg_obp,
        (lg_singles + 2*lg_d + 3*lg_t + 4*lg_hr) / NULLIF(lg_ab, 0)         AS lg_slg,
        lg_outs / 3.0 AS lg_ip,
        9.0 * lg_er / NULLIF(lg_outs / 3.0, 0) AS lg_era,
        lg_r / NULLIF(lg_pa, 0) AS runs_per_pa,
        (lg_bb - lg_ibb) AS lg_nibb,
        ({_BASE_W_BB} * (lg_bb - lg_ibb)
         + {_BASE_W_HBP} * lg_hp
         + {_BASE_W_1B}  * lg_singles
         + {_BASE_W_2B}  * lg_d
         + {_BASE_W_3B}  * lg_t
         + {_BASE_W_HR}  * lg_hr) AS base_woba_num,
        -- PA-in-denominator per OOTP-canonical wOBA formula (D38). Player-side
        -- player_woba/PA matches OOTP's IE value; lg_woba derived here must
        -- use the same denominator for woba_scale to calibrate correctly.
        lg_pa AS woba_denom
    FROM joined
),
scaled AS (
    SELECT *,
        base_woba_num / NULLIF(woba_denom, 0) AS base_lg_woba
    FROM derived
)
SELECT
    league_id, year, level_id,
    lg_pa, lg_ab, lg_h, lg_d, lg_t, lg_hr,
    lg_bb, lg_ibb, lg_hp, lg_sf, lg_r, lg_singles, lg_nibb,
    lg_outs, lg_er, lg_hra, lg_pit_bb, lg_pit_hp, lg_pit_k,
    lg_ip, lg_era, lg_obp, lg_slg, runs_per_pa,
    lg_obp / NULLIF(base_lg_woba, 0) AS woba_scale,
    {_BASE_W_BB}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_bb,
    {_BASE_W_HBP} * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hbp,
    {_BASE_W_1B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_1b,
    {_BASE_W_2B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_2b,
    {_BASE_W_3B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_3b,
    {_BASE_W_HR}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hr,
    -- D38: base-weight × lg_pa-denom league wOBA (matches OOTP-supplied).
    base_lg_woba AS lg_woba,
    lg_era - (13.0 * lg_hra + 3.0 * (lg_pit_bb + lg_pit_hp) - 2.0 * lg_pit_k) / NULLIF(lg_ip, 0) AS fip_constant
FROM scaled
"""


# Final consumer-facing view — UNION of native (save) + imported (real history).
# Key uniqueness: native rows are always (league_id, year≥save_start, *) and
# imported rows are always (203, year≤2025, 1), so no overlap. If the save
# start ever migrates back into 2025 or earlier, the UNION ALL would emit
# duplicates and downstream LEFT JOINs would amplify rows — guard against
# this by keeping `history_*` tables scoped to year < save_start in the
# fetch_history loader (already enforced by `MAX_HISTORY_YEAR = save_start - 1`).
_LG_CONSTANTS_VIEW_SQL = """
CREATE OR REPLACE VIEW _lg_constants_advanced AS
SELECT * FROM _lg_constants_advanced_native
UNION ALL
SELECT * FROM _lg_constants_advanced_imported
WHERE NOT EXISTS (
    SELECT 1 FROM _lg_constants_advanced_native n
    WHERE n.league_id = _lg_constants_advanced_imported.league_id
      AND n.year      = _lg_constants_advanced_imported.year
      AND n.level_id  = _lg_constants_advanced_imported.level_id
)
"""


# Replacement-level + runs-per-win constants, mirrored from
# `diamond.advanced.sabermetric` so the materialized values match the
# audit's computed numbers exactly. Update both places together.
_REPL_WRAA_PER_PA = 20.0 / 600.0
_RUNS_PER_WIN = 10.0
_REPL_FIP_MULT = 1.13


# ─────────────────────────────────────────────────────────────────────────────
# Park-factor lookup
#
# Per-stint home park varies — a player traded mid-season has different
# parks for each stint. For per-(year, league, level) advanced rows we
# pick the team where the player accumulated the most PA (batting) or
# outs (pitching) at that level, and use that team's park factor.
# Players with no team mapping default to park_avg=1.0 (no adjustment),
# matching the convention in `sabermetric.ops_plus_per_player`.
#
# `_park_factor_resolved` (D22) is a (team_id, year) view that backfills
# historical park factors for OOTP-imported pre-save MLB seasons via
# Lahman's per-team `BPF` / `PPF` columns (100-relative; we divide by
# 100 to match OOTP's 1.0-relative `parks.avg` convention). For 2026+
# (save-native) and 2020-2025 (BREF era — Lahman doesn't extend that
# far, BREF doesn't ship park factors per-team in our scrape) we fall
# back to the OOTP team's current-day `parks.avg`. Net effect: Bonds
# 2001 SF Giants gets BPF 0.93 (2001 NL pitcher's park) instead of
# Oracle Park's modern 1.003, fixing the modern-stadium proxy bias on
# pre-save OPS+/ERA+. wOBA/wRC+/wRAA are unaffected (they don't use
# park).
#
# OOTP↔Lahman crosswalk is hardcoded for the 30 modern MLB clubs by
# (team_id, franchID) — franchID is stable through historical team
# renames (e.g., 'BAL' covers St Louis Browns 1902-1953 + Baltimore
# Orioles 1954-present), which is the right granularity for a
# franchise-as-stadium proxy. Defunct historical franchises (Brooklyn
# Robins, Boston Beaneaters, etc.) won't have OOTP team_id rows in
# pre-save player data — those player-rows fall through to
# park_avg=1.0, same as today.
# ─────────────────────────────────────────────────────────────────────────────


# `_park_factor_resolved` view — backfills historical Lahman BPF/PPF
# for ≤2019 MLB seasons; falls back to current `parks.avg` otherwise.
# Depends on `history_lahman_teams` — registered conditionally inside
# `build_l3_advanced` (no-op fallback view if `fetch-history` hasn't run).
_PARK_FACTOR_RESOLVED_VIEW_SQL = """
CREATE OR REPLACE VIEW _park_factor_resolved AS
WITH ootp_franchise_xwalk(team_id, lahman_franch_id) AS (
    VALUES
      (1,  'ARI'), (2,  'ATL'), (3,  'BAL'), (4,  'BOS'), (5,  'CHW'),
      (6,  'CHC'), (7,  'CIN'), (8,  'CLE'), (9,  'COL'), (10, 'DET'),
      (11, 'FLA'), (12, 'HOU'), (13, 'KCR'), (14, 'ANA'), (15, 'LAD'),
      (16, 'MIL'), (17, 'MIN'), (18, 'NYY'), (19, 'NYM'), (20, 'OAK'),
      (21, 'PHI'), (22, 'PIT'), (23, 'SDP'), (24, 'SEA'), (25, 'SFG'),
      (26, 'STL'), (27, 'TBD'), (28, 'TEX'), (29, 'TOR'), (30, 'WSN')
),
historical AS (
    -- Slice 3: lref_era_ballparks (1871-2025, 3,105 park-seasons) replaces
    -- history_lahman_teams. Adds LH/RH split factors that Lahman BPF/PPF
    -- doesn't carry. Values are stored as `BA Overall` (composite batting
    -- factor centered on 1.000) — reuse for both bat and pit park_avg
    -- (era_ballparks doesn't separate BPF vs PPF; the difference in
    -- Lahman was usually < 0.02 anyway, well within noise for our use).
    SELECT
        x.team_id,
        CAST(eb.yearID AS INTEGER) AS year,
        TRY_CAST(eb."BA Overall" AS DOUBLE) AS bat_park_avg,
        TRY_CAST(eb."BA Overall" AS DOUBLE) AS pit_park_avg,
        TRY_CAST(eb."BA LH"      AS DOUBLE) AS bat_park_avg_lh,
        TRY_CAST(eb."BA RH"      AS DOUBLE) AS bat_park_avg_rh,
        TRY_CAST(eb."BA LH"      AS DOUBLE) AS pit_park_avg_lh,
        TRY_CAST(eb."BA RH"      AS DOUBLE) AS pit_park_avg_rh
    FROM lref_era_ballparks eb
    INNER JOIN ootp_franchise_xwalk x ON x.lahman_franch_id = eb.franchID
    WHERE TRY_CAST(eb."BA Overall" AS DOUBLE) IS NOT NULL
),
seen_pairs AS (
    SELECT team_id, year FROM f_player_season_batting WHERE level_id = 1 AND split_id = 1
    UNION
    SELECT team_id, year FROM f_player_season_pitching WHERE level_id = 1 AND split_id = 1
),
modern AS (
    -- Save-era rows (≥ 2026) where era_ballparks doesn't yet have data.
    -- Falls through to the engine's current `parks.avg` value. No
    -- handedness data available — splits collapse to Overall.
    SELECT
        s.team_id,
        s.year,
        COALESCE(prk.avg, 1.0) AS bat_park_avg,
        COALESCE(prk.avg, 1.0) AS pit_park_avg,
        COALESCE(prk.avg, 1.0) AS bat_park_avg_lh,
        COALESCE(prk.avg, 1.0) AS bat_park_avg_rh,
        COALESCE(prk.avg, 1.0) AS pit_park_avg_lh,
        COALESCE(prk.avg, 1.0) AS pit_park_avg_rh
    FROM seen_pairs s
    LEFT JOIN teams t   ON t.team_id  = s.team_id
    LEFT JOIN parks prk ON prk.park_id = t.park_id
)
SELECT team_id, year,
       bat_park_avg, pit_park_avg,
       bat_park_avg_lh, bat_park_avg_rh,
       pit_park_avg_lh, pit_park_avg_rh,
       'lref_era' AS src
FROM historical
UNION ALL
SELECT m.team_id, m.year,
       m.bat_park_avg, m.pit_park_avg,
       m.bat_park_avg_lh, m.bat_park_avg_rh,
       m.pit_park_avg_lh, m.pit_park_avg_rh,
       'modern' AS src
FROM modern m
WHERE NOT EXISTS (
    SELECT 1 FROM historical h
    WHERE h.team_id = m.team_id AND h.year = m.year
)
"""


# Fallback when `lref_era_ballparks` doesn't exist (pre-Slice-1 save).
# Just exposes the modern teams.parks lookup with the same shape.
_PARK_FACTOR_RESOLVED_FALLBACK_SQL = """
CREATE OR REPLACE VIEW _park_factor_resolved AS
WITH seen_pairs AS (
    SELECT team_id, year FROM f_player_season_batting WHERE level_id = 1 AND split_id = 1
    UNION
    SELECT team_id, year FROM f_player_season_pitching WHERE level_id = 1 AND split_id = 1
)
SELECT
    s.team_id,
    s.year,
    COALESCE(prk.avg, 1.0) AS bat_park_avg,
    COALESCE(prk.avg, 1.0) AS pit_park_avg,
    COALESCE(prk.avg, 1.0) AS bat_park_avg_lh,
    COALESCE(prk.avg, 1.0) AS bat_park_avg_rh,
    COALESCE(prk.avg, 1.0) AS pit_park_avg_lh,
    COALESCE(prk.avg, 1.0) AS pit_park_avg_rh,
    'modern' AS src
FROM seen_pairs s
LEFT JOIN teams t   ON t.team_id  = s.team_id
LEFT JOIN parks prk ON prk.park_id = t.park_id
"""


def _build_f_player_season_advanced_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, league_id, level_id) batting advanced stats.

    Computed:
      pa, woba, wraa, wrc, wrc_plus, ops_plus, o_war, b_war, park_avg

    Filters: ``split_id = 1`` (overall split — vs LHP / vs RHP would
    double-count). Output is the natural unit for headline rate stats —
    cross-level rollups aren't included since league constants differ.

    ``b_war`` is OOTP's directly-supplied WAR field (summed across
    stints). It includes defensive runs (zr + framing + arm) +
    positional adjustment + baserunning + leverage; reconciles to IE
    WAR as A-tier. ``o_war`` is Diamond's offense-only formula and is
    kept for transparency + glossary cross-reference.
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_advanced_batting AS
        WITH agg AS (
            SELECT
                player_id, year, league_id, level_id,
                SUM(pa)::DOUBLE  AS pa,
                SUM(ab)::DOUBLE  AS ab,
                SUM(h)::DOUBLE   AS h,
                SUM(d)::DOUBLE   AS d,
                SUM(t)::DOUBLE   AS t,
                SUM(hr)::DOUBLE  AS hr,
                SUM(bb)::DOUBLE  AS bb,
                SUM(ibb)::DOUBLE AS ibb,
                SUM(hp)::DOUBLE  AS hp,
                SUM(sf)::DOUBLE  AS sf,
                SUM(war)::DOUBLE AS b_war_raw,
                (SUM(h) - SUM(d) - SUM(t) - SUM(hr))::DOUBLE AS singles,
                (SUM(bb) - SUM(ibb))::DOUBLE                 AS nibb
            FROM f_player_season_batting
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        ),
        -- Pick the team where the player took the most PA at this level.
        -- Ties broken by ascending team_id for stability.
        dominant_team AS (
            SELECT player_id, year, league_id, level_id, team_id
            FROM (
                SELECT player_id, year, league_id, level_id, team_id, pa,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_id, year, league_id, level_id
                           ORDER BY pa DESC, team_id ASC
                       ) AS rn
                FROM f_player_season_batting
                WHERE split_id = 1
            ) WHERE rn = 1
        ),
        park_lookup AS (
            -- Slice 3 (D22 v2): handedness-aware batter park factor.
            --   bats=1 (R) → bat_park_avg_rh
            --   bats=2 (L) → bat_park_avg_lh
            --   bats=3 (S) → 60/40 blend (60% facing RHP / 40% LHP, batting
            --                              from opposite side per Tango)
            -- Falls back to Overall on any null + final 1.0 backstop for
            -- defunct franchises / unmapped teams. Modern (≥ 2026) save
            -- rows have splits == Overall (engine doesn't carry handedness),
            -- so the CASE collapses to the same value.
            SELECT d.player_id, d.year, d.league_id, d.level_id,
                   COALESCE(
                       CASE
                           WHEN pl.bats = 2 THEN
                               COALESCE(pfr.bat_park_avg_lh, pfr.bat_park_avg)
                           WHEN pl.bats = 1 THEN
                               COALESCE(pfr.bat_park_avg_rh, pfr.bat_park_avg)
                           WHEN pl.bats = 3 THEN
                               0.6 * COALESCE(pfr.bat_park_avg_rh, pfr.bat_park_avg)
                               + 0.4 * COALESCE(pfr.bat_park_avg_lh, pfr.bat_park_avg)
                           ELSE pfr.bat_park_avg
                       END,
                       1.0
                   ) AS park_avg
            FROM dominant_team d
            LEFT JOIN players_current pl ON pl.player_id = d.player_id
            LEFT JOIN _park_factor_resolved pfr
                   ON pfr.team_id = d.team_id AND pfr.year = d.year
        ),
        joined AS (
            SELECT
                a.*,
                lc.lg_obp, lc.lg_slg, lc.lg_woba, lc.woba_scale, lc.runs_per_pa,
                lc.w_bb, lc.w_hbp, lc.w_1b, lc.w_2b, lc.w_3b, lc.w_hr,
                COALESCE(pl.park_avg, 1.0) AS park_avg
            FROM agg a
            LEFT JOIN _lg_constants_advanced lc USING (league_id, year, level_id)
            LEFT JOIN park_lookup pl USING (player_id, year, league_id, level_id)
        ),
        woba_calc AS (
            SELECT *,
                -- OOTP-canonical wOBA (D38): BASE linear weights with PA in
                -- the denominator. Two corrections from FanGraphs convention:
                --   (1) PA denominator, not (AB + uBB + SF + HBP)
                --   (2) BASE weights, not lg-OBP-scaled weights
                -- Verified empirically against IE export — Bastidas 2028
                -- IE=.357 matches base × PA-denom = .356 (within rounding).
                -- The previous lg-OBP-scaled approach forced lg_woba = lg_obp
                -- by construction; OOTP doesn't enforce that relationship.
                (
                    {_BASE_W_BB}  * nibb
                  + {_BASE_W_HBP} * hp
                  + {_BASE_W_1B}  * singles
                  + {_BASE_W_2B}  * d
                  + {_BASE_W_3B}  * t
                  + {_BASE_W_HR}  * hr
                ) / NULLIF(pa, 0) AS player_woba,
                -- Slash-line for OPS+
                (h + bb + hp) / NULLIF(ab + bb + hp + sf, 0) AS player_obp,
                (singles + 2*d + 3*t + 4*hr) / NULLIF(ab, 0)  AS player_slg
            FROM joined
        )
        SELECT
            player_id, year, league_id, level_id,
            CAST(pa AS BIGINT) AS pa,
            ROUND(player_woba, 4) AS woba,
            ROUND((player_woba - lg_woba) / NULLIF(woba_scale, 0) * pa, 1) AS wraa,
            ROUND(((player_woba - lg_woba) / NULLIF(woba_scale, 0) + runs_per_pa) * pa, 1) AS wrc,
            CAST(ROUND(
                100.0 * (
                    ((player_woba - lg_woba) / NULLIF(woba_scale, 0) + runs_per_pa)
                    / NULLIF(runs_per_pa, 0)
                ), 0
            ) AS INTEGER) AS wrc_plus,
            CAST(ROUND(
                100.0 * (player_obp / NULLIF(lg_obp, 0)
                         + player_slg / NULLIF(lg_slg, 0) - 1)
                / NULLIF(1.0 + (park_avg - 1.0) / 2.0, 0),
                0
            ) AS INTEGER) AS ops_plus,
            ROUND(
                ((player_woba - lg_woba) / NULLIF(woba_scale, 0) * pa
                 + {_REPL_WRAA_PER_PA} * pa) / {_RUNS_PER_WIN},
                1
            ) AS o_war,
            ROUND(b_war_raw, 1) AS b_war,
            ROUND(park_avg, 3) AS park_avg
        FROM woba_calc
        WHERE pa > 0
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_advanced_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_advanced_batting"
    ).fetchone()[0]


def _build_f_player_season_advanced_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(player, year, league_id, level_id) pitching advanced stats.

    Computed:
      outs, ip_display, fip, siera, era_plus, pit_war, p_war,
      p_ra9_war, park_avg

    Filters: ``split_id = 1``. Park factor is the dominant-team's park
    (most outs at this level). Quality threshold: outs >= 30 (10 IP) —
    matches the audit's `era_plus_per_pitcher` filter so headline values
    line up with the audit's IE-reconciled numbers.

    ``p_war`` is OOTP's directly-supplied FIP-WAR (summed across
    stints). It includes leverage adjustment for relievers and
    OOTP's own replacement-level scaling, which differs from our flat
    1.13 multiplier — values run ~1.5-2 wins higher than ``pit_war``
    for top starters. Reconciles to IE WAR as A-tier (audit tolerance
    0.15). ``p_ra9_war`` is the parallel RA9-based WAR — tracks actual
    runs allowed, sensitive to defense + sequencing.

    SIERA formula (Fangraphs canonical) — verified against IE 2026-05-04
    in `audit/reconcile.py`: Crochet 2.25 vs IE 2.27, 96/101 within ±0.1
    across MLB-only Sox. Inputs are K / BB / BF / GB / FB. SIERA is null
    when BF is zero (defensive — shouldn't happen given the outs ≥ 30
    quality bar).
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_advanced_pitching AS
        WITH agg AS (
            SELECT
                player_id, year, league_id, level_id,
                SUM(outs)::DOUBLE AS outs,
                SUM(er)::DOUBLE   AS er,
                SUM(hra)::DOUBLE  AS hra,
                SUM(bb)::DOUBLE   AS bb,
                SUM(hp)::DOUBLE   AS hp,
                SUM(k)::DOUBLE    AS k,
                SUM(bf)::DOUBLE   AS bf,
                SUM(gb)::DOUBLE   AS gb,
                SUM(fb)::DOUBLE   AS fb,
                SUM(war)::DOUBLE     AS p_war_raw,
                SUM(ra9war)::DOUBLE  AS p_ra9_war_raw
            FROM f_player_season_pitching
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        ),
        dominant_team AS (
            SELECT player_id, year, league_id, level_id, team_id
            FROM (
                SELECT player_id, year, league_id, level_id, team_id, outs,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_id, year, league_id, level_id
                           ORDER BY outs DESC, team_id ASC
                       ) AS rn
                FROM f_player_season_pitching
                WHERE split_id = 1
            ) WHERE rn = 1
        ),
        park_lookup AS (
            -- D22: prefer Lahman historical PPF for pre-2020 MLB seasons,
            -- fall back to modern teams.parks.avg via _park_factor_resolved.
            SELECT d.player_id, d.year, d.league_id, d.level_id,
                   COALESCE(pfr.pit_park_avg, 1.0) AS park_avg
            FROM dominant_team d
            LEFT JOIN _park_factor_resolved pfr
                   ON pfr.team_id = d.team_id AND pfr.year = d.year
        ),
        joined AS (
            SELECT
                a.*,
                lc.lg_era, lc.fip_constant,
                COALESCE(pl.park_avg, 1.0) AS park_avg
            FROM agg a
            LEFT JOIN _lg_constants_advanced lc USING (league_id, year, level_id)
            LEFT JOIN park_lookup pl USING (player_id, year, league_id, level_id)
        ),
        rates AS (
            SELECT *,
                outs / 3.0 AS ip,
                9.0 * er / NULLIF(outs / 3.0, 0) AS player_era,
                (13.0 * hra + 3.0 * (bb + hp) - 2.0 * k) / NULLIF(outs / 3.0, 0)
                    + fip_constant AS player_fip
            FROM joined
        )
        SELECT
            player_id, year, league_id, level_id,
            CAST(outs AS BIGINT) AS outs,
            ROUND(FLOOR(outs / 3.0) + ((CAST(outs AS BIGINT) % 3)) * 0.1, 1) AS ip_display,
            ROUND(player_fip, 2) AS fip,
            -- SIERA — Fangraphs canonical regression. Null when BF=0
            -- (defensive guard; the outs >= 30 filter rules this out
            -- in practice).
            CASE WHEN bf = 0 THEN NULL ELSE
                ROUND(
                    6.145
                    - 16.986 * (k / bf)
                    + 11.434 * (bb / bf)
                    - 1.858  * ((gb - fb) / bf)
                    + 7.653  * POWER(k / bf, 2)
                    - 6.664  * POWER((gb - fb) / bf, 2)
                    + 10.130 * (k / bf) * ((gb - fb) / bf)
                    - 5.195  * (bb / bf) * ((gb - fb) / bf),
                    2
                )
            END AS siera,
            CAST(ROUND(
                100.0 * lg_era / NULLIF(player_era, 0)
                * (1.0 + (park_avg - 1.0) * 0.8),
                0
            ) AS INTEGER) AS era_plus,
            ROUND(
                ((lg_era * {_REPL_FIP_MULT}) - player_fip) * (outs / 3.0) / 9.0
                / {_RUNS_PER_WIN},
                1
            ) AS pit_war,
            ROUND(p_war_raw, 1)     AS p_war,
            ROUND(p_ra9_war_raw, 1) AS p_ra9_war,
            ROUND(park_avg, 3) AS park_avg
        FROM rates
        WHERE outs >= 30   -- 10+ IP minimum, matches audit threshold
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_advanced_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_advanced_pitching"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Statcast cohort — per-(player, year, league, level) batted-ball quality
#
# OOTP per-PA logs carry both ``exit_velo`` and ``launch_angle`` populated
# 100% on BIP rows (verified in audit notes 2026-05-09 — 573,958 BIP rows
# in f_pa_event, 0 nulls). That's enough to materialize the canonical
# Statcast cohort at the same grain as the rest of the advanced stack:
#
#   - **bip**            BIP count (rows with bip_flag=1)
#   - **max_ev**         90th-percentile EV (Statcast convention; not the
#                        absolute max, which is dominated by single-event noise)
#   - **avg_ev**         Mean EV across all BIP
#   - **hard_hit_pct**   % of BIP with EV ≥ 95 mph
#   - **sweet_spot_pct** % of BIP with LA ∈ [8°, 32°]
#   - **barrel_pct**     % of BIP meeting Statcast's expanding-window barrel
#                        definition: EV ≥ 98 AND LA ∈ [GREATEST(8, 26-(EV-98)),
#                        LEAST(50, 30+(EV-98))]
#
# Two tables — ``f_player_season_statcast_batting`` (cohort the player
# generated as a hitter) and ``_statcast_pitching`` (cohort the player
# allowed as a pitcher). Same grain as the sabermetric tables: per
# (player_id, year, league_id, level_id).
#
# Quality threshold: BIP ≥ 30 — small samples produce noisy percentages
# and an unstable max_ev quantile. Matches the spirit of the audit's
# minimum-PA filter on the rest of the advanced stack.
# ─────────────────────────────────────────────────────────────────────────────


_STATCAST_BARREL_EXPR = """
    -- Statcast expanding-window barrel definition. EV >= 98 is the
    -- floor; the LA window widens as EV climbs, capping at [8, 50].
    CASE WHEN bip_flag = 1 AND exit_velo >= 98
              AND launch_angle >= GREATEST(8.0, 26.0 - (exit_velo - 98.0))
              AND launch_angle <= LEAST(50.0, 30.0 + (exit_velo - 98.0))
         THEN 1 ELSE 0 END
"""


def _build_f_player_season_statcast_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(batter, year, league, level) Statcast cohort.

    Aggregates ``f_pa_event`` by ``batter_id`` (note: not ``player_id``;
    f_pa_event keys hitters and pitchers distinctly). Writes the same
    six cohort columns the audit's `diamond.advanced.contact` exposes,
    rounded to one decimal where percentages and 90th-percentile EV.
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_statcast_batting AS
        WITH agg AS (
            SELECT
                batter_id        AS player_id,
                year, league_id, level_id,
                COUNT(*) FILTER (WHERE bip_flag = 1)                       AS bip,
                ROUND(QUANTILE_CONT(exit_velo, 0.90)
                    FILTER (WHERE bip_flag = 1 AND exit_velo > 0), 1)      AS max_ev,
                ROUND(AVG(exit_velo) FILTER (WHERE bip_flag = 1), 1)       AS avg_ev,
                ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag = 1 AND exit_velo >= 95)
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS hard_hit_pct,
                ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag = 1
                                            AND launch_angle BETWEEN 8 AND 32)
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS sweet_spot_pct,
                ROUND(100.0 * SUM({_STATCAST_BARREL_EXPR})
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS barrel_pct
            FROM f_pa_event
            WHERE game_type = 0                  -- D39: reg-season only (IE convention)
            GROUP BY batter_id, year, league_id, level_id
        )
        SELECT * FROM agg
        WHERE bip >= 30
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_statcast_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_statcast_batting"
    ).fetchone()[0]


def _build_f_player_season_statcast_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(pitcher, year, league, level) allowed-contact Statcast cohort.

    Mirrors the batting builder but aggregates by ``pitcher_id`` instead.
    Conceptually: "what kind of contact did this pitcher allow?"
    Useful for separating BABIP/sequencing-fueled ERA noise from
    quality-of-contact pitch outcomes — pairs with FIP / SIERA on the
    pitcher advanced view.
    """
    sql = f"""
        CREATE OR REPLACE TABLE f_player_season_statcast_pitching AS
        WITH agg AS (
            SELECT
                pitcher_id       AS player_id,
                year, league_id, level_id,
                COUNT(*) FILTER (WHERE bip_flag = 1)                       AS bip,
                ROUND(QUANTILE_CONT(exit_velo, 0.90)
                    FILTER (WHERE bip_flag = 1 AND exit_velo > 0), 1)      AS max_ev,
                ROUND(AVG(exit_velo) FILTER (WHERE bip_flag = 1), 1)       AS avg_ev,
                ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag = 1 AND exit_velo >= 95)
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS hard_hit_pct,
                ROUND(100.0 * COUNT(*) FILTER (WHERE bip_flag = 1
                                            AND launch_angle BETWEEN 8 AND 32)
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS sweet_spot_pct,
                ROUND(100.0 * SUM({_STATCAST_BARREL_EXPR})
                       / NULLIF(COUNT(*) FILTER (WHERE bip_flag = 1), 0), 1)
                                                                           AS barrel_pct
            FROM f_pa_event
            WHERE game_type = 0                  -- D39: reg-season only (IE convention)
            GROUP BY pitcher_id, year, league_id, level_id
        )
        SELECT * FROM agg
        WHERE bip >= 30
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_statcast_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_statcast_pitching"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# X-stats — bilinear-interpolated xwOBA / xBA / xSLG per BIP from L_REF
# (Slice 2, D26+D27)
#
# Reads OOTP's canonical (LA, EV) → x-stat lookup tables out of L_REF
# (`lref_xwoba_table` / `lref_xba_table` / `lref_xslg_table`) instead of
# computing xwOBA from scratch. Each table is a 106 × 61 grid:
#
#   rows:    launch_angle from -45° to +60° (1° steps)
#   cols:    exit_velocity from 50 to 110 mph (1 mph steps)
#   cell:    OOTP-canonical x-stat value, or blank for sparse cells
#
# Per-BIP bilinear interpolation: clamp (LA, EV) to grid range, find the
# four corner cells, weighted-average by fractional distances. Empty
# corners contribute 0 (xwOBA on a never-observed combo is essentially 0).
#
# We don't go through `launch_speed_angle` (LSA) — OOTP's at-bat dump
# carries (LA, EV) but not LSA, so the (LA, EV) → x-stat tables are
# directly usable. The `lref_xiso_table` is keyed on LSA and stays
# untouched here; reverse-engineering LSA classification from (LA, EV)
# is a future slice (per BACKLOG).
#
# Output schema (`f_player_season_xstats_batting` / `_pitching`):
#   player_id, year, league_id, level_id,
#   bip_xstat,    BIP count with valid (LA, EV) for lookup
#   xwoba_bip,    AVG(xwoba_pa) over those BIP
#   xba_bip,      AVG(xba_pa)
#   xslg_bip,     AVG(xslg_pa)
#
# Quality threshold: BIP ≥ 30 (matches the Statcast cohort tables).
# ─────────────────────────────────────────────────────────────────────────────


# UNPIVOT a wide xstat grid into long form (la, ev, value).
# `lref_xwoba_table` schema: la_adj VARCHAR, '50'..'110' VARCHAR (one column
# per EV value, all stored as varchar via L_REF's all_varchar=true).
def _xstat_long_view_sql(view_name: str, source_table: str) -> str:
    return f"""
        CREATE OR REPLACE VIEW {view_name} AS
        WITH long AS (
            UNPIVOT {source_table}
            ON COLUMNS(* EXCLUDE (la_adj))
            INTO
                NAME ev_str
                VALUE val_str
        )
        SELECT
            CAST(la_adj AS INTEGER)   AS la,
            CAST(ev_str AS INTEGER)   AS ev,
            TRY_CAST(val_str AS DOUBLE) AS val
        FROM long
        WHERE val_str IS NOT NULL
          AND val_str != ''
          AND TRY_CAST(val_str AS DOUBLE) IS NOT NULL
    """


# Build the per-BIP xstat lookup view: every BIP row in `f_pa_event` gets
# bilinear-interpolated xwoba_pa / xba_pa / xslg_pa. Out-of-grid LA or EV
# clamps to the grid edge; empty corners contribute 0 to the weighted
# average (rare combos with insufficient OOTP data are essentially zero).
_F_PA_EVENT_XSTATS_SQL = """
    CREATE OR REPLACE VIEW _f_pa_event_xstats AS
    WITH bip AS (
        SELECT
            game_id, year, batter_id, pitcher_id, pa_in_game_seq,
            league_id, level_id, game_type,
            -- Clamp LA and EV to the grid range so out-of-range BIPs
            -- still get a (conservative) lookup. Numbers outside the
            -- table are dominated by ground-grounders and pop-ups
            -- where xwoba is essentially 0 anyway.
            GREATEST(-45, LEAST(60,  launch_angle))            AS la_clamp,
            GREATEST(50,  LEAST(110, exit_velo))               AS ev_clamp,
            FLOOR(GREATEST(50, LEAST(110, exit_velo)))::INT    AS ev_floor,
            CEIL(GREATEST(50,  LEAST(110, exit_velo)))::INT    AS ev_ceil
        FROM f_pa_event
        WHERE bip_flag = 1
          AND game_type = 0                  -- D39: reg-season only
          AND exit_velo > 0
          AND launch_angle IS NOT NULL
    )
    SELECT
        b.game_id, b.year, b.batter_id, b.pitcher_id, b.pa_in_game_seq,
        b.league_id, b.level_id,
        -- Linear interpolation along EV (LA is integer in OOTP's at-bat
        -- log so no LA-axis interpolation needed). D39 fix: when EV is
        -- integer-valued (common — OOTP rounds to 0.1mph, FLOOR(=)CEIL),
        -- skip the interp arithmetic and use the floor value directly.
        -- Old form `floor*(ceil-x) + ceil*(x-floor)` collapsed to zero
        -- whenever ev_ceil == ev_floor, silently zeroing out anywhere
        -- from 5-20% of every player's BIPs (esp. crushed HR contact at
        -- 110.0 exit velo). Across the warehouse this systematically
        -- under-counted xBA / xSLG / xwOBA by ~30%.
        CASE WHEN b.ev_ceil = b.ev_floor
             THEN COALESCE(xwf.val, 0)
             ELSE COALESCE(xwf.val, 0) * (b.ev_ceil - b.ev_clamp)
                + COALESCE(xwc.val, COALESCE(xwf.val, 0)) * (b.ev_clamp - b.ev_floor)
        END AS xwoba_pa,
        CASE WHEN b.ev_ceil = b.ev_floor
             THEN COALESCE(xbf.val, 0)
             ELSE COALESCE(xbf.val, 0) * (b.ev_ceil - b.ev_clamp)
                + COALESCE(xbc.val, COALESCE(xbf.val, 0)) * (b.ev_clamp - b.ev_floor)
        END AS xba_pa,
        CASE WHEN b.ev_ceil = b.ev_floor
             THEN COALESCE(xsf.val, 0)
             ELSE COALESCE(xsf.val, 0) * (b.ev_ceil - b.ev_clamp)
                + COALESCE(xsc.val, COALESCE(xsf.val, 0)) * (b.ev_clamp - b.ev_floor)
        END AS xslg_pa
    FROM bip b
    LEFT JOIN _xwoba_lookup xwf ON xwf.la = b.la_clamp AND xwf.ev = b.ev_floor
    LEFT JOIN _xwoba_lookup xwc ON xwc.la = b.la_clamp AND xwc.ev = b.ev_ceil
    LEFT JOIN _xba_lookup   xbf ON xbf.la = b.la_clamp AND xbf.ev = b.ev_floor
    LEFT JOIN _xba_lookup   xbc ON xbc.la = b.la_clamp AND xbc.ev = b.ev_ceil
    LEFT JOIN _xslg_lookup  xsf ON xsf.la = b.la_clamp AND xsf.ev = b.ev_floor
    LEFT JOIN _xslg_lookup  xsc ON xsc.la = b.la_clamp AND xsc.ev = b.ev_ceil
"""


def _build_f_player_season_xstats_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(batter, year, league, level) IE-canonical xwOBA / xBA / xSLG.

    Reads OOTP's canonical (LA, EV) → x-stat tables out of L_REF.
    OOTP's IE display values use AB / PA denominators (NOT per-BIP):

      xBA   = SUM(xba_pa  over BIPs) / AB
      xSLG  = SUM(xslg_pa over BIPs) / AB
      xwOBA = (SUM(xwoba_pa over BIPs) + 0.69·uBB + 0.72·HBP) / PA

    The per-BIP averages (xwoba_bip / xba_bip / xslg_bip) are kept
    as inspection columns — useful for "what quality of contact did
    they make" vs "what did that contact + non-contact PAs translate
    to overall". D39 fix landed alongside the interpolation correction
    in `_f_pa_event_xstats`.
    """
    sql = """
        CREATE OR REPLACE TABLE f_player_season_xstats_batting AS
        WITH bip_agg AS (
            SELECT
                batter_id        AS player_id,
                year, league_id, level_id,
                COUNT(*)                                AS bip_xstat,
                SUM(xwoba_pa)                           AS sum_xwoba,
                SUM(xba_pa)                             AS sum_xba,
                SUM(xslg_pa)                            AS sum_xslg,
                ROUND(AVG(xwoba_pa), 4)                 AS xwoba_bip,
                ROUND(AVG(xba_pa),   4)                 AS xba_bip,
                ROUND(AVG(xslg_pa),  4)                 AS xslg_bip
            FROM _f_pa_event_xstats
            GROUP BY batter_id, year, league_id, level_id
        ),
        pa_agg AS (
            -- Pull AB / PA / non-BIP credits from the L2 batting fact table
            -- (split_id=1 = full-season; sum across multi-stint team_id rows).
            SELECT
                player_id, year, league_id, level_id,
                SUM(ab) AS ab,  SUM(pa) AS pa,
                SUM(bb) - SUM(ibb) AS ubb, SUM(hp) AS hbp
            FROM f_player_season_batting
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        )
        SELECT
            b.player_id, b.year, b.league_id, b.level_id,
            b.bip_xstat,
            b.xwoba_bip, b.xba_bip, b.xslg_bip,
            -- IE-style denominators: per AB for xBA/xSLG, per PA for xwOBA
            -- with non-BIP weights folded in (uBB=0.69, HBP=0.72 per OOTP base wOBA).
            -- D39 empirical scalers: lref_x*_table values are calibrated to
            -- real-MLB Statcast probabilities, but OOTP IE displays pre-scaled
            -- values ~1.22x (xBA) / ~1.09x (xSLG) higher. Calibrated against
            -- the Padres 2028 IE corpus (73 MLB qualifiers). xwOBA is already
            -- within ~3% so no scaler. Without these multipliers Diamond
            -- under-reports x-stats by 10-22% systematically.
            ROUND(1.22 * b.sum_xba  / NULLIF(p.ab, 0), 4)                           AS xba,
            ROUND(1.09 * b.sum_xslg / NULLIF(p.ab, 0), 4)                           AS xslg,
            ROUND((b.sum_xwoba + 0.69 * COALESCE(p.ubb, 0) + 0.72 * COALESCE(p.hbp, 0))
                  / NULLIF(p.pa, 0), 4)                                             AS xwoba
        FROM bip_agg b
        LEFT JOIN pa_agg p
            ON p.player_id = b.player_id
           AND p.year      = b.year
           AND p.league_id = b.league_id
           AND p.level_id  = b.level_id
        WHERE b.bip_xstat >= 30
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_xstats_batting
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_xstats_batting"
    ).fetchone()[0]


def _build_f_player_season_xstats_pitching(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(pitcher, year, league, level) allowed-contact xwOBA / xBA / xSLG.

    Same IE-canonical denominators as the batting variant. Pitcher
    "AB allowed" + "PA allowed" come from `career_pit`.
    """
    sql = """
        CREATE OR REPLACE TABLE f_player_season_xstats_pitching AS
        WITH bip_agg AS (
            SELECT
                pitcher_id       AS player_id,
                year, league_id, level_id,
                COUNT(*)                                AS bip_xstat,
                SUM(xwoba_pa)                           AS sum_xwoba,
                SUM(xba_pa)                             AS sum_xba,
                SUM(xslg_pa)                            AS sum_xslg,
                ROUND(AVG(xwoba_pa), 4)                 AS xwoba_bip,
                ROUND(AVG(xba_pa),   4)                 AS xba_bip,
                ROUND(AVG(xslg_pa),  4)                 AS xslg_bip
            FROM _f_pa_event_xstats
            WHERE pitcher_id IS NOT NULL
            GROUP BY pitcher_id, year, league_id, level_id
        ),
        bf_agg AS (
            -- For pitchers, denominators are batters faced (BF for xwOBA's PA)
            -- and AB allowed (AB for xBA/xSLG). f_player_season_pitching has
            -- the `bf` column. iw = intentional walks (pitcher analog of ibb).
            SELECT
                player_id, year, league_id, level_id,
                SUM(ab) AS ab, SUM(bf) AS pa,
                SUM(bb) - SUM(iw) AS ubb, SUM(hp) AS hbp
            FROM f_player_season_pitching
            WHERE split_id = 1
            GROUP BY player_id, year, league_id, level_id
        )
        SELECT
            b.player_id, b.year, b.league_id, b.level_id,
            b.bip_xstat,
            b.xwoba_bip, b.xba_bip, b.xslg_bip,
            -- Same D39 empirical scalers as the batting builder.
            ROUND(1.22 * b.sum_xba  / NULLIF(p.ab, 0), 4)                           AS xba,
            ROUND(1.09 * b.sum_xslg / NULLIF(p.ab, 0), 4)                           AS xslg,
            ROUND((b.sum_xwoba + 0.69 * COALESCE(p.ubb, 0) + 0.72 * COALESCE(p.hbp, 0))
                  / NULLIF(p.pa, 0), 4)                                             AS xwoba
        FROM bip_agg b
        LEFT JOIN bf_agg p
            ON p.player_id = b.player_id
           AND p.year      = b.year
           AND p.league_id = b.league_id
           AND p.level_id  = b.level_id
        WHERE b.bip_xstat >= 30
    """
    con.execute(sql)
    con.execute("""
        ALTER TABLE f_player_season_xstats_pitching
        ADD PRIMARY KEY (player_id, year, league_id, level_id)
    """)
    return con.execute(
        "SELECT COUNT(*) FROM f_player_season_xstats_pitching"
    ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — registered into the L3 builder list
# ─────────────────────────────────────────────────────────────────────────────


def build_l3_advanced(
    con: duckdb.DuckDBPyConnection,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Build the per-(player, year, league_id, level_id) advanced fact tables.

    Returns dict of `{table_name: row_count}`. Idempotent (CREATE OR
    REPLACE under the hood). Depends on L2 facts being current — the
    L3 orchestrator runs after L2 so this is always satisfied during
    normal `build_warehouse` runs.
    """
    rows: dict[str, int] = {}

    # 1. Register the league-constants views first; the table builders
    #    JOIN against the union view. Order matters — the final view
    #    references both component views by name.
    con.execute(_LG_CONSTANTS_NATIVE_VIEW_SQL)
    # _imported view (Slice 4): MLB rows from `lref_era_stats` (1870-2025);
    # MiLB rows from `lref_era_stats_minors` (Slice 5). Both come from
    # L_REF, which is per-save and frozen at first ingest (D27). Soft-skip
    # only on a pre-Slice-1 warehouse where L_REF hasn't been ingested yet.
    lref_era_loaded = con.execute(
        """
        SELECT COUNT(*) >= 2 FROM information_schema.tables
        WHERE table_name IN ('lref_era_stats', 'lref_era_stats_minors')
        """
    ).fetchone()[0]
    if lref_era_loaded:
        con.execute(_LG_CONSTANTS_IMPORTED_VIEW_SQL)
        con.execute(_LG_CONSTANTS_VIEW_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _lg_constants_advanced (view) "
                "[dim]native + imported (lref_era_stats MLB 1870-2025 + "
                "lref_era_stats_minors AAA/AA/A+/A 1901-2024)[/dim]"
            )
    else:
        # Without L_REF, the final union view is just the native rows.
        con.execute(
            "CREATE OR REPLACE VIEW _lg_constants_advanced AS "
            "SELECT * FROM _lg_constants_advanced_native"
        )
        if verbose:
            console.print(
                "  [yellow]![/yellow] _lg_constants_advanced (view) "
                "[dim]native only — run `diamond ingest` to ingest L_REF for "
                "pre-save baselines[/dim]"
            )

    # 1b. Register `_park_factor_resolved` (D22 v2 / Slice 3) — historical
    #     park factors via lref_era_ballparks (1871-2025, with LH/RH
    #     handedness splits) for pre-save MLB seasons; modern teams.parks.avg
    #     for save years (2026+). Replaces the prior history_lahman_teams
    #     dependency; gated on lref_era_ballparks existing (Slice 1 ingest).
    lref_era_bp_loaded = con.execute(
        """
        SELECT COUNT(*) > 0 FROM information_schema.tables
        WHERE table_name = 'lref_era_ballparks'
        """
    ).fetchone()[0]
    if lref_era_bp_loaded:
        con.execute(_PARK_FACTOR_RESOLVED_VIEW_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _park_factor_resolved (view) "
                "[dim]lref_era_ballparks 1871-2025 + LH/RH splits + "
                "modern fallback[/dim]"
            )
    else:
        con.execute(_PARK_FACTOR_RESOLVED_FALLBACK_SQL)
        if verbose:
            console.print(
                "  [yellow]![/yellow] _park_factor_resolved (view) "
                "[dim]modern only — run `diamond ingest` to ingest L_REF for "
                "historical park factors[/dim]"
            )

    # 1c. Register the L_REF-backed x-stat lookup views (Slice 2, D26+D27).
    #     Soft-skip if L_REF hasn't been ingested yet — pre-Slice-1 saves
    #     would hard-fail on the UNPIVOT against a missing table. Once L_REF
    #     freezes on first ingest, these views become permanent.
    lref_loaded = con.execute(
        """
        SELECT COUNT(*) >= 3 FROM information_schema.tables
        WHERE table_name IN ('lref_xwoba_table','lref_xba_table','lref_xslg_table')
        """
    ).fetchone()[0]
    if lref_loaded:
        con.execute(_xstat_long_view_sql("_xwoba_lookup", "lref_xwoba_table"))
        con.execute(_xstat_long_view_sql("_xba_lookup",   "lref_xba_table"))
        con.execute(_xstat_long_view_sql("_xslg_lookup",  "lref_xslg_table"))
        con.execute(_F_PA_EVENT_XSTATS_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _xwoba_lookup / _xba_lookup / _xslg_lookup "
                "(views) [dim]L_REF (LA, EV) → x-stat grids, long-form[/dim]"
            )
            console.print(
                "  [green]✓[/green] _f_pa_event_xstats (view) "
                "[dim]bilinear-interpolated xwoba_pa / xba_pa / xslg_pa per BIP[/dim]"
            )

    # 2. Per-player advanced facts.
    builders = [
        ("f_player_season_advanced_batting",  _build_f_player_season_advanced_batting),
        ("f_player_season_advanced_pitching", _build_f_player_season_advanced_pitching),
        ("f_player_season_statcast_batting",  _build_f_player_season_statcast_batting),
        ("f_player_season_statcast_pitching", _build_f_player_season_statcast_pitching),
    ]
    if lref_loaded:
        builders.extend([
            ("f_player_season_xstats_batting",   _build_f_player_season_xstats_batting),
            ("f_player_season_xstats_pitching",  _build_f_player_season_xstats_pitching),
        ])
    for name, fn in builders:
        n = fn(con)
        rows[name] = n
        if verbose:
            console.print(
                f"  [green]✓[/green] {name:<42} [dim]{n:>10,} rows[/dim]"
            )

    return rows
