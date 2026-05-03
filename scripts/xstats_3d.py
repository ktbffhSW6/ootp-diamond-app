"""3D EV x LA x hit_loc bucket model — xstats EDA refinement.

Tests whether adding hit_loc as a third dimension closes the gap to IE xstats.
Compares to the 2D model from xstats_eda.py.
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
def view(name: str, csv: Path) -> None:
    con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_csv_auto('{csv.as_posix()}', sample_size=-1, ignore_errors=true)")

view("at_bats", DUMP / "players_at_bat_batting_stats.csv")
view("games", DUMP / "games.csv")
view("players", DUMP / "players.csv")
view("ie_bs1", IE / "boston_red_sox_organization_-_roster_batting_superstats_1.csv")

# ─── Step 1: profile hit_loc values to design buckets ────────────────────────
print("=" * 78)
print("hit_loc DISTRIBUTION (regular-season BIP w/ valid EV+LA)")
print("=" * 78)
hl_dist = con.execute("""
    SELECT a.hit_loc, COUNT(*) AS n,
        ROUND(AVG(CASE WHEN a.result IN (6,7,8,9) THEN 1 ELSE 0 END), 3) AS hit_rate
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
    GROUP BY a.hit_loc ORDER BY n DESC
""").fetchall()

print(f"  {'hit_loc':>8} {'count':>10} {'hit_rate':>10}")
for hl, n, hr in hl_dist[:30]:
    print(f"  {hl:>8} {n:>10,} {hr:>10}")
print(f"  ... ({len(hl_dist)} distinct values total)")
print()

# Approach: hit_loc encodes fielder + zone. We don't know the exact 0-105 mapping
# but we can let the data speak — use raw hit_loc as the bucket key. With 781K BIP
# spread across ~100 distinct values + 5 EV × 6 LA buckets, we'll have thin cells
# in places. Use Empirical Bayes shrinkage to handle this:
#   bucket_rate_smoothed = (n*bucket_rate + k*global_la_rate) / (n+k)
# where k=20 and global_la_rate is the per-(EV,LA) rate ignoring hit_loc.

# ─── Step 2: build the 3D + 2D bucket tables and shrinkage ──────────────────
print("=" * 78)
print("Build 3D bucket model with shrinkage to 2D fallback")
print("=" * 78)

con.execute("""
    CREATE OR REPLACE TABLE bip_train AS
    SELECT
        CASE WHEN a.exit_velo < 70 THEN 0
             WHEN a.exit_velo < 80 THEN 1
             WHEN a.exit_velo < 90 THEN 2
             WHEN a.exit_velo < 100 THEN 3
             ELSE 4 END AS ev_b,
        CASE WHEN a.launch_angle < 0 THEN 0
             WHEN a.launch_angle < 10 THEN 1
             WHEN a.launch_angle < 20 THEN 2
             WHEN a.launch_angle < 30 THEN 3
             WHEN a.launch_angle < 40 THEN 4
             ELSE 5 END AS la_b,
        a.hit_loc,
        CASE WHEN a.result IN (6,7,8,9) THEN 1 ELSE 0 END AS is_hit,
        CASE WHEN a.result = 6 THEN 1 WHEN a.result = 7 THEN 2
             WHEN a.result = 8 THEN 3 WHEN a.result = 9 THEN 4 ELSE 0 END AS tb,
        CASE WHEN a.result = 6 THEN 0.89 WHEN a.result = 7 THEN 1.27
             WHEN a.result = 8 THEN 1.62 WHEN a.result = 9 THEN 2.10
             ELSE 0 END AS woba_v
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
""")

# 2D fallback (per EV x LA)
con.execute("""
    CREATE OR REPLACE TABLE lookup_2d AS
    SELECT ev_b, la_b,
        AVG(is_hit) AS p_ba,
        AVG(tb) AS p_slg,
        AVG(woba_v) AS p_woba
    FROM bip_train
    GROUP BY ev_b, la_b
""")

# 3D raw (per EV x LA x hit_loc)
con.execute("""
    CREATE OR REPLACE TABLE lookup_3d_raw AS
    SELECT ev_b, la_b, hit_loc, COUNT(*) AS n,
        AVG(is_hit) AS p_ba_raw,
        AVG(tb) AS p_slg_raw,
        AVG(woba_v) AS p_woba_raw
    FROM bip_train
    GROUP BY ev_b, la_b, hit_loc
