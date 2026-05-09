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
# per-(league_id, year, level_id) aggregates). Save coverage only —
# 2026 onward in this save, since OOTP doesn't emit league_history rows
# for pre-save imported player-seasons.
_LG_CONSTANTS_NATIVE_VIEW_SQL = f"""
CREATE OR REPLACE VIEW _lg_constants_advanced_native AS
WITH agg_bat AS (
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
agg_pit AS (
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
        (lg_ab + (lg_bb - lg_ibb) + lg_sf + lg_hp) AS woba_denom
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
    -- woba_scale calibrates linear weights so that league wOBA == league OBP
    lg_obp / NULLIF(base_lg_woba, 0) AS woba_scale,
    -- Final scaled weights
    {_BASE_W_BB}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_bb,
    {_BASE_W_HBP} * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hbp,
    {_BASE_W_1B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_1b,
    {_BASE_W_2B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_2b,
    {_BASE_W_3B}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_3b,
    {_BASE_W_HR}  * (lg_obp / NULLIF(base_lg_woba, 0)) AS w_hr,
    -- League wOBA — equals lg_obp by construction
    lg_obp AS lg_woba,
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
WITH lahman_bat AS (
    SELECT
        yearID AS year,
        SUM(AB)::DOUBLE  AS ab,
        SUM(H)::DOUBLE   AS h,
        SUM("2B")::DOUBLE AS d,
        SUM("3B")::DOUBLE AS t,
        SUM(HR)::DOUBLE  AS hr,
        SUM(BB)::DOUBLE  AS bb,
        SUM(COALESCE(IBB, 0))::DOUBLE AS ibb,
        SUM(COALESCE(HBP, 0))::DOUBLE AS hp,
        SUM(COALESCE(SF, 0))::DOUBLE  AS sf,
        SUM(COALESCE(SH, 0))::DOUBLE  AS sh,
        SUM(COALESCE(SO, 0))::DOUBLE  AS k,
        SUM(R)::DOUBLE   AS r,
        -- PA derived: AB + BB + HBP + SF + SH (CI not tracked; <0.01% of PA)
        SUM(AB + BB + COALESCE(HBP, 0) + COALESCE(SF, 0) + COALESCE(SH, 0))::DOUBLE AS pa
    FROM history_lahman_batting
    WHERE lgID IN ('AL','NL','AA','FL','NA','PL','UA') AND yearID <= 2019
    GROUP BY yearID
),
bref_bat AS (
    SELECT
        year AS year,
        SUM(AB)::DOUBLE  AS ab,
        SUM(H)::DOUBLE   AS h,
        SUM("2B")::DOUBLE AS d,
        SUM("3B")::DOUBLE AS t,
        SUM(HR)::DOUBLE  AS hr,
        SUM(BB)::DOUBLE  AS bb,
        SUM(COALESCE(IBB, 0))::DOUBLE AS ibb,
        SUM(COALESCE(HBP, 0))::DOUBLE AS hp,
        SUM(COALESCE(SF, 0))::DOUBLE  AS sf,
        SUM(COALESCE(SH, 0))::DOUBLE  AS sh,
        SUM(COALESCE(SO, 0))::DOUBLE  AS k,
        SUM(R)::DOUBLE   AS r,
        SUM(PA)::DOUBLE  AS pa
    FROM history_bref_batting
    WHERE Lev IN ('Maj-AL','Maj-NL') AND year BETWEEN 2020 AND 2025
    GROUP BY year
),
all_bat AS (
    SELECT * FROM lahman_bat
    UNION ALL
    SELECT * FROM bref_bat
),
lahman_pit AS (
    SELECT
        yearID AS year,
        SUM(IPouts)::DOUBLE AS outs,
        SUM(ER)::DOUBLE     AS er,
        SUM(HR)::DOUBLE     AS hra,
        SUM(BB)::DOUBLE     AS pit_bb,
        SUM(COALESCE(HBP, 0))::DOUBLE AS pit_hp,
        SUM(COALESCE(SO, 0))::DOUBLE  AS pit_k
    FROM history_lahman_pitching
    WHERE lgID IN ('AL','NL','AA','FL','NA','PL','UA') AND yearID <= 2019
    GROUP BY yearID
),
bref_pit AS (
    SELECT
        year,
        SUM(IPouts)::DOUBLE AS outs,
        SUM(ER)::DOUBLE     AS er,
        SUM(HR)::DOUBLE     AS hra,
        SUM(BB)::DOUBLE     AS pit_bb,
        SUM(COALESCE(HBP, 0))::DOUBLE AS pit_hp,
        SUM(COALESCE(SO, 0))::DOUBLE  AS pit_k
    FROM history_bref_pitching
    WHERE Lev IN ('Maj-AL','Maj-NL') AND year BETWEEN 2020 AND 2025
    GROUP BY year
),
all_pit AS (
    SELECT * FROM lahman_pit
    UNION ALL
    SELECT * FROM bref_pit
),
joined AS (
    SELECT
        203 AS league_id, b.year, 1 AS level_id,
        b.pa  AS lg_pa,
        b.ab  AS lg_ab,
        b.h   AS lg_h,
        b.d   AS lg_d,
        b.t   AS lg_t,
        b.hr  AS lg_hr,
        b.bb  AS lg_bb,
        b.ibb AS lg_ibb,
        b.hp  AS lg_hp,
        b.sf  AS lg_sf,
        b.r   AS lg_r,
        (b.h - b.d - b.t - b.hr) AS lg_singles,
        COALESCE(p.outs, 0.0)   AS lg_outs,
        COALESCE(p.er,   0.0)   AS lg_er,
        COALESCE(p.hra,  0.0)   AS lg_hra,
        COALESCE(p.pit_bb, 0.0) AS lg_pit_bb,
        COALESCE(p.pit_hp, 0.0) AS lg_pit_hp,
        COALESCE(p.pit_k,  0.0) AS lg_pit_k
    FROM all_bat b
    LEFT JOIN all_pit p ON p.year = b.year
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
        (lg_ab + (lg_bb - lg_ibb) + lg_sf + lg_hp) AS woba_denom
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
    lg_obp AS lg_woba,
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
    SELECT
        x.team_id,
        ht.yearID AS year,
        ht.BPF::DOUBLE / 100.0 AS bat_park_avg,
        ht.PPF::DOUBLE / 100.0 AS pit_park_avg
    FROM history_lahman_teams ht
    INNER JOIN ootp_franchise_xwalk x ON x.lahman_franch_id = ht.franchID
    WHERE ht.yearID <= 2019 AND ht.BPF IS NOT NULL AND ht.PPF IS NOT NULL
),
seen_pairs AS (
    SELECT team_id, year FROM f_player_season_batting WHERE level_id = 1 AND split_id = 1
    UNION
    SELECT team_id, year FROM f_player_season_pitching WHERE level_id = 1 AND split_id = 1
),
modern AS (
    SELECT
        s.team_id,
        s.year,
        COALESCE(prk.avg, 1.0) AS bat_park_avg,
        COALESCE(prk.avg, 1.0) AS pit_park_avg
    FROM seen_pairs s
    LEFT JOIN teams t   ON t.team_id  = s.team_id
    LEFT JOIN parks prk ON prk.park_id = t.park_id
)
SELECT team_id, year, bat_park_avg, pit_park_avg, 'lahman' AS src
FROM historical
UNION ALL
SELECT m.team_id, m.year, m.bat_park_avg, m.pit_park_avg, 'modern' AS src
FROM modern m
WHERE NOT EXISTS (
    SELECT 1 FROM historical h
    WHERE h.team_id = m.team_id AND h.year = m.year
)
"""


