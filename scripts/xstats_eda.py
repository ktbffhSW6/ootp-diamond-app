"""20-minute EDA probe for D-tier xstats (xBA/xSLG/xwOBA/xERA).

Goals:
  1) How much training data do we have? (at-bats with valid EV/LA)
  2) What's the IE xBA/xSLG/xwOBA distribution look like?
  3) Does a naive EV/LA bucket lookup (built from realized outcomes) get us close
     to IE's xstats on the MLB-only Sox control group?
  4) Cell-count sanity: is there enough population per bucket to be stable?

Approach for (3): Build empirical outcome rates per (EV-bucket × LA-bucket)
across ALL MLB at-bats. Then for each MLB-only Sox batter, map their actual
BIP into those buckets and average the bucket-level expected outcome.
Compare that to their IE-reported xBA/xSLG/xwOBA.

Output: prints summary stats and per-player comparison table to stdout.
Does NOT touch the codebase. Pure read-only probe.
"""
from __future__ import annotations

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import duckdb
from pathlib import Path

SAVE = Path(r"C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games\Building the Green Monster.lg")
DUMP = SAVE / "dump" / "dump_2029_11" / "csv"
IE = SAVE / "import_export"

con = duckdb.connect()

# --- Load needed CSVs as views ---------------------------------------------
def view(name: str, csv: Path) -> None:
    con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_csv_auto('{csv.as_posix()}', sample_size=-1, ignore_errors=true)")

view("at_bats", DUMP / "players_at_bat_batting_stats.csv")
view("games", DUMP / "games.csv")
view("players", DUMP / "players.csv")
view("ie_bs1", IE / "boston_red_sox_organization_-_roster_batting_superstats_1.csv")

# --- Q1: How much usable training data? ------------------------------------
print("=" * 78)
print("Q1: TRAINING DATA VOLUME")
print("=" * 78)

total = con.execute("SELECT COUNT(*) FROM at_bats").fetchone()[0]
bip_total = con.execute("""
    SELECT COUNT(*) FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
""").fetchone()[0]
bip_with_ev = con.execute("""
    SELECT COUNT(*) FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
""").fetchone()[0]
print(f"  Total PA (all leagues, all game types):        {total:>10,}")
print(f"  Regular-season BIP (all leagues):              {bip_total:>10,}")
print(f"  ...with valid EV+LA:                           {bip_with_ev:>10,}")
print(f"  EV/LA coverage rate:                           {100.0*bip_with_ev/bip_total:>9.1f}%")
print()

# Coverage by year (parsing year from game date)
year_dist = con.execute("""
    SELECT EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) AS yr, COUNT(*) AS bip
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0
    GROUP BY yr ORDER BY yr
""").fetchall()
print("  BIP-with-EV by season:")
for y, n in year_dist:
    print(f"    {y}: {n:>9,}")
print()

# --- Q2: IE xBA/xSLG/xwOBA distribution ------------------------------------
print("=" * 78)
print("Q2: IE xBA/xSLG/xwOBA DISTRIBUTION (Boston roster)")
print("=" * 78)

# IE reports stats with "-" for null. Cast carefully.
agg_q = """
    SELECT
        COUNT(*) AS n_rows,
        COUNT("xBA") FILTER (WHERE TRY_CAST(REPLACE(NULLIF(CAST("xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) IS NOT NULL) AS n_xba,
        COUNT("xSLG") FILTER (WHERE TRY_CAST(REPLACE(NULLIF(CAST("xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) IS NOT NULL) AS n_xslg,
        COUNT("xwOBA") FILTER (WHERE TRY_CAST(REPLACE(NULLIF(CAST("xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) IS NOT NULL) AS n_xwoba,
        ROUND(MIN(TRY_CAST(REPLACE(NULLIF(CAST("xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS min_xba,
        ROUND(MAX(TRY_CAST(REPLACE(NULLIF(CAST("xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS max_xba,
        ROUND(AVG(TRY_CAST(REPLACE(NULLIF(CAST("xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS avg_xba,
        ROUND(STDDEV(TRY_CAST(REPLACE(NULLIF(CAST("xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS sd_xba,
        ROUND(MIN(TRY_CAST(REPLACE(NULLIF(CAST("xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS min_xslg,
        ROUND(MAX(TRY_CAST(REPLACE(NULLIF(CAST("xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS max_xslg,
        ROUND(AVG(TRY_CAST(REPLACE(NULLIF(CAST("xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS avg_xslg,
        ROUND(STDDEV(TRY_CAST(REPLACE(NULLIF(CAST("xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS sd_xslg,
        ROUND(MIN(TRY_CAST(REPLACE(NULLIF(CAST("xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS min_xwoba,
        ROUND(MAX(TRY_CAST(REPLACE(NULLIF(CAST("xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS max_xwoba,
        ROUND(AVG(TRY_CAST(REPLACE(NULLIF(CAST("xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS avg_xwoba,
        ROUND(STDDEV(TRY_CAST(REPLACE(NULLIF(CAST("xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE)), 3) AS sd_xwoba
    FROM ie_bs1
"""
r = con.execute(agg_q).fetchone()
print(f"  Total IE rows: {r[0]}")
print(f"  Rows w/ xBA reported: {r[1]}")
print(f"  Rows w/ xSLG reported: {r[2]}")
print(f"  Rows w/ xwOBA reported: {r[3]}")
print()
print(f"  xBA   : min={r[4]}  max={r[5]}  avg={r[6]}  sd={r[7]}")
print(f"  xSLG  : min={r[8]}  max={r[9]}  avg={r[10]}  sd={r[11]}")
print(f"  xwOBA : min={r[12]}  max={r[13]}  avg={r[14]}  sd={r[15]}")
print()