""")

# Shrinkage: blend 3D raw with 2D fallback. k=20 controls strength.
SHRINK_K = 20
con.execute(f"""
    CREATE OR REPLACE TABLE lookup_3d AS
    SELECT
        r.ev_b, r.la_b, r.hit_loc, r.n,
        (r.n * r.p_ba_raw   + {SHRINK_K} * f.p_ba)   / (r.n + {SHRINK_K}) AS p_ba,
        (r.n * r.p_slg_raw  + {SHRINK_K} * f.p_slg)  / (r.n + {SHRINK_K}) AS p_slg,
        (r.n * r.p_woba_raw + {SHRINK_K} * f.p_woba) / (r.n + {SHRINK_K}) AS p_woba
    FROM lookup_3d_raw r
    JOIN lookup_2d f USING (ev_b, la_b)
""")

n_cells = con.execute("SELECT COUNT(*) FROM lookup_3d").fetchone()[0]
n_thin = con.execute("SELECT COUNT(*) FROM lookup_3d WHERE n < 20").fetchone()[0]
print(f"  3D cells: {n_cells} (with EB shrinkage k={SHRINK_K})")
print(f"  Thin cells (n<20, dominated by 2D fallback): {n_thin}")
print()

# ─── Step 3: per-player BIP contribution under 3D model ──────────────────────
con.execute("""
    CREATE OR REPLACE TABLE bip_contrib_3d AS
    SELECT
        a.player_id,
        COUNT(*) AS bip,
        SUM(b.p_ba) AS sum_xh,
        SUM(b.p_slg) AS sum_xtb,
        SUM(b.p_woba) AS sum_xwoba_bip
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    JOIN lookup_3d b ON
        b.ev_b = CASE WHEN a.exit_velo < 70 THEN 0 WHEN a.exit_velo < 80 THEN 1
                      WHEN a.exit_velo < 90 THEN 2 WHEN a.exit_velo < 100 THEN 3 ELSE 4 END
    AND b.la_b = CASE WHEN a.launch_angle < 0 THEN 0 WHEN a.launch_angle < 10 THEN 1
                      WHEN a.launch_angle < 20 THEN 2 WHEN a.launch_angle < 30 THEN 3
                      WHEN a.launch_angle < 40 THEN 4 ELSE 5 END
    AND b.hit_loc = a.hit_loc
    WHERE EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) = 2029
      AND a.result IN (4,5,6,7,8,9) AND a.sac = 0
      AND a.exit_velo > 0 AND a.launch_angle IS NOT NULL
    GROUP BY a.player_id
""")

con.execute("""
    CREATE OR REPLACE TABLE pa_breakdown AS
    SELECT
        a.player_id,
        COUNT(*) AS pa,
        COUNT(*) FILTER (WHERE a.result = 1) AS k,
        COUNT(*) FILTER (WHERE a.result = 2) AS bb,
        COUNT(*) FILTER (WHERE a.result = 10) AS hbp,
        COUNT(*) - COUNT(*) FILTER (WHERE a.result = 2)
                 - COUNT(*) FILTER (WHERE a.result = 10)
                 - COUNT(*) FILTER (WHERE a.sac > 0) AS ab
    FROM at_bats a
    JOIN games g ON g.game_id = a.game_id AND g.game_type = 0
    WHERE EXTRACT(YEAR FROM TRY_CAST(g.date AS DATE)) = 2029
    GROUP BY a.player_id
""")

con.execute("""
    CREATE OR REPLACE TABLE player_xstat_3d AS
    SELECT
        p.player_id, p.pa, p.ab, p.k, p.bb, p.hbp, bc.bip,
        ROUND(bc.sum_xh / NULLIF(p.ab, 0), 3) AS x_ba,
        ROUND(bc.sum_xtb / NULLIF(p.ab, 0), 3) AS x_slg,
        ROUND((bc.sum_xwoba_bip + 0.69*p.bb + 0.72*p.hbp)
              / NULLIF(p.ab + p.bb + p.hbp, 0), 3) AS x_woba
    FROM pa_breakdown p
    LEFT JOIN bip_contrib_3d bc ON bc.player_id = p.player_id
