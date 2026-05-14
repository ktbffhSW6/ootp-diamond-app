# OOTP Data Quirks — Master Reference

> **Single source of truth for every OOTP-data quirk, formula calibration,
> permanent limitation, and display-policy decision we've discovered.**
>
> **Use this file before re-investigating anything.** If a stat is misbehaving
> and there's an entry here, the answer is here. Deep-dive investigations
> live in `DATA_NOTES.md` (chronological log); decisions live in
> `DECISIONS.md` (architectural commitments). This file is the index that
> says *"yes, we already figured that out — here's where we landed."*
>
> Last consolidated: **2026-05-14** (Phase 4b chain: L_IE routing + POW-aware
> calibration + Tier A/B/D + D40 watchdog + career-event scope fix).

---

## Table of contents

1. [How to use this file](#how-to-use-this-file)
2. [Display-policy rule (the one mental model)](#display-policy-rule)
3. [Encoding quirks](#encoding-quirks) — physical properties of the dump
4. [Formula calibrations](#formula-calibrations) — every constant we calibrated
5. [Permanent limitations (sealed)](#permanent-limitations-sealed) — won't reach 100%
6. [Display policy ledger](#display-policy-ledger) — what's hidden + why
7. [Reconcile workflow](#reconcile-workflow) — how to keep this honest
8. [The lost-work hall of fame](#the-lost-work-hall-of-fame) — things we forgot + rediscovered

---

## How to use this file

**When you see a reconcile mismatch, when a calibration "feels off," when
you're tempted to grid-search something** — first check the relevant
section here. Every entry has the form:

- **Item** — what it is
- **Status** — `SEALED` / `CALIBRATED` / `PERMANENT` / `DEFERRED`
- **Value / formula** — the actual number or shape
- **Why** — one-line reason
- **When + where** — commit + deep-dive pointer

`SEALED` means **don't re-investigate** without new evidence (different
save, OOTP version bump, fundamentally new data). The history of
re-litigation is too long. See "lost-work hall of fame" at the bottom.

---

## Display-policy rule

> **The single rule: any column where Diamond's value can differ from OOTP IE
> display by more than rounding noise (≥ ~5pp) is hidden from the UI.**
>
> *(Phase 4a-extended-3, commits `cd422af` + `169ad0c`, 2026-05-10.)*

- The reconcile harness still computes the value and compares to IE — that's
  the drift watch.
- The L3 builder still materializes it — that's an invariants-watchdog input
  for Phase 4b's `_diamond_invariants` table.
- It just doesn't reach the user-facing surfaces (player page, roster page,
  leaderboards, chart builder, cockpit, compare).

The Diamond user invariant is: **"Any number you see in the app matches what
OOTP shows in the game, within rounding."** Things that can't satisfy that
invariant are silently dropped from display until the L_IE display-routing
path (see [deferred work](#deferred-work)) is built.

---

## Encoding quirks

Physical / structural quirks of the dump CSV format. **None of these are
guessable** — they had to be discovered empirically.

### Per-PA log (`players_at_bat_batting_stats.csv`)

| Quirk | Value | Why it matters | Found |
|---|---|---|---|
| `hit_xy` is **batter-relative** | range `[0, 255]`; 0=pull, 128=center, 255=oppo regardless of bat hand | LHB + RHB HRs both cluster at mean `hit_xy ≈ 71` (low = pull for both). Don't apply handedness adjustment when classifying spray; do apply when rendering on a stadium overlay. | D39, re-confirmed Phase 4a-ext-2 |
| `hit_xy` **encoding is 1D direction**, not a packed coord | `avg(hit_xy)` over a player's BIPs has `r = 0.17` correlation with IE Pull%. Top-10 pull hitters have `avg_xy = 128`; bottom-10 = 126. **OOTP's IE Pull% uses internal sim features** (bat-hand × pitch type × swing angle) not exposed in dumps. | Pull/Cent/Oppo% is structurally unreachable. | Phase 4a-ext-2 |
| `hit_loc` is **sparse codes 0-87** | codes 0-43, 79, 85, 87 observed | `hit_loc ≤ 22 = infield zone` (12× count jump at the 22/23 boundary). Multi-dim refinement for `IFH`: `hit_loc ≤ 30 AND EV < 95 AND LA < 5`. | Phase 4a #5 + ext-2 |
| `sac=1` = sac bunt; `sac=2` = sac fly | IE BIP **includes both** | Don't filter `sac=0` when counting BIP. Probe: 59/78 exact match without filter vs 7/78 with. | Phase 4a-ext |
| CSV order is meaningful | grouped by batter; `file_seq` order within `(game_id, player_id)` is chronological | `pa_in_game_seq = ROW_NUMBER() OVER (PARTITION BY game_id, player_id ORDER BY file_seq)`. Used for the at-bat-event PK. | OPEN-4 |
| `game_id` is **recycled across seasons** | Integer 10001 is one game in 2026-08, a different game in 2027-09. | PK on `f_pa_event` must include `year`. | D11 era |
| `result` codes | 1=K, 2=BB, 4=GO, 5=FO, 6=1B, 7=2B, 8=3B, 9=HR, 10=HBP, 11=CI | BIP = `result IN (4,5,6,7,8,9)`. Don't add `sac=0`. | OPEN-1 |
| **OOTP EV scale runs ~5 mph below real-MLB Statcast** | save league-avg EV ~83 mph vs real ~88-89; top-end avg-EV stars sit ~5-7 mph below their real counterparts | When `f_record_player` UNIONs save EV records with `history_statcast_*`, the `source` column distinguishes. Don't compare across sources. | D8 era |

### Per-player / per-team / per-league snapshots

| Quirk | Value | Why | Found |
|---|---|---|---|
| `players_pitching.csv` | 0 of 67 rating cols populated when scouting mode is on (standard) | **Not in L0**. Skip. Pitching ratings live in `players_scouted_ratings`. | OPEN-1, D19 |
| `players_batting.csv` | only 4 of 42 cols are populated (`running_ratings_*`) | Fold those 4 cols into `players_snapshot`; drop the rest. | OPEN-1 |
| `players_fielding.csv` zero values | mean "never rated / never played there" | Surface as `NULL` in API so UI shows `—` unambiguously. | Phase 2 |
| Same `league_id` at **multiple `level_id`s** | OOTP's 2021 MiLB reorg reclassified leagues 209-213 + 252 between L4 (modern) and L6 (historical). | `milb_levels_per_league` must be PLURAL — fan out per (league_id, level_id). Using `MIN(level_id)` leaves L6 historical rows orphan. | Phase 4a #3 |
| `players_career_*_stats.csv` natural-key dups | `(player_id, year, team_id, league_id, level_id, split_id, stint)` has OOTP-source dups | L1 uses synthetic PK `(dump_date, file_seq)`; L2 aggregates with SUM-over-natural-key. Pattern verified in audit Phase C. | OPEN-6 |
| `players_career_pitching_stats.csv` has native `gb` / `fb` cols | (pitcher-allowed counts) | Batting side does NOT have native GB/FB — must derive from PA log. | Phase 4a-ext-2 |
| `players_individual_batting_stats.csv` | 5 cols total: `player_id, opponent_id, ab, h, hr` | Use for batter-vs-pitcher matchup history; sparse but accurate. | OPEN-1 |
| `players_streak.csv` `ended` field | ~0.15% NULL (active streaks); also boundary dups | PK includes `COALESCE(ended, '9999-12-31')` to disambiguate. | OPEN-5 |
| `players_at_bat_batting_stats.csv` PA log scope | **Missing for DSL/foreign-league players** entirely. Padres corpus: 37 players had IE BIP > 0 but ZERO L0 PA rows. | `f_pa_event` can't reach them. Use PCB summary (`AB - K + SF + SH`) for BIP-as-display. | Phase 4a-ext |

### Reference data + L_REF

| Quirk | Value | Why | Found |
|---|---|---|---|
| `lref_xiso_table.txt` is NOT a (LA, EV) → LSA classifier | It's a **6×4 histogram** of (launch_speed_angle bucket × outcome). Useful for downstream xISO calc once LSA is assigned, but doesn't classify. | The (LA, EV) → LSA classifier must be **reverse-engineered** from per-player IE ground truth. We did that for LSA=6 (barrel) in Phase 4a-ext-3 — see [barrel calibration](#barrel-formula). | Phase 4a-ext-3 |
| `lref_xwoba/xba/xslg_table.txt` | 106 rows × 61 cols: `launch_angle` × `exit_velo` → expected stat | Bilinear interpolate per BIP, then aggregate across player's BIPs. Empirical scalers required (see calibrations). | D26+D27, D39 |
| `lref_era_stats_minors` MiLB league coverage | 11 leagues covered: IL, PCL, EL, SL, TL, NWL, SAL, MWL, CAL, CAR, FSL + American Association + Pioneer (added Phase 4a #3) | L5/L6/L7/L8 foreign/complex/independent leagues are NOT covered. Pre-2026 player-seasons there resolve `NULL` for OPS+/wRC+/etc. — permanent. | D29 Slice 5 + Phase 4a #3 |
| L_REF is **frozen at first ingest** | per save. Refresh via `diamond ingest --refresh-lref` with SHA1 diff preview. | Mirrors OOTP engine convention — reference data is captured at save creation. Mid-version OOTP patches don't retroactively shift advanced stats. | D27 |

### Date / ID conventions

| Quirk | Value | Why | Found |
|---|---|---|---|
| `dump_date` is **end-of-month** | `dump_YYYY_MM` is exported when OOTP advances *into* `MM+1`, so it represents data through last day of MM. | `dump_name_to_date()` returns `date(y, m, last_day_of_month)` via `calendar.monthrange`. Run `diamond migrate-dump-dates` once on legacy warehouses (idempotent via `_diamond_settings.dump_date_convention = 'end_of_month'`). | D36 |
| Several L0 ID cols come in as VARCHAR | `l0_trade_history.{team_id_0/1, player_id_0_*/1_*, message_id, date}` + `l0_league_playoff_fixtures.{league_id, team_id0, team_id1}`. DuckDB `read_csv_auto` parks them as VARCHAR when adjacent column variance confuses inference. | All scope filters in `l1_event.py` wrap LHS in `TRY_CAST(... AS BIGINT)`. NULL-on-failure safely excludes non-numeric rows. | D36 |
| OOTP IE Pull% / Cent% / Oppo% are NOT events-derived | They use internal sim features (bat-hand × pitch type × swing angle) that aren't exposed in dumps. | Whatever IE displays, we can't reproduce from `hit_xy` alone. Tested every encoding × cutoff combo; ceiling MAE ~7pp per col. | Phase 4a-ext-2 |
| OOTP IE "Soft / Med / Solid" is EV-bucketing, NOT LSA-banding | Tested LSA bands {1+2}/{3+4}/{5+6} → MAE 12.4/5.3/8.8 vs EV-cutoffs (76, 95) at MAE 1.7/2.1/1.2. | Stick with EV cutoffs (Phase 4a #4). | Phase 4a-ext-3 |
| IE org-roster aggregate **excludes foreign-league stints** | A Padres player who played in KBO (L8) or Caribbean Winter (L11) — IE shows only their Padres-org stats. | PCB-BIP `level_id BETWEEN 1 AND 6` filter is correct. Widening to no-filter regressed match rate by 1pp. | Phase 4a-ext-2 |

### Warehouse-build architecture quirks

| Quirk | Value | Why it matters | Found |
|---|---|---|---|
| **L1 event tables collapse to MAX(dump_date)** | Every `players_career_*_event` and similar is filtered `WHERE dump_date = (SELECT MAX(dump_date) FROM source_l0)`. Per-dump history is **NOT** retained at L1. | Tier B history snapshots (`f_*_history`) MUST source from L0 directly. The L1 collapse is intentional (correctness + performance for normal queries) but invisible if you don't read `l1_event.py`. | Phase 4b Tier B 2026-05-14 |
| **`_scoped_players` is snapshot-based** | Built from `l0_players` (current-team snapshot) where `team_id IN _scoped_teams`. Retired/released players have `team_id=0` in the snapshot → excluded → their PRIOR stints on scoped teams get dropped. | D40 watchdog flagged this — 7 real `team_pa_count` reds on Padres (team 274 in 2026 L4 was off by 79 PA from missing player Raphael Gladu). **Fix**: career-stint event tables switched from `_SCOPE_PLAYER` to `_SCOPE_TEAM` (commit `8137ab3`). `_scoped_players` itself stays snapshot-based for UI surfaces (Cockpit "Players in scope" count). | D40 + Phase 4b 2026-05-14 |
| **OOTP doesn't cache team-level wOBA** | `f_team_season_batting_ootp.woba` is 0.0 for ALL 3,647 rows in this OOTP version. | Can't use OOTP cache as the dump-side comparator for team_woba invariant. Dropped from the watchdog catalog; revisit if a future OOTP version populates it. | Phase 4b D40 2026-05-14 |
| **OOTP team_history vs career_batting can disagree by 1-2 PA** | Boston 2026 MLB: `team_history.pa = 6226` vs SUM of latest-dump player_career_batting_stats = 6228. Delta = -2 PA. | Our derivation exactly matches the L0 player-career sum (correct). The discrepancy is INSIDE OOTP between its team-level cache and per-player career table. Documented as "informational" red on the watchdog; not a Diamond bug. | Phase 4b D40 2026-05-14 |
| **L_IE export is point-in-time, requires manual export** | `<save>/import_export/*.csv` is generated by OOTP's "Reports → Roster Exports" UI action. NOT auto-refreshed on sim advance. | L_IE routing pulls bit-for-bit OOTP IE values, but they reflect "what OOTP UI showed when user last exported." Diamond DROPs and recreates `lie_*` tables on every warehouse refresh (unlike L_REF which is frozen). | D41 + L_IE Slice 1 2026-05-14 |
| **L_IE export is org-only** | The export contains the active org's ~270-player current-year roster. Multi-stint players (mid-season call-ups) appear with ONE aggregate row, not per-stint. | L_IE routing applies via single-stint-only eligibility predicate. Multi-stint years (10-15 batters per save) keep per-stint derivations. | L_IE Slice 1 2026-05-14 |
| **OOTP recycles `game_id` across seasons** | `(game_id)` is NOT unique in `f_pa_event` or `l0_games`. PK requires `(year, game_id)`. | Tier A + Tier B + f_pa_event PKs include `year` for this reason. New L0 builders must follow suit. | D17 / Phase 4b 2026-05-14 |

---

## Formula calibrations

Every constant and formula shape we've calibrated against OOTP IE.
**Don't re-grid-search without a reason.** See `audit/reconcile.py`
ColSpec notes for per-column citations.

### Sabermetric core

| Stat | Formula / value | Notes | Calibrated |
|---|---|---|---|
| **wOBA** | `(0.69·uBB + 0.72·HBP + 0.89·1B + 1.27·2B + 1.62·3B + 2.10·HR) / PA` | Base linear weights × PA denominator. **NOT** the FanGraphs (AB+uBB+SF+HBP) form with lg-OBP-scaled weights — those formulas diverge by .015-.020 for minor leaguers with SH>0. Lives in `l3_advanced.py:woba_calc` + `reconcile.py:BATTING_DERIVED_CTE`. | D38 |
| **lg_woba** | `base_lg_woba` (base weights × `lg_pa` denom) | NOT `lg_obp`. Computed in `_lg_constants_advanced_native` / `_imported`. | D38 |
| **OPS+** | `100 × (OBP/lgOBP + SLG/lgSLG - 1) / park_avg_half`, where `park_avg_half = 1 + (avg - 1)/2` | Park factor halved. | D11 era |
| **ERA+** | `100 × lgERA / ERA / park_avg_80`, where `park_avg_80 = 1 + (avg - 1) × 0.8` | Park factor at 80% of full. Verified Crochet 2029 ERA+ 127 vs IE 127 at Fenway. | D11 era |
| **Park factor** | LH/RH split per `players_current.bats`. Switch hitters: 60% LH / 40% RH blend per Tango. | Pre-2026 uses `lref_era_ballparks`; modern falls through to `parks.avg`. | D29 Slice 3 |
| **bWAR / pWAR / RA9_WAR** | **OOTP-supplied directly** as `players_career_*.war` / `.ra9war`. IE A-tier reconciled. | DO NOT recompute. Custom `o_war` + `pit_war` are inspectable alternatives only. | Phase 2 |
| **FIP** | `(13·HR + 3·(BB+HBP) - 2·K) / IP + cFIP`, where `cFIP = lg_ERA - lg_(13·HR + 3·(BB+HBP) - 2·K) / lg_IP` | lg constants from `lref_era_stats` (pre-2026) or `f_league_season` (2026+). | D11 era |
| **SIERA** | Standard FanGraphs SIERA, 8 components | Decoded in commit `011338b`. | May 2026 |
| **Runs-per-PA** | `runs_per_pa = lg_runs / lg_pa` per (league, year, level) | Used in wRC+ + wRAA. | D11 |
| **Replacement level** (pit_WAR custom) | Flat 1.13 lg-runs-per-replacement-PA | Custom, not OOTP-canonical. `pWAR` is the OOTP-canonical one. | D39 era |

### Batted-ball + Statcast

| Stat | Formula / value | Notes | Calibrated |
|---|---|---|---|
| **BIP** | `result IN (4,5,6,7,8,9)` — **NO sac filter** | IE BIP includes sacs (both bunts and flies). Probe: 59/78 exact vs 7/78 with `sac=0`. | Phase 4a-ext |
| **BIP (display)** | `AB - K + SF + SH` summed across `level_id BETWEEN 1 AND 6` from PCB (`f_player_season_batting`) | 96-98% match vs PA-event count 91%. Closes DSL/foreign gap. L7-L8 widening REGRESSED by 1pp (IE excludes them). | Phase 4a-ext + ext-2 |
| **LA buckets** | GB `< 11`, LD `[11, 25]`, FB `[26, 50]`, PU `≥ 51` | Was 12/27/52 pre-ext. Re-grid-searched after BIP fix; MAE 1.54pp vs 2.54pp. | Phase 4a-ext |
| **GB/FB ratio** | `GB / (FB + PU)` (popups count as FB-side) | Verified MAE 0.21 vs alt `GB/FB` MAE 0.76. | Phase 4a-ext |
| **EV cutoffs (Soft/Med/Solid)** | Soft `< 76`, Avg/Med `76–94`, Solid `≥ 95` | 95-mph solid floor matches MLB-Statcast hard-hit convention exactly. Grid-searched 74 batters × 12,506 BIP. | Phase 4a #4 |
| **Barrel cone** | `EV ≥ 97 AND LA ∈ [26 − (EV−97), 30 + (EV−97)]`, capped at LA `[8, 50]` | Expanding cone centered at LA=28. **Almost identical to Statcast canonical** (Savant uses EV ≥ 98); OOTP runs 1 mph lower. Reverse-engineered from per-player IE BAR ground truth. | Phase 4a-ext-3 |
| **Hard-hit %** | `EV ≥ 95` | Statcast convention. 94-95% match. | Phase 4a #4 |
| **Sweet-spot %** | `LA ∈ [8°, 32°]` | Statcast convention. NO OOTP IE counterpart — Diamond-custom. Dropped from UI Phase 4a-ext-3. | (Statcast convention) |
| **max_ev** | 90th-percentile EV, **NOT** absolute peak | Statcast convention. Absolute peak is single-event noise. 97% match. | D8 era |
| **HHi / HHi%** | Hard-hit-index count + % (HHi = count at EV ≥ 95; HHi% = HHi/BIP) | 94% / 95% match. | D8 era |
| **IFH** | `result = 6 AND LA < 5 AND hit_loc ≤ 30 AND exit_velo < 95` | Multi-dim. Denominator = all GBs (FanGraphs canonical). MAE 3.09pp. Single-dim `hit_loc ≤ 22` was 3.54pp. | Phase 4a-ext-2 |

### Expected stats (x-stats)

| Stat | Formula / value | Notes | Calibrated |
|---|---|---|---|
| **xBA scaler** | `1.22` × `SUM(xba_pa over BIPs) / AB` | `xba_pa` from bilinear-interpolated `lref_xba_table`. Without scaler, under-reports by ~22%. Grid-searched: 63/73 exact at 1.21, 62/73 at 1.22 (essentially tied). Kept 1.22. | D39, re-verified ext-2 |
| **xSLG scaler** | `1.09` × `SUM(xslg_pa over BIPs) / AB` | 60-61/73 exact at 1.07-1.09 (essentially flat). Kept 1.09. | D39 |
| **xwOBA scaler** | `1.03` × `(SUM(xwoba_pa over BIPs) + 0.69·uBB + 0.72·HBP) / PA` | Was no-scaler. Grid-searched: 63/73 exact at 1.03 vs 52/73 with no scaler. | Phase 4a-ext-2 |
| **xERA formula** | `19.5 × xwOBA − 2.5` | Refit after xwOBA scaler change. MAE 0.146 / 67/71 within ±0.40. Prior `21.5·xwOBA − 2.65` (calibrated against no-scaler xwOBA) regressed to MAE 0.42 once the scaler was applied. | Phase 4a-ext-2 |
| **Integer-EV interpolation** | At integer EV, treat as the floor-value (no zero-bug) | The original interpolation collapsed at integer EV. D39 fix: `CASE WHEN ev_ceil = ev_floor THEN floor_val ELSE bilinear` | D39 |

### Reference-data + scoping

| Item | Value | Notes | When |
|---|---|---|---|
| **Game type filter** | `game_type = 0` (regular season) everywhere stats are computed | Excludes spring (`game_type=2`) and playoffs (`game_type=4`). IE display uses regular season only. | D39 |
| **MiLB league crosswalk** | 13 leagues: IL, PCL, EL, SL, TL, NWL, SAL, MWL, CAL, CAR, FSL, **+ American Association (237), + Pioneer (253)** | Last two added Phase 4a #3. Each crosswalk row produces baselines for ALL levels the league appears at (fan-out). | D29 Slice 5 + Phase 4a #3 |
| **Pre-2026 MiLB level fan-out** | `milb_levels_per_league` is PLURAL — one row per (league_id, level_id) seen in `f_player_season_batting` | OOTP's 2021 reorg means leagues 209-213 + 252 sit at BOTH L4 (modern) and L6 (historical). Old `MIN(level_id)` left L6 rows orphan. | Phase 4a #3 |
| **In-progress season league constants** | For year `Y` mid-season: `_lg_constants_advanced_native` falls back to aggregating from `f_player_season_*` when `league_history_*_stats` has no rows yet | OOTP only writes `league_history_*_stats.csv` for completed seasons. Mid-July Padres dump had zero 2028 rollup rows. | D37 |

---

## Permanent limitations (sealed)

These items have been investigated to exhaustion. **Do not re-investigate
without new evidence (different save, OOTP version bump, new data source).**

### Spray direction (Pull% / Cent% / Oppo%) — `SEALED`

- **Match**: 38-54% per column at best
- **Why**: `hit_xy` has `r = 0.17` correlation with per-batter Pull%. Top-10 pull
  hitters have `avg_xy = 128`; bottom-10 = 126. OOTP's IE Pull% uses internal
  sim features (bat hand × pitch type × swing angle) **never written to any
  dump column**.
- **Tested encodings that all hit ~7pp MAE floor**: 1D batter-relative,
  1D stadium-relative + handedness, 16×16 packed grid (x % 16 + y / 16),
  BIP-subset filters (hits-only, outs-only, FB+LD-only, etc.), 2D hit_xy ×
  hit_loc combinations.
- **Status**: dropped from UI (commit `cd422af`). Spray chart kept (renders
  individual events correctly after the `[0, 255]` clipping fix).
- **Recon ColSpecs**: marked `SEALED Phase 4a-ext-3` — kept only as drift watch.
- **Deep dive**: DATA_NOTES.md "Phase 4a-extended-2 deep-dives" + ext-3.

### F-tier pitch-tracking 36 columns — `PERMANENT`

`whiff%`, `zone%`, `chase%`, `csw%`, per-pitch-type splits, etc. across
`batting_superstats_2` + `pitching_superstats_2`. **OOTP doesn't write per-pitch
zone or type to any dump**. The per-PA `players_at_bat_batting_stats.csv`
records `result + hit_loc + hit_xy + exit_velo + launch_angle + sprint_speed` —
no pitch-level metadata.

- **Match**: 0%
- **Status**: F-tier per D8 (formalized D40). Always renders `—` in recon.
  Not surfaced in UI.

### League-leader codes 44, 49 — `PERMANENT`

- 58 of 60 league-leader category codes mapped (97%).
- Codes 44 + 49 are pitching rate stats with no clean alignment to any
  Diamond-computed metric. Likely OOTP-internal categories with no public
  formula.

### OOTP "developed pitch" state — `PERMANENT`

- Shea Sprague PIT mismatch (and similar) — appears to be stub state in
  current scouting mode.

### DSL / foreign-league PA event log — `PERMANENT` (data-availability)

- 37+ players in any Padres-org IE roster have summary BIP > 0 but **zero rows
  in `l0_players_at_bat_batting_stats`**. OOTP doesn't write a PA log for
  DSL / KBO / Pioneer / Caribbean Winter games.
- **Status**: `f_pa_event` can't reach them. Workarounds: PCB summary
  formula (`AB - K + SF + SH`) for BIP-as-display; null rate stats elsewhere.

### BUH%, BAR count — `PERMANENT` (sparse / integer noise)

- **BUH%** (Bunt Hit %): 0-3 bunts per season per batter typical; with denom
  < 5, a single bunt swings % by 20+pp. 68% match within ±3pp.
- **BAR** (integer Barrel count): per-player ±1 noise on integer count.
  67% exact / 67/74 within ±1. The COUNT is structurally noisy; **BAR%
  (the rate) is at 94%** — that one's fine.

### Multi-stint OPS+ / ERA+ display discrepancy — `BY DESIGN`

- **D11 architecture**: rate stats are never rolled up across levels.
  `f_player_season_advanced_*` produces one row per (player, year, league, level).
- IE displays a combined org-roster aggregate. Reproducible via PA-weighted
  aggregation of our per-level rows to within **±2 OPS+ for the median
  multi-stint player**.
- Outlier gaps (>20 OPS+) come from foreign / winter-league stints that
  IE's org-roster display excludes — not a formula bug.
- **No formula change.** Earlier hypothesis "level-weighted park factor" was
  wrong.

### MiLB pre-2026 advanced stats at L5/L6/L7/L8 — `PERMANENT` (no source)

- ~7,500 NULL OPS+ / wRC+ player-seasons at these levels.
- Permanent cause: leagues at these levels are foreign (KBO, Korean Futures,
  Dominican Rookie), rookie complex (AZ / FL Complex), modern post-1998
  independents (Atlantic, Frontier), or unknown-name OOTP-internal
  placeholder leagues — **no `lref_era_stats_minors` coverage exists**.
- Coverage closed by Phase 4a #3: L6 100% → 85%, L7 100% → 84%.

### `players_pitching.csv` — `PERMANENT` (scouting mode)

- All 67 rating cols zero in scouting mode (standard config).
- **Not in L0.** Pitching ratings live in `players_scouted_ratings`.

### `xiso_table` is NOT a classifier — `LIMITATION`

- 6×4 histogram of (LSA bucket × outcome). Not a (LA, EV) → LSA lookup.
- DATA_NOTES claim that xiso "replaces our barrel/SS/HH classification" was
  aspirational. To use xiso, we still need to **reverse-engineer the
  (LA, EV) → LSA classifier**. We did this for LSA=6 (barrel) in Phase 4a-ext-3.

---

## Display policy ledger

Every column we've explicitly removed from the UI, in commit order.

### Dropped 2026-05-10 (commit `cd422af` — spray)

| Surface | Column | Reason |
|---|---|---|
| Player page situational splits | `pull` / `center` / `oppo` split rows | hit_xy classification at MAE ~7pp ceiling |
| Spray chart | Pull% / Cent% / Oppo% aggregate labels | Same |
| Spray chart | rendering — KEPT (clipping fixed `[0,130]` → `[0,255]`) | 30% of events were mis-rendering on oppo foul line |
| Reconcile ColSpec notes | `Pull%` / `Cent%` / `Oppo%` tagged `SEALED Phase 4a-ext-3` | Drift watch only |

### Dropped 2026-05-10 (commit `169ad0c` — full ditch)

| Surface | Columns dropped | Reason |
|---|---|---|
| Player page Advanced batting | `xwoba_bip`, `xba_bip`, `xslg_bip`, `bip_xstat` | Per-BIP averages don't appear in OOTP IE. Scaled `xba/xslg/xwoba` at 89-92% match. |
| Player page Advanced pitching | Same 4 fields | Same. (Scaled versions on pitching side ARE at 96-97% match — could be re-enabled later via the scaled cols; see [deferred](#deferred-work).) |
| Roster Contact mode (batter + pitcher) | `BIP`, `Avg EV`, `Brl%`, `SS%` | BIP 80-82% (DSL gap), Avg EV 83-87% (per-player residual), Brl% 74% batting, SS% no IE counterpart |
| Roster Contact mode | KEPT: `Max EV` (97%), `HH%` (94-95%) | Rounding-grade matches |
| Leaderboards catalog | `AVG_EV`, `BARREL_PCT`, `SWEET_SPOT_PCT`, `xwOBA`, `xBA`, `xSLG` | Same reasoning |
| Chart Builder picker | Inherited via shared catalog | Same |

### What stays on display (≥95% match — rounding-grade)

- All counting stats, slash line, OPS+/wRC+/ERA+ at 94-99%
- bWAR / pWAR / RA9_WAR (OOTP-supplied directly, A-tier)
- wOBA, FIP, SIERA, WHIP, ERA at 94-99%
- LD%, GB%, FB% (batting + pitching), IFFB, HR/FB at 91-97%
- HHi, HHi%, Max EV at 94-97%
- xERA pitching at 97%
- xBA / xSLG / xwOBA pitching at 96-97% (NOT exposed as columns — could be via the scaled version; deferred)

### Survived (kept as L3 materializations, hidden from UI)

The L3 builders still compute everything. The intent is twofold:
1. **Reconcile drift watch** — keep comparing to IE so future OOTP version
   bumps surface as drift.
2. **Invariants watchdog inputs** for Phase 4b's `_diamond_invariants` —
   OOTP-cached values that should agree with our derivations within tolerance.

So `f_player_season_xstats_*`, `f_player_season_statcast_*`, etc. all stay
populated. They're just not surfaced in the API for the dropped columns.

---

## Reconcile workflow

> *"How do we keep this list from going stale?"*

### After ANY L3 formula change

1. **Rebuild**: `diamond ingest --rebuild-only`
2. **Reconcile against Sox**: `diamond reconcile`
3. **Reconcile against Padres**: `diamond reconcile --save "The Fathers" --ie-dir docs/helpful_files/recon/Padres`
4. Inspect `audit_output/reconciliation_report.md`. Match-rate drops are signal.
5. If a sealed column's match rate moves up, that's evidence to revisit;
   document in DATA_NOTES.md and unseal the ColSpec.

### Naming conventions for sealed work

- ColSpec note prefix: `SEALED Phase 4a-ext-N` (or whatever phase).
- File header in any L3/audit code that touches a calibration: cite the
  commit + phase that established it.
- Comments explaining "why this constant": short, with a link to either the
  grid-search probe or the deep-dive DATA_NOTES section.

### When to actually re-investigate

Re-investigate IF:
- A new save surfaces a different pattern (Padres exposed bugs latent in Sox
  for 6 weeks per D38)
- OOTP releases a version bump (re-run `make smoke` + reconcile; L_REF refresh
  may be needed via `diamond ingest --refresh-lref`)
- A new ground-truth corpus appears (different IE export, etc.)
- The recon harness flags drift on a previously-sealed column

DO NOT re-investigate just because you forgot. **This file is the memory.**

---

## The lost-work hall of fame

Cases where we **forgot a finding and re-investigated**, leaving a paper trail.
Lock these in.

### Barrel cone (re-derived Phase 4a-ext-3 after multiple empirical re-fits)

- 2026-05-04: Original `_STATCAST_BARREL_EXPR` in `l3_advanced.py` used
  Statcast canonical EV ≥ 98 expanding cone. Reconcile.py used a different
  hand-tuned flat rectangle (calibrated against 9 MLB-only Sox starters).
- 2026-05-10 Phase 4a-ext: re-grid-searched a flat rectangle on Padres
  corpus. Found `EV ≥ 99, LA[13..41]` at MAE 1.24. Called it "data limit."
- 2026-05-10 Phase 4a-ext-3: user pushed back. Re-tested cone shapes. Found
  `EV ≥ 97, LA ∈ [26 − (EV−97), 30 + (EV−97)]` at MAE 0.78 — almost identical
  to canonical Statcast (EV ≥ 98) with a 1-mph lower floor. Applied to BOTH
  recon and L3 production.

**Lesson**: when a number is 67% match and the residual is integer-counted,
try cone / ellipse / piecewise shapes before declaring it noise.

### Spray chart hit_xy clipping (broken since at least May 2026)

- D29 era (2026-05-09): `web/lib/stadiums.ts` documented hit_xy as `[0, 130]`
  with the spray chart clamping to that range.
- 2026-05-10 Phase 4a-ext-2: user pointed out the chart "felt off." Inspection:
  actual hit_xy range is `[0, 255]` (verified empirically). 30% of events
  were clipping to oppo foul line.
- Fixed in commit `cd422af`: both `fieldAngleDeg` and `StadiumSprayChart.tsx`
  filter use `[0, 255]`.

**Lesson**: assumption about a range encoded in COMMENTS is easy to lose
when the data evolves. Re-verify ranges on a new save.

### xiso_table claimed as classifier (aspirational doc, never implemented)

- 2026-05-14 L_REF Slice 1: DATA_NOTES said `xiso_table` "replaces our
  barrel / SS / HH classification."
- 2026-05-10 Phase 4a-ext-3: inspection showed it's a (LSA × outcome) histogram,
  not a (LA, EV) → LSA lookup. The promise was aspirational — the actual
  reverse-engineering wasn't done until Phase 4a-ext-3.

**Lesson**: don't mark something "done" or "wired" until it's actually
materialized + tested. Use `_assert_columns_present`-style guards (as we
did in `l2_ootp.py`).

### Multi-stint OPS+/ERA+ hypothesis was wrong (D40 BACKLOG → Phase 4a #6)

- BACKLOG had "~5-10pp error on ~12 players who split MLB/AAA in one season.
  Hypothesis: OOTP applies level-weighted park factor."
- Phase 4a #6 investigation showed median multi-stint gap is 2 OPS+ (within
  noise). Outliers are foreign/winter-league stints IE excludes from
  org-roster aggregate. D11 architecture (per-level rows) is correct.

**Lesson**: hypotheses written into BACKLOG without grounding probes can
mislead. Always test the prior data before believing the prior hypothesis.

---

## Deferred work

Things that could lift the dropped columns back into the UI later. **None
of these are blocking** — the app is in a strong, honest state without them.

### L_IE display routing — Slice 1 ✅ DONE 2026-05-14

- **Status**: SHIPPED. `src/diamond/schema/l_ie.py` ingests 21 `lie_*`
  tables (one per `<save>/import_export/*_organization_-_roster_*.csv`).
  Org-agnostic suffix discovery; DROP-and-rebuild on every warehouse
  refresh (point-in-time snapshot). Per-discipline unified views
  `v_lie_player_{batting,pitching,fielding}_display` parse OOTP display
  strings to typed numerics ready to COALESCE in API CTEs. Wired into
  `rebuild_l1_l2` after L3 build.
- **Routing live for**: `_fetch_advanced_batting` + `_fetch_advanced_pitching`
  in `routes/players.py` — single-stint players, latest year only.
  Multi-stint years keep per-stint derivations to avoid mismatching
  IE's per-player aggregate against our per-(year, level) grain.
  View-existence gated by `_view_exists` so warehouses predating L_IE
  fall through to derivations without erroring.
- **Verified**: Jackson Merrill 2028 derived wOBA=0.350 OPS+=124 bWAR=3.6
  → **L_IE-routed wOBA=0.343 OPS+=125 bWAR=3.6 (bit-for-bit OOTP IE match)**.
  Padres save: 98 batters + 114 pitchers gain bit-for-bit accuracy on
  latest-year advanced stats. Pre-routing gap distribution: OPS+ median
  2 max 25, FIP median 0.02 max 0.82, ERA+ median 3 max 186 — all eliminated.
- **Remaining slices** (deferred — diminishing returns):
  - Basic batting/pitching stints (already 99%+ exact via Python computation).
  - Fielding stats (view ready, not yet wired into `_fetch_fielding_rows`).
  - Roster + leaderboards + cockpit (same eligibility predicate; trivial wiring).
  - Per-position spray %s / BAR count / Statcast cells / IFH% / BUH% (column resurrection on the frontend; values exist in L_IE views).

### Pitching xstats re-enable — xBA + xSLG ✅ DONE 2026-05-14

- **Status**: SHIPPED. Restored `xba` + `xslg` (scaled SUM/AB values
  from `f_player_season_xstats_pitching`) on the player page pitching
  Advanced view + leaderboards catalog (`xBA_pit` / `xSLG_pit` ids;
  default 30-BIP qualifier; ascending — lower is better for pitchers).
- **Match rates** (Padres reconcile): xBA **96%**, xSLG **97%** —
  both over D41's 95% bar. xwOBA (82%) and xERA (87%) stay deferred
  until per-player calibration brings them over the bar.
- **Routing**: L_IE-routed to bit-for-bit OOTP IE for single-stint
  org-roster pitchers in latest year; L3 derivation at 96-97% match
  for everyone else. Verified end-to-end on Kempner / Vasquez / Keller
  / Doughty — IE-routed values match the IE export exactly.

### L3 per-player x-stat calibration — POW-aware ✅ DONE 2026-05-14

- **Status**: SHIPPED. Replaced flat 1.22 xBA / 1.09 xSLG scalers with
  POW-rating-aware linear corrections in `_build_f_player_season_xstats_batting`.
- **Calibration constants** (OLS fit on n=43 Padres single-stint org,
  L1-L4, BIP≥30; r ≈ 0.65 for both):
  - `xBA  correction = 0.00823 + 0.00054 · (POW - 50)`
  - `xSLG correction = 0.01527 + 0.00115 · (POW - 50)`
- **Year-aware POW lookup**: `players_ratings_snapshot` (29 monthly
  snapshots in the Padres save) provides per-(player_id, year) POW
  ratings. Pre-2026 stints (no snapshot data) → POW=50 fallback (intercept-only).
- **Padres reconcile post-calibration**:
  - xBA 89% → **95%** ← clears D41 bar
  - xSLG 89% → **93%** (under bar)
  - xwOBA batting 78% → **92%** (improved LA buckets cascade)
  - xwOBA pitching 82% → **96%** ← clears bar
  - HHi% / EV / Soft% / Avg% / Solid% all gained pp from L3 rebuild
- **Re-enables**: batting xBA + pitching xwOBA both restored on the
  player page. Batting xSLG / xwOBA stay deferred (93% / 92% — under
  bar). xERA stays out (87%).
- **Caveat**: calibration is Padres-specific. Sox / other saves may
  benefit from a per-save refit. Future work — detect calibration
  drift during ingest, re-fit if reconcile gap exceeds threshold.
- **Status**: planned, not started. Phase 4b's invariants watchdog +
  game-grain facts come first.

---

## File map

- **This file** (`DATA_QUIRKS.md`): master at-a-glance reference. Read first.
- `DATA_NOTES.md`: chronological deep-dive log. Phase 4a + ext + ext-2 + ext-3
  investigations live there with full grid-search receipts.
- `DECISIONS.md`: architectural commitments (D1-D40). Why we made each design
  call.
- `PROJECT_STATUS.md`: current phase + recent ships.
- `BACKLOG.md`: open work prioritized by phase.
- `SCHEMA.md`: warehouse layer architecture (L0 → L1 → L2 → L3 + L_REF).
- `UI_DESIGN.md`: five-tab IA, theme system, render conventions.