# --- Q3: Build a bucket-lookup model from realized outcomes ---------------
print("=" * 78)
print("Q3: NAIVE EV×LA BUCKET MODEL → COMPARE TO IE xBA/xSLG/xwOBA")
print("=" * 78)

# Build outcome lookup: for each (EV-bucket, LA-bucket), compute
# the empirical BA, SLG, wOBA across all 2029 MLB regular-season BIP.
#
# wOBA weights (FanGraphs ~2024):
#   uBB=0.69, HBP=0.72, 1B=0.89, 2B=1.27, 3B=1.62, HR=2.10
#   wOBA = (sum of weighted events) / (PA - IBB - SO + ...) approx.
# But for BIP-only outcome lookup we drop walks: just need (1B/2B/3B/HR/out)
# Total bases: 1B=1, 2B=2, 3B=3, HR=4, GO/FO=0
con.execute("""
    CREATE OR REPLACE TABLE bip_train AS
    SELECT
        a.exit_velo, a.launch_angle, a.result,
        -- 5-bucket EV: <70 / 70-80 / 80-90 / 90-100 / 100+
        CASE
            WHEN a.exit_velo < 70 THEN 0
            WHEN a.exit_velo < 80 THEN 1
            WHEN a.exit_velo < 90 THEN 2
            WHEN a.exit_velo < 100 THEN 3
            ELSE 4
        END AS ev_b,
        -- 6-bucket LA: <0 / 0-10 / 10-20 / 20-30 / 30-40 / 40+
        CASE
            WHEN a.launch_angle < 0 THEN 0
            WHEN a.launch_angle < 10 THEN 1
            WHEN a.launch_angle < 20 THEN 2
            WHEN a.launch_angle < 30 THEN 3
            WHEN a.launch_angle < 40 THEN 4
            ELSE 5
        END AS la_b,
        -- realized outcomes
        CASE WHEN a.result = 6 THEN 1 ELSE 0 END AS is_1b,
        CASE WHEN a.result = 7 THEN 1 ELSE 0 END AS is_2b,
        CASE WHEN a.result = 8 THEN 1 ELSE 0 END AS is_3b,
        CASE WHEN a.result = 9 THEN 1 ELSE 0 END AS is_hr,
        CASE WHEN a.result IN (6,7,8,9) THEN 1 ELSE 0 END AS is_hit,
        CASE WHEN a.result = 6 THEN 1
             WHEN a.result = 7 THEN 2
             WHEN a.result = 8 THEN 3
             WHEN a.result = 9 THEN 4
             ELSE 0 END AS tb,
        -- wOBA contribution (BIP-only; we'll average over BIP not PA)
        CASE WHEN a.result = 6 THEN 0.89
             WHEN a.result = 7 THEN 1.27
             WHEN a.result = 8 THEN 1.62
             WHEN a.result = 9 THEN 2.10
             ELSE 0 END AS woba_v
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
""")

bucket_count = con.execute("SELECT COUNT(*) FROM bip_train").fetchone()[0]
print(f"  BIP training rows: {bucket_count:,}")

# Lookup table: per (ev_b, la_b)
print("\n  Bucket population & expected outcomes:")
print(f"  {'ev_b':<5}{'la_b':<5}{'n':>8}  {'xBA':>6}  {'xSLG':>6}  {'xwOBA':>6}")
for row in con.execute("""
    SELECT ev_b, la_b, COUNT(*) AS n,
        ROUND(AVG(is_hit), 3) AS xba,
        ROUND(AVG(tb), 3) AS xslg,
        ROUND(AVG(woba_v), 3) AS xwoba
    FROM bip_train
    GROUP BY ev_b, la_b
    ORDER BY ev_b, la_b
""").fetchall():
    print(f"  {row[0]:<5}{row[1]:<5}{row[2]:>8,}  {row[3]:>6.3f}  {row[4]:>6.3f}  {row[5]:>6.3f}")