""")

# ─── Step 4: compare to IE ────────────────────────────────────────────────────
print("=" * 78)
print("3D MODEL vs IE — top 25 high-BIP players")
print("=" * 78)
print(f"  {'name':<28} {'BIP':>5}  {'IE xBA':>7}  {'der xBA':>7}  {'d':>6}  "
      f"{'IE xSLG':>7}  {'der xSLG':>7}  {'d':>6}  {'IE xwOBA':>8}  {'der xwOBA':>8}  {'d':>6}")
rows = con.execute("""
    SELECT
        ie."Name" AS name,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."BIP" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_bip,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
        TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
        ps.x_ba, ps.x_slg, ps.x_woba, ps.bip
    FROM ie_bs1 ie
    JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
    LEFT JOIN player_xstat_3d ps ON ps.player_id = p.player_id
    WHERE TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) IS NOT NULL
      AND ps.bip IS NOT NULL
    ORDER BY ie_bip DESC NULLS LAST
    LIMIT 25
""").fetchall()
for r in rows:
    name, ie_bip, ie_xba, ie_xslg, ie_xwoba, x_ba, x_slg, x_woba, bip = r
    d_ba = (x_ba - ie_xba)
    d_slg = (x_slg - ie_xslg)
    d_woba = (x_woba - ie_xwoba)
    print(f"  {name:<28} {ie_bip or 0:>5.0f}  {ie_xba:>7.3f}  {x_ba:>7.3f}  {d_ba:>+6.3f}  "
          f"{ie_xslg:>7.3f}  {x_slg:>7.3f}  {d_slg:>+6.3f}  "
          f"{ie_xwoba:>8.3f}  {x_woba:>8.3f}  {d_woba:>+6.3f}")

print()
agg = con.execute("""
    WITH joined AS (
        SELECT
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
            ps.x_ba, ps.x_slg, ps.x_woba
        FROM ie_bs1 ie
        JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
        LEFT JOIN player_xstat_3d ps ON ps.player_id = p.player_id
    )
    SELECT
        COUNT(*) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL) AS n,
        ROUND(AVG(ABS(x_ba - ie_xba)) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL), 4) AS mae_ba,
        ROUND(AVG(ABS(x_slg - ie_xslg)) FILTER (WHERE ie_xslg IS NOT NULL AND x_slg IS NOT NULL), 4) AS mae_slg,
        ROUND(AVG(ABS(x_woba - ie_xwoba)) FILTER (WHERE ie_xwoba IS NOT NULL AND x_woba IS NOT NULL), 4) AS mae_woba,
        ROUND(corr(x_ba, ie_xba) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL), 3) AS r_ba,
        ROUND(corr(x_slg, ie_xslg) FILTER (WHERE ie_xslg IS NOT NULL AND x_slg IS NOT NULL), 3) AS r_slg,
        ROUND(corr(x_woba, ie_xwoba) FILTER (WHERE ie_xwoba IS NOT NULL AND x_woba IS NOT NULL), 3) AS r_woba,
        -- with bias removed (r is shift-invariant; this is just to confirm)
        ROUND(AVG(x_ba - ie_xba) FILTER (WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL), 4) AS bias_ba,
        ROUND(AVG(x_slg - ie_xslg) FILTER (WHERE ie_xslg IS NOT NULL AND x_slg IS NOT NULL), 4) AS bias_slg,
        ROUND(AVG(x_woba - ie_xwoba) FILTER (WHERE ie_xwoba IS NOT NULL AND x_woba IS NOT NULL), 4) AS bias_woba
    FROM joined