# Fallback when `history_lahman_teams` doesn't exist (fresh save without
# `fetch-history` run). Just exposes the modern teams.parks lookup with
# the same shape, so downstream JOIN-on-(team_id,year) keeps working.
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
            -- D22: prefer Lahman historical BPF for pre-2020 MLB seasons,
            -- fall back to modern teams.parks.avg via _park_factor_resolved.
            -- Final fallback to 1.0 covers defunct franchises / unmapped teams.
            SELECT d.player_id, d.year, d.league_id, d.level_id,
                   COALESCE(pfr.bat_park_avg, 1.0) AS park_avg
            FROM dominant_team d
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
                (w_bb*nibb + w_hbp*hp + w_1b*singles + w_2b*d + w_3b*t + w_hr*hr)
                / NULLIF(ab + nibb + sf + hp, 0) AS player_woba,
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
            league_id, level_id,
            -- Clamp LA and EV to the grid range so out-of-range BIPs
            -- still get a (conservative) lookup. Numbers outside the
            -- table are dominated by ground-grounders and pop-ups
            -- where xwoba is essentially 0 anyway.
            GREATEST(-45, LEAST(60,  launch_angle))            AS la_clamp,
            GREATEST(50,  LEAST(110, exit_velo))               AS ev_clamp,
            FLOOR(GREATEST(50, LEAST(110, exit_velo)))::INT    AS ev_floor,
            CEIL(GREATEST(50,  LEAST(110, exit_velo)))::INT    AS ev_ceil
        FROM f_pa_event
        WHERE bip_flag = 1 AND exit_velo > 0 AND launch_angle IS NOT NULL
    )
    SELECT
        b.game_id, b.year, b.batter_id, b.pitcher_id, b.pa_in_game_seq,
        b.league_id, b.level_id,
        -- Linear interpolation along EV (LA is integer in OOTP's at-bat
        -- log so no LA-axis interpolation needed). Empty corners → 0.
        COALESCE(xwf.val, 0) * (b.ev_ceil - b.ev_clamp)
            + COALESCE(xwc.val, COALESCE(xwf.val, 0)) * (b.ev_clamp - b.ev_floor)
                AS xwoba_pa,
        COALESCE(xbf.val, 0) * (b.ev_ceil - b.ev_clamp)
            + COALESCE(xbc.val, COALESCE(xbf.val, 0)) * (b.ev_clamp - b.ev_floor)
                AS xba_pa,
        COALESCE(xsf.val, 0) * (b.ev_ceil - b.ev_clamp)
            + COALESCE(xsc.val, COALESCE(xsf.val, 0)) * (b.ev_clamp - b.ev_floor)
                AS xslg_pa
    FROM bip b
    LEFT JOIN _xwoba_lookup xwf ON xwf.la = b.la_clamp AND xwf.ev = b.ev_floor
    LEFT JOIN _xwoba_lookup xwc ON xwc.la = b.la_clamp AND xwc.ev = b.ev_ceil
    LEFT JOIN _xba_lookup   xbf ON xbf.la = b.la_clamp AND xbf.ev = b.ev_floor
    LEFT JOIN _xba_lookup   xbc ON xbc.la = b.la_clamp AND xbc.ev = b.ev_ceil
    LEFT JOIN _xslg_lookup  xsf ON xsf.la = b.la_clamp AND xsf.ev = b.ev_floor
    LEFT JOIN _xslg_lookup  xsc ON xsc.la = b.la_clamp AND xsc.ev = b.ev_ceil