# Build per-player expected stat by averaging bucket-rates over their actual BIP
con.execute("""
    CREATE OR REPLACE TABLE bucket_lookup AS
    SELECT ev_b, la_b,
        AVG(is_hit) AS p_ba,
        AVG(tb) AS p_slg,
        AVG(woba_v) AS p_woba
    FROM bip_train
    GROUP BY ev_b, la_b
""")

con.execute("""
    -- BIP contribution: sum of bucket-expected hits/TB/woba per player
    CREATE OR REPLACE TABLE bip_contrib AS
    SELECT
        a.player_id,
        COUNT(*) AS bip,
        SUM(b.p_ba) AS sum_xh,
        SUM(b.p_slg) AS sum_xtb,
        SUM(b.p_woba) AS sum_xwoba_bip
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    JOIN bucket_lookup b ON
        b.ev_b = CASE WHEN a.exit_velo < 70 THEN 0 WHEN a.exit_velo < 80 THEN 1
                      WHEN a.exit_velo < 90 THEN 2 WHEN a.exit_velo < 100 THEN 3 ELSE 4 END
    AND b.la_b = CASE WHEN a.launch_angle < 0 THEN 0 WHEN a.launch_angle < 10 THEN 1
                      WHEN a.launch_angle < 20 THEN 2 WHEN a.launch_angle < 30 THEN 3
                      WHEN a.launch_angle < 40 THEN 4 ELSE 5 END
    WHERE EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) = 2029
      AND a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
    GROUP BY a.player_id
""")
# Total PA breakdown per player to get correct denominator
con.execute("""
    CREATE OR REPLACE TABLE pa_breakdown AS
    SELECT
        a.player_id,
        COUNT(*) AS pa,
        COUNT(*) FILTER (WHERE a.result = 1) AS k,
        COUNT(*) FILTER (WHERE a.result = 2) AS bb,
        COUNT(*) FILTER (WHERE a.result = 10) AS hbp,
        COUNT(*) FILTER (WHERE a.sac > 0) AS sac,
        -- AB = PA - BB - HBP - SAC
        COUNT(*) - COUNT(*) FILTER (WHERE a.result = 2)
                 - COUNT(*) FILTER (WHERE a.result = 10)
                 - COUNT(*) FILTER (WHERE a.sac > 0) AS ab
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) = 2029
    GROUP BY a.player_id
""")
con.execute("""
    CREATE OR REPLACE TABLE player_xstat AS
    SELECT
        p.player_id,
        p.pa, p.ab, p.k, p.bb, p.hbp,
        bc.bip,
        ROUND(bc.sum_xh / NULLIF(p.ab, 0), 3) AS x_ba,
        ROUND(bc.sum_xtb / NULLIF(p.ab, 0), 3) AS x_slg,
        -- xwOBA includes BB (0.69) + HBP (0.72) + BIP-bucket-weighted; per PA-AB-IBB+SF
        -- We don't have IBB or SF exact split; use (PA - K) as approx wOBA denom? No,
        -- standard wOBA denom is AB+BB+HBP+SF (excl IBB/SAC). Simplification: use
        -- AB+BB+HBP since SAC excluded and SF rare.
        ROUND((bc.sum_xwoba_bip + 0.69*p.bb + 0.72*p.hbp) /
              NULLIF(p.ab + p.bb + p.hbp, 0), 3) AS x_woba
    FROM pa_breakdown p
    LEFT JOIN bip_contrib bc ON bc.player_id = p.player_id
""")

# Compare to IE for MLB-only Sox (filter to BIP>=50 to skip cup-of-coffee guys)
print()
print("  Per-player comparison (top 20 by BIP, IE xBA available):")
print(f"  {'name':<28} {'BIP':>5}  {'IE xBA':>7}  {'der xBA':>7}  {'Δ':>6}  "
      f"{'IE xSLG':>7}  {'der xSLG':>7}  {'Δ':>6}  {'IE xwOBA':>8}  {'der xwOBA':>8}  {'Δ':>6}")