""").fetchone()

print(f"  3D-model fit (n={agg[0]} player pairs):")
print(f"    MAE  xBA  : {agg[1]:.4f}    Pearson r: {agg[4]}    bias: {agg[7]:+.4f}")
print(f"    MAE  xSLG : {agg[2]:.4f}    Pearson r: {agg[5]}    bias: {agg[8]:+.4f}")
print(f"    MAE  xwOBA: {agg[3]:.4f}    Pearson r: {agg[6]}    bias: {agg[9]:+.4f}")
print()

# ─── Step 5: bias-corrected fit (subtract mean delta) ────────────────────────
print("  After bias correction (subtract mean delta from derived):")
agg2 = con.execute("""
    WITH joined AS (
        SELECT
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
            ps.x_ba, ps.x_slg, ps.x_woba
        FROM ie_bs1 ie
        JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
        LEFT JOIN player_xstat_3d ps ON ps.player_id = p.player_id
    ),
    biased AS (
        SELECT
            ie_xba, ie_xslg, ie_xwoba,
            x_ba - AVG(x_ba - ie_xba) OVER () AS x_ba_c,
            x_slg - AVG(x_slg - ie_xslg) OVER () AS x_slg_c,
            x_woba - AVG(x_woba - ie_xwoba) OVER () AS x_woba_c
        FROM joined
        WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL
    )
    SELECT
        ROUND(AVG(ABS(x_ba_c - ie_xba)), 4),
        ROUND(AVG(ABS(x_slg_c - ie_xslg)), 4),
        ROUND(AVG(ABS(x_woba_c - ie_xwoba)), 4),
        ROUND(100.0 * AVG(CASE WHEN ABS(x_ba_c - ie_xba) <= 0.010 THEN 1.0 ELSE 0 END), 1) AS m_ba,
        ROUND(100.0 * AVG(CASE WHEN ABS(x_slg_c - ie_xslg) <= 0.020 THEN 1.0 ELSE 0 END), 1) AS m_slg,
        ROUND(100.0 * AVG(CASE WHEN ABS(x_woba_c - ie_xwoba) <= 0.015 THEN 1.0 ELSE 0 END), 1) AS m_woba
    FROM biased
""").fetchone()
print(f"    MAE  xBA  : {agg2[0]:.4f}    match-rate (+/-0.010): {agg2[3]}%")
print(f"    MAE  xSLG : {agg2[1]:.4f}    match-rate (+/-0.020): {agg2[4]}%")
print(f"    MAE  xwOBA: {agg2[2]:.4f}    match-rate (+/-0.015): {agg2[5]}%")
print()

# ─── Step 6: same but only high-BIP players (>=200 BIP) ─────────────────────
print("  Restricted to BIP >= 200 (real samples, not cup-of-coffee):")
agg3 = con.execute("""
    WITH joined AS (
        SELECT
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xba,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xSLG" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xslg,
            TRY_CAST(REPLACE(NULLIF(CAST(ie."xwOBA" AS VARCHAR), '-'), ',', '') AS DOUBLE) AS ie_xwoba,
            ps.x_ba, ps.x_slg, ps.x_woba, ps.bip
        FROM ie_bs1 ie
        JOIN players p ON LOWER(p.first_name || ' ' || p.last_name) = LOWER(ie."Name")
        LEFT JOIN player_xstat_3d ps ON ps.player_id = p.player_id
        WHERE ps.bip >= 200
    )
    SELECT
        COUNT(*) AS n,
        ROUND(AVG(ABS(x_ba - ie_xba)), 4),
        ROUND(AVG(ABS(x_slg - ie_xslg)), 4),
        ROUND(AVG(ABS(x_woba - ie_xwoba)), 4),
        ROUND(corr(x_ba, ie_xba), 3),
        ROUND(corr(x_slg, ie_xslg), 3),
        ROUND(corr(x_woba, ie_xwoba), 3),
        ROUND(AVG(x_ba - ie_xba), 4),
        ROUND(AVG(x_slg - ie_xslg), 4),
        ROUND(AVG(x_woba - ie_xwoba), 4)
    FROM joined
    WHERE ie_xba IS NOT NULL AND x_ba IS NOT NULL
""").fetchone()
print(f"    n={agg3[0]} players")
print(f"    MAE  xBA  : {agg3[1]:.4f}    Pearson r: {agg3[4]}    bias: {agg3[7]:+.4f}")
print(f"    MAE  xSLG : {agg3[2]:.4f}    Pearson r: {agg3[5]}    bias: {agg3[8]:+.4f}")
print(f"    MAE  xwOBA: {agg3[3]:.4f}    Pearson r: {agg3[6]}    bias: {agg3[9]:+.4f}")
print()