"""


def _build_f_player_season_xstats_batting(con: duckdb.DuckDBPyConnection) -> int:
    """Per-(batter, year, league, level) bilinear-interpolated xwOBA / xBA / xSLG.

    Reads OOTP's canonical (LA, EV) → x-stat tables out of L_REF. Each
    BIP gets per-PA expected values; aggregate to season as a simple mean.
    Pairs with the existing Statcast cohort table — together they answer
    "what kind of contact?" (max_ev / hh%) AND "what should that contact
    have produced?" (xwOBA).
    """
    sql = """
        CREATE OR REPLACE TABLE f_player_season_xstats_batting AS
        WITH agg AS (
            SELECT
                batter_id        AS player_id,
                year, league_id, level_id,
                COUNT(*)                                AS bip_xstat,
                ROUND(AVG(xwoba_pa), 4)                 AS xwoba_bip,
                ROUND(AVG(xba_pa),   4)                 AS xba_bip,
                ROUND(AVG(xslg_pa),  4)                 AS xslg_bip
            FROM _f_pa_event_xstats
            GROUP BY batter_id, year, league_id, level_id
        )
        SELECT * FROM agg
        WHERE bip_xstat >= 30
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

    Same shape as the batting table but keyed on `pitcher_id`. "What
    quality of contact did this pitcher allow, on average?" — pairs
    with FIP / SIERA on the pitcher advanced view.
    """
    sql = """
        CREATE OR REPLACE TABLE f_player_season_xstats_pitching AS
        WITH agg AS (
            SELECT
                pitcher_id       AS player_id,
                year, league_id, level_id,
                COUNT(*)                                AS bip_xstat,
                ROUND(AVG(xwoba_pa), 4)                 AS xwoba_bip,
                ROUND(AVG(xba_pa),   4)                 AS xba_bip,
                ROUND(AVG(xslg_pa),  4)                 AS xslg_bip
            FROM _f_pa_event_xstats
            WHERE pitcher_id IS NOT NULL
            GROUP BY pitcher_id, year, league_id, level_id
        )
        SELECT * FROM agg
        WHERE bip_xstat >= 30
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
    # _imported view depends on history_lahman_* + history_bref_*. If the
    # one-time `diamond fetch-history` backfill hasn't run yet, those
    # tables don't exist and the view registration fails. Soft-skip in
    # that case so warehouse builds don't hard-fail on a fresh save —
    # advanced stats for pre-save seasons stay null until history is loaded.
    history_loaded = con.execute(
        """
        SELECT COUNT(*) >= 4 FROM information_schema.tables
        WHERE table_name IN ('history_lahman_batting','history_lahman_pitching',
                             'history_bref_batting','history_bref_pitching')
        """
    ).fetchone()[0]
    if history_loaded:
        con.execute(_LG_CONSTANTS_IMPORTED_VIEW_SQL)
        con.execute(_LG_CONSTANTS_VIEW_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _lg_constants_advanced (view) "
                "[dim]native + imported (Lahman 1871-2019 + BREF 2020-2025)[/dim]"
            )
    else:
        # Without history tables, the final union view is just the native rows.
        con.execute(
            "CREATE OR REPLACE VIEW _lg_constants_advanced AS "
            "SELECT * FROM _lg_constants_advanced_native"
        )
        if verbose:
            console.print(
                "  [yellow]![/yellow] _lg_constants_advanced (view) "
                "[dim]native only — run `diamond fetch-history` to backfill "
                "pre-save MLB baselines[/dim]"
            )

    # 1b. Register `_park_factor_resolved` (D22) — backfills Lahman
    #     historical BPF/PPF for ≤2019 MLB seasons; falls back to
    #     modern teams.parks.avg otherwise. Conditional on
    #     history_lahman_teams existing.
    history_teams_loaded = con.execute(
        """
        SELECT COUNT(*) > 0 FROM information_schema.tables
        WHERE table_name = 'history_lahman_teams'
        """
    ).fetchone()[0]
    if history_teams_loaded:
        con.execute(_PARK_FACTOR_RESOLVED_VIEW_SQL)
        if verbose:
            console.print(
                "  [green]✓[/green] _park_factor_resolved (view) "
                "[dim]Lahman BPF/PPF ≤ 2019 + modern ≥ 2020[/dim]"
            )
    else:
        con.execute(_PARK_FACTOR_RESOLVED_FALLBACK_SQL)
        if verbose:
            console.print(
                "  [yellow]![/yellow] _park_factor_resolved (view) "
                "[dim]modern only — run `diamond fetch-history` to "
                "backfill pre-2020 park factors[/dim]"
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