rows = con.execute("""
    SELECT
        ie."Name" AS name,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."BIP" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_bip,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
        ps.x_ba, ps.x_slg, ps.x_woba, ps.bip
    FROM ie_bs1 ie
    JOIN players p
      ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
    LEFT JOIN player_xstat ps ON ps.player_id = p.player_id
    WHERE TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) IS NOT NULL
    ORDER BY ie_bip DESC NULLS LAST
    LIMIT 25
""").fetchall()
for r in rows:
    name, ie_bip, ie_xba, ie_xslg, ie_xwoba, x_ba, x_slg, x_woba, bip = r
    if x_ba is None:
        print(f"  {name:<28} {ie_bip or 0:>5.0f}  {ie_xba:>7.3f}  {'(no data)':>7}")
        continue
    d_ba = (x_ba - ie_xba) if ie_xba is not None else 0
    d_slg = (x_slg - ie_xslg) if ie_xslg is not None else 0
    d_woba = (x_woba - ie_xwoba) if ie_xwoba is not None else 0
    print(f"  {name:<28} {ie_bip or 0:>5.0f}  {ie_xba:>7.3f}  {x_ba:>7.3f}  {d_ba:>+6.3f}  "
          f"{ie_xslg:>7.3f}  {x_slg:>7.3f}  {d_slg:>+6.3f}  "
          f"{ie_xwoba:>8.3f}  {x_woba:>8.3f}  {d_woba:>+6.3f}")

# Aggregate match quality
print()
agg = con.execute("""
    WITH joined AS (
        SELECT
            TRY_CAST(REPLACE(NULLIF(CAST(ie."BIP" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_bip,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
            ps.x_ba, ps.x_slg, ps.x_woba
        FROM ie_bs1 ie
        JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
        LEFT JOIN player_xstat ps ON ps.player_id = p.player_id
    )
    SELECT
        COUNT(*) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL) AS n_pairs,
        ROUND(AVG(ABS(x_ba - ie_xba)) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL), 4) AS mae_ba,
        ROUND(AVG(ABS(x_slg - ie_xslg)) FILTER (WHERE ie_xslg IS NOT NULL AND x_slg IS NOT NULL), 4) AS mae_slg,
        ROUND(AVG(ABS(x_woba - ie_xwoba)) FILTER (WHERE ie_xwoba IS NOT NULL AND x_woba IS NOT NULL), 4) AS mae_woba,
        ROUND(corr(x_ba, ie_xba) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL), 3) AS r_ba,
        ROUND(corr(x_slg, ie_xslg) FILTER (WHERE ie_xslg IS NOT NULL AND x_slg IS NOT NULL), 3) AS r_slg,
        ROUND(corr(x_woba, ie_xwoba) FILTER (WHERE ie_xwoba IS NOT NULL AND x_woba IS NOT NULL), 3) AS r_woba
    FROM joined
""").fetchone()
print(f"  Naive bucket-model fit (n={agg[0]} player pairs):")
print(f"    MAE  xBA  : {agg[1]:.4f}    Pearson r: {agg[4]}")
print(f"    MAE  xSLG : {agg[2]:.4f}    Pearson r: {agg[5]}")
print(f"    MAE  xwOBA: {agg[3]:.4f}    Pearson r: {agg[6]}")
print()

# --- Q4: What % of player-pairs match within typical reconciliation tol? ---
# IE displays xBA to 3 decimals. ±0.010 is a reasonable "match" threshold.
print("  % of pairs matching within typical IE display tolerances:")
for col, der_col, tol in [("xBA", "x_ba", 0.010), ("xSLG", "x_slg", 0.020), ("xwOBA", "x_woba", 0.015)]:
    pct = con.execute(f"""
        WITH joined AS (
            SELECT
                TRY_CAST(REPLACE(NULLIF(CAST(ie."{col}" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_v,
                ps.{der_col} AS der_v
            FROM ie_bs1 ie
            JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
            LEFT JOIN player_xstat ps ON ps.player_id = p.player_id
        )
        SELECT 100.0 * AVG(CASE WHEN ABS(der_v - ie_v) <= {tol} THEN 1.0 ELSE 0 END)
        FROM joined WHERE ie_v IS NOT NULL AND der_v IS NOT NULL
    """).fetchone()[0]
    print(f"    {col:<6} (+/- {tol}): {pct:>5.1f}%")
print()

print("=" * 78)
print("RECOMMENDATION")
print("=" * 78)
print("""
  Read the MAE / r / match-rate above. Heuristic:
    - r >= 0.85 + xBA MAE <= 0.020 → naive bucket model is enough; finer model
      gives diminishing returns. Ship it as a D-tier "good-enough" derivation.
    - r 0.70-0.85 → bucket model partial; refine with finer bins or add hit_loc /
      pull-direction features. Worth ~3 hours.
    - r < 0.70 or large MAE → OOTP's xstats use logic we can't see from EV/LA
      alone; likely uses pre-roll batter ratings to seed the expectation.
      D-tier stays D-tier. Skip and move on.
""")
