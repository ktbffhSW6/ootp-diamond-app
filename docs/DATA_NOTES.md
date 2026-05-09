# OOTP Data Notes

> Empirical findings about how OOTP 27 stores and exports its data.
> Append entries as new quirks or codebooks are discovered.
> These are FACTS about the data, not decisions — see DECISIONS.md for those.

---

## Save folder layout

```
saved_games/<save_name>.lg/
├── dump/                          ← OOTP writes monthly
│   └── dump_yyyy_mm/
│       └── csv/                   ← ~70 CSV files (the dump)
├── import_export/                 ← OOTP writes when user exports a roster view
│                                    (Boston Red Sox org only at present)
└── diamond/                       ← OUR folder, OOTP doesn't touch
    ├── diamond.duckdb
    ├── diamond_config.json
    └── reconciliation/
```

## Dump file size hierarchy (largest first, dump_2029_11)

| File | MB | Notes |
|---|---|---|
| `players_at_bat_batting_stats.csv` | 100 | per-PA event log; ~1.3M rows for a season |
| `players_career_batting_stats.csv` | 82 | year × player × team × split rollups, append across seasons |
| `players_career_pitching_stats.csv` | 82 | same pattern as batting |
| `players.csv` | 45 | full player bio/contract/morale; 148K rows world-wide |
| `players_game_batting.csv` | 39 | per-game player batting log |
| `players_career_fielding_stats.csv` | 33 | year × player × position × split |

## File rollover behavior

| File family | Behavior | Implication |
|---|---|---|
| `players_at_bat_batting_stats.csv` | **Resets at season start (Feb-Mar dump).** `dump_2026_11` and `dump_2026_12` are byte-identical (95 MB). `dump_2027_03` is 3 MB (spring training only). Also: **`game_id` is recycled across seasons** — id 10001 is one game in 2026 dumps, a different game in 2027 dumps. | The Nov dump IS the canonical season at-bat snapshot. **History is recoverable**: L0 retains every previously ingested dump's rows by `dump_date`, so `f_pa_event` reaches back into L0 with cross-dump dedup keyed on (`game_id`, `season_year`) to assemble multi-year coverage. PK = (year, game_id, batter_id, pa_in_game_seq) with `year` carried for disambiguation. |
| `games.csv` | Resets at season start, same as at-bats. `game_id` recycled across years. | Same multi-year recovery via L0; `f_pa_event` JOINs `l0_games` on (`game_id`, `dump_date`) to keep at-bat-row to game-row pairing within the same dump. |
| `players_game_batting.csv` | Same reset pattern as at-bat | Same Nov-dump rule |
| `players_career_*_stats.csv` | **Append-only across seasons** | Latest dump is authoritative |
| `players_individual_batting_stats.csv` | **Append-only across seasons** (cumulative all-time matchup table: player × opponent_pitcher → ab/h/hr) | Latest dump is authoritative |

## Verified codebooks

### `games.game_type`
| Value | Meaning |
|---|---|
| 0 | REGULAR_SEASON |
| 2 | SPRING_TRAINING |
| 3 | POSTSEASON |
| 4 | EXHIBITION |
| 5 | INTERNATIONAL (WBC / friendlies) |
| 6 | SPECIAL_EVENT |
| 8 | UNKNOWN_8 (1 game observed) |

### `*_stats.split_id` (batting & pitching)
| Value | Meaning |
|---|---|
| 1 | OVERALL |
| 2 | VS_LHP |
| 3 | VS_RHP |
| 21 | POSTSEASON |

Verified: `vs_LHP + vs_RHP = OVERALL` exactly. POSTSEASON is additive (separate bucket). 2029 MLB postseason participants exactly match `players_who_have_split_id_21` — confirmed Mets won World Series vs Yankees.

### `*_fielding_stats.split_id`
| Value | Meaning |
|---|---|
| 0 | OVERALL (no platoon split for fielding) |

### `players_at_bat_batting_stats.result`
| Code | Meaning | Notes |
|---|---|---|
| 1 | STRIKEOUT | no batted ball |
| 2 | WALK | no batted ball |
| 4 | GROUND_OUT | mean LA -28°, mean EV 77 mph |
| 5 | FLY_OUT | mean LA +43°, mean EV 82 mph (incl. pop-ups) |
| 6 | SINGLE | mean LA +9°, mean EV 86 mph |
| 7 | DOUBLE | mean LA +22°, mean EV 94 mph |
| 8 | TRIPLE | mean LA +25°, mean EV 95 mph |
| 9 | HOME_RUN | mean LA +30°, mean EV 100 mph |
| 10 | HIT_BY_PITCH | no batted ball |
| 11 | CATCHERS_INTERFERENCE | rare (18 events in 2029 MLB) |

Verified by exact aggregate match: sum of all event counts for regular-season MLB 2029 = 183,906 = total overall PA. Code 3 unobserved in regular-season MLB (may appear in other game types, possibly fielders' choice or ROE).

## Decoded codebooks (second pass)

All four discovered codebooks. See `src/diamond/constants.py` for the IntEnum definitions.

### `players_awards.award_id` — all 13 codes verified

Cross-referenced against `league_history.best_hitter_id / best_pitcher_id / best_rookie_id` (217/234 MVP winners match best_hitter, 134/151 CY match best_pitcher, 164/182 RoY match best_rookie — match is per-league-per-year, top voter only).

| Code | Award | Notes |
|---|---|---|
| 0 | PLAYER_OF_THE_WEEK | ~26 winners/league/year (one per week) |
| 1 | PITCHER_OF_THE_MONTH | 6/league/year, all pitchers, d=1 |
| 2 | HITTER_OF_THE_MONTH | 6/league/year, all hitters, d=1 |
| 3 | ROOKIE_OF_THE_MONTH | 6/league/year, mixed |
| 4 | CY_YOUNG | top-3 voted, d=11 m=11 |
| 5 | MVP | top-3 voted, d=12 m=11 |
| 6 | ROOKIE_OF_THE_YEAR | top-3 voted, d=9 m=11 |
| 7 | GOLD_GLOVE | one per position (`position` field 1-9 = P-RF) |
| 9 | ALL_STAR | ASG roster (~30/league/year, d=14 m=7) |
| 11 | SILVER_SLUGGER | one per position (`position` 2-10, 10=DH) |
| 13 | RELIEVER_OF_THE_YEAR | top-3 voted |
| 14 | WS_CHAMPION_ROSTER | only winning league's `sub_league_id` populated |
| 15 | POSTSEASON_SERIES_MVP | WC/DS/CS/WS MVP per series |

Codes 8, 10, 12 unused — gaps in the sequence (OOTP reserves for future award types).

### `players_league_leader.category` — 47 of 60 verified

Verified by exact aggregate match (place=1 leader's `amount` matches the named stat for that player-year). Batting categories 0-26, pitching 27-59. Codes left unmapped (21, 22, 26, 31, 41, 44, 46, 49, 51, 53, 55, 57) are derived/sabermetric stats we don't compute as raw fields (RC, wOBA, FIP, SIERA, K%, SV%, QS%, etc.) — TBD.

Notable: rate stats (IP, ERA, WHIP, HR9, BB9, K9) match at low rate due to the OOTP IP convention rounding (172.1 displayed = 172.333 real).

See `LeaderCategory` in `constants.py` for the full enum.

### `players_streak.streak_id` — 21 codes profiled

Clear split:
- **11 batter streaks**: HITTING (max 34), GAMES_PLAYED (max 41), ON_BASE (max 37), MULTI_HIT, 3+ HIT, HR, EXTRA_BASE_HIT, RBI, RUN, plus 2 rare types
- **9 pitcher streaks**: SCORELESS_INNINGS (max 33), NO_HR_ALLOWED (max 31), APPEARANCE (max 39), WIN, QS, K, LOSS, SAVES, NO_WALK_ALLOWED
- **1 mixed (id 11)**: 99% pitchers, max 11

Names are best-guess pending OOTP documentation. Mapping ranks by max-value within each group.

### `players_injury_history.body_part` — 12 codes profiled

Best-guess mapping based on frequency + avg length + day-to-day rate:
- ARM (id 6, 7971 inj, 86% DTD) — most common, mostly minor
- LEG (id 3, 7853, avg 11 days)
- GENERIC (id 0, 7466, only 25% DTD — possibly the "non-specific" bucket where OOTP defaults)
- SHOULDER (id 5), BACK (id 7), ELBOW (id 10), OBLIQUE (id 9, avg 35 days), UCL/Tommy John (id 8, avg **60 days**, severe)
- ANKLE (id 1), HEAD (id 2, 88% DTD), HAND/THUMB (id 11), PERSONAL (id 4, 251 inj, 92% DTD — likely personal/family leave)

## League / team structure

- **MLB** = `league_id` 203, `league_level` 1, 30 teams.
- **MLB-affiliated leagues** = `parent_league_id = 203`. 14 leagues: AAA (204, 205), AA (206-208), A+/A (209-213, 252), Complex (217 ACL, 218 FCL), DSL (234).
- **AFL** = `league_id` 70 (Arizona Fall League). 6 teams. Special — not in `leagues.csv` with a parent reference, only appears in `teams.csv`.
- **DSL multi-affiliate**: 23 of 30 MLB orgs have **2 DSL teams** (e.g., Boston has Red Sox Blue + Red Sox Red); 7 orgs have 1.
- **Complex (FCL/ACL)**: every MLB org has exactly 1, evenly split 15 FCL / 15 ACL by geography.
- **Boston Red Sox org `team_id`s**: 4 (MLB), 35 (Worcester AAA), 64 (Portland AA), 269 (Greenville A), 289 (Salem A+), 113 (FCL), 158 (DSL Blue), 326 (DSL Red).

## Data quirks / gotchas

- **`players.csv` ratings columns are all 0** — the dump's true-rating fields are not exported when "Hide Player Ratings" is on. **Use `players_scouted_ratings.csv` instead.**
- **Multiple scout rows per player** in `players_scouted_ratings.csv` — one per scouting team. To get the player's own org's view, filter `scouting_team_id = <player's org's team_id>`.
- **`scouting_team_id = 0` is the OBJECTIVE / true rating** — no scouting accuracy bias. Discovered while resolving SCHEMA OPEN-1 (2026-05-05). 18,130 player rows under team_id=0; cross-reference with team_id=4 (Red Sox) shows CON exact match in 76.7% / POW 76.0% / 99.6% within ±5 pts — exactly the noise pattern of normal scout-accuracy spread on top of truth. **Per Decision D12, Diamond does not expose the objective rating anywhere in the product.** The reason it's documented here at all is operational: the L0→L1 ingest filter must drop `scouting_team_id = 0` rows so they're never reachable downstream. The audit harness uses `team_id = 4` (Sox) — that's the lens we always operate through.
- **`players_batting.csv` / `players_pitching.csv` / `players_fielding.csv` are NOT stat tables** — confusingly named. They're per-player rating snapshots, parallel to `players_scouted_ratings.csv` but mostly empty in this save: `players_batting` has only the 4 `running_ratings_*` columns populated (the 30+ `batting_ratings_*` cols are all zero), `players_pitching` is **completely empty** (0 of 67 rating cols populated), `players_fielding` has 27 useful cols (per-position experience + per-position rating + potential, the experience cols being unique to this file). Rationale appears to be that the canonical rating source is `players_scouted_ratings`; these three are leftover/legacy export shapes that didn't get filled in. Schema implication: skip `players_pitching` ingest, fold `players_batting`'s 4 running cols into the players snapshot, ingest `players_fielding` as a state-snapshot.
- **Athletics' DSL team** (id 177) has `parent_team_id = 0` — only MLB-org affiliate where the FK is missing. Cross-check with `team_affiliations.csv` instead of relying on `parent_team_id` alone.
- **`players.inducted` is the year of HOF induction**, not a boolean (e.g., Hank Aaron's row shows `inducted = 1982`).
- **`import_export` org reports show ALL of a player's season stats**, including time on prior orgs (mid-year trades), team_id=0 (amateur/college), and short-season prospect leagues (lg=75). Do NOT filter by team_id when reconciling.
- **`players_league_leader.csv` only covers post-save years** — pre-save year leaders aren't recorded. For "Building the Green Monster" save (started 2026), only 2026-2029 leader data exists. Historic leaders must be derived from `players_career_*` aggregates.
- **`league_history_all_star.csv`** has 5,869 rows over 95 years but no entries for 2029 yet — All-Star game may not have been played in current sim cycle. Investigate.
- **OOTP IP convention**: stored as `outs` integer; display as `FLOOR(outs/3) + (outs%3)*0.1`. E.g., 517 outs = 172 innings + 1 out remainder = displayed "172.1" (NOT 172.4).
- **`players_career_*` stints**: when a player plays for multiple teams in one season (trade, recall), they get multiple rows with incrementing `stint`. Sum across stints for season totals.
- **Trade summaries** in `trade_history.csv` use `<entity:type#id>` tags (e.g., `<Houston Astros:team#12>`, `<Bryan King:player#20728>`) — parseable into structured player/team references.
- **`players_streak.csv` boundary dups** — `(player_id, league_id, streak_id, started)` has 476 dups in 316K rows (~0.15%), almost all on `streak_id=21`. Pattern is consistent: an ENDED streak (`value=6, has_ended=1, ended=2028-5-22`) co-exists with a NEW ACTIVE streak (`value=3, has_ended=0, ended=NULL`) where the active streak's `started` equals the ended streak's `ended`. So the unique key requires `ended` (or a `COALESCE(ended, '9999-12-31')` sentinel) included. Discovered while resolving SCHEMA OPEN-5 (2026-05-05).
- **`leader.category` codes 44 and 49 remain unresolved (2026-05-05)** — out of
  the original 13 unmapped codes, 11 were resolved by computing the missing
  derived stats (now in `LeaderCategory`); 2 stayed mysterious despite
  thorough probing. Code 44 has values 8-10 across 8 MLB SP leaders
  (Skubal=9.24, Peralta=9.91, Yamamoto=9.44, etc.) and is NOT K/9, HA/9,
  HR/9, BB/9, WHIP, K-BB/9, IP/G, BF/IP, or any obvious composite.
  Code 49 has values 47-70 across 8 MLB SP leaders (Crochet=66.13,
  Snell=68.58, Skubal=47.66 in 2027 / 67.19 in 2029) and is NOT ERA-,
  FIP-, K% (K/BF), or any standard normalized stat. Both are likely
  OOTP-specific composites or scaled internal stats. Skipped without
  ranking the matches because we don't want to introduce a guess.
- **Sprague PIT mismatch — confirmed structurally inaccessible (2026-05-05)**: `individual_pitch_ratings` reconcile shows PIT=2 for Shea Sprague (pid 52253) vs our derived count-of-non-zero-pitch-ratings = 3 (FB=45, CH=40, SL=35). After exhaustive investigation, this is the ONLY mismatch in 220 Sox-org pitchers. Tested and ruled out: rating threshold (≥30/35/40 — many other pitchers have rated=30-35 pitches that DO count); position / role / handedness (same as comparable pitchers); age / experience / career usage; rating-talent gap (Sprague's gap is identical to his FB and CH); rating evolution (SL stable at 35 for 3+ years); `players_pitching.csv` columns (file is empty per OPEN-1); `players.csv` pitch-related cols (only fatigue/strategy, no arsenal flag); other 3-pitch pitchers with identical rating profiles (e.g. Pereira FB=40/CH=35/SL=40) get IE_PIT=3 correctly. Conclusion: OOTP carries an internal "developed pitch" state that is not exposed in any CSV column. The count-non-zero rule is correct for 219/220 = 99.5% of pitchers and stays as our derivation. This is a known 1/220 structural limitation, not a derivation bug.

## Stat replicability (against `import_export` 20-80 ratings + counting/derived stats)

90 of 97 audited columns reconcile exactly or within tolerance. Remaining gaps:

- **C-tier (need league constants)**: OPS+, ERA+, FIP, RC, RC/27, wOBA. All reachable via `league_history_*` totals + park factors from `parks.csv`.
- **G-tier**: DEF rating formula in `batting_ratings` — current "max of fielding_rating_pos2..9" guess only matches 29% of cases. Needs investigation.

## Performance & save-content scale

- **148K players** world-wide in current dump (most are non-scope: KBO, foreign country pools, draft prospects).
- **17,192 regular-season games** in MLB 2029.
- **1.3M at-bat events** in MLB 2029 (single-season, single-league).
- **494 trades** total, **112 in 2029**.
- **159 years of standings history** (1871-2029) — save loaded with full real-world MLB history.
- **291 Hall of Fame players**, all retired, all with induction year.

## At-bat event encoding (additional fields)

- **`bats`**: 1=R (76% of players), 2=L (24%), 3=S (6%)
- **`throws`**: 1=R, 2=L (same convention as bats)
- **`hit_loc`**: integer field-grid code. 1-49 = infield zones, 38-99 = outfield zones, 98-105 = over-the-fence (HR zones, 6 distinct codes by depth/direction). Ground outs concentrate in 1-43, fly outs in 44-99.
- **`hit_xy`**: 0-255 lateral position; packed 16×16 (`x = hit_xy / 16`, `y = hit_xy % 16`). **Empirically batter-relative** (verified 2026-05-12 against MLB-2029): mean `hit_xy ≈ 71` for both LHB and RHB HRs — same pull-side band for both hands. If hit_xy were field-absolute the means would diverge by hand. So pull / center / oppo classification doesn't branch on bat hand: `x ≤ 5` → pull, `6..9` → center, `x ≥ 10` → oppo, applied uniformly. (Earlier note in this file said "low = LF-side, high = RF-side" — the empirical evidence shows hit_xy is in batter's own frame, not the field's. Updated.) ZERO values represent "no spatial coordinate" (~50 BIP per result code) and are excluded from spray classification.
- **`exit_velo`**: mph. 0 = no batted ball (K, BB, HBP).
- **`launch_angle`**: degrees (positive = up). Edge cases at -65 etc. exist but are rare.
- **`Close`**: 1 if the game-state was "close" (typically within 4 runs after the 7th).
- **`pinch`**: 1 if pinch-hit appearance.
- **`base1` / `base2` / `base3`**: 0/1 booleans for runner on each base, PRE-AB. Combine as `base1 + 2*base2 + 4*base3` for compact base_state (0-7).
- **`outs`**: pre-AB outs count.

## League constants (computed for 2029 MLB)

| Constant | Value | Notes |
|---|---|---|
| lg AVG | .244 | matches modern real MLB norm |
| lg OBP | .315 | |
| lg SLG | .398 | |
| lg OPS | .713 | |
| lg BABIP | .292 | |
| lg ERA | 4.00 | matches real MLB exactly |
| Runs/PA | .114 | for wRC normalization |
| wOBA scale | .999 | calibrated so league-avg wOBA = lg_obp |
| wBB | 0.690 | linear weights — base FG values × scale |
| wHBP | 0.720 | |
| w1B | 0.889 | |
| w2B | 1.269 | |
| w3B | 1.619 | |
| wHR | 2.099 | |
| FIP constant | 3.04 | computed: lgERA - (13·HR + 3·(BB+HBP) - 2·K)/IP |

## Empirical Run Expectancy matrix (2029 MLB, 1.2M events)

Mean runs from this state to end of half-inning, per (base_state, outs):

| State | 0 outs | 1 out | 2 outs |
|---|---|---|---|
| Empty | 0.59 | 0.32 | 0.13 |
| 1B | 0.71 | 0.37 | 0.16 |
| 2B | 0.72 | 0.41 | 0.18 |
| 1B+2B | 1.01 | 0.53 | 0.23 |
| 3B | 0.86 | 0.47 | 0.18 |
| 1B+3B | 1.21 | 0.56 | 0.25 |
| 2B+3B | 1.33 | 0.67 | 0.26 |
| Loaded | 1.96 | 0.98 | 0.41 |

Slightly compressed vs real-MLB matrix (e.g., real bases-empty-0-out is ~0.48), suggesting OOTP's run environment is marginally higher-leverage than real MLB.

---

## Findings from full 21-file `import_export` reconciliation (2026-05-02)

### IE display conventions

The `import_export` files apply UI formatting to numeric dump fields. The
reconciliation matcher now normalizes these:

- **`-`** is the "no value" sentinel (treated as null).
- **Trailing `%`** on percentages: `"9.1%"` ↔ `9.1`.
- **Currency**: `"$28 800 000"` (dollar prefix, space thousands-separator) ↔ `28800000`.
- **Auto-renewal annotation**: `"1 (auto.)"` on contract years field.

When a field is a **categorical string** in IE (e.g. VELO `"75-80 Mph"`,
G/F `"EX FB"`, popularity `"Well Known"`, personality `"Normal"`, scouting
accuracy `"V.High"`), the dump stores a small integer that maps to it. We
don't yet have these mapping tables — they're tagged G-tier.

### Pitching career-stats discoveries

- **PPG**: OOTP truncates (`FLOOR`), not rounds, when displaying integer.
- **GO%**: IE displays as decimal fraction (`0.17` = 17%), 2-decimal precision —
  not a percentage.
- **SV%**: OOTP uses `sv / (sv + bs)` (saves over save situations), not
  `sv / svo`.
- **GF**: pull `career_pit.gf` directly — *not* `g - gs` (which is "relief
  appearances", a different concept).
- **WPA**: IE rounds to 1 decimal; per-stint sums round nicely.

### Unreconciled formula puzzles (TBD)

- **DEF (G-tier)**: appears in batting_ratings, batting_potential,
  position_ratings. The `MAX(fielding_rating_pos2..9)` formula is consistently
  5-15 points HIGHER than IE values (e.g. ie=55, derived=60). DEF likely
  applies a positional difficulty adjustment or a weighted average of the
  underlying skill ratings (range/error/arm), not a simple positional max.
- **pLi (career_pit.li)**: neither `SUM(li)`, `AVG(li)`, nor `SUM(li)/SUM(g)`
  reproduces IE values. Some pitchers come out 12× too high; others ~300× too
  high. The semantics of `career_pit.li` are unclear — may need per-game
  leverage sums elsewhere.
- **RA in pitching_stats_2**: a small integer (often <10) that doesn't match
  raw `career_pit.r` (much larger) or per-9 RA (decimal). Possibly some
  unearned-runs-only or specific-context metric.

### Statcast (at-bat-derived) approximations

`batting_superstats_1` and `pitching_superstats_1` derive ~22 columns from
the per-PA `players_at_bat_batting_stats` event log. Formulas are
approximately right but exact reconciliation needs:

- **EV buckets** for Soft%/Avg%/Solid%: OOTP's exact cutoffs unknown.
  Currently using `<85 / 85-100 / >=100` mph as a placeholder.
- **`hit_xy` + `bats` decoding**: needed for Pull%/Cent%/Oppo% spray-direction
  classification (currently NULL).
- **`hit_loc` decoding**: needed for IFH% (infield-hit %).
- **xBA/xSLG/xwOBA/xERA** (D-tier): require a regression model from
  (EV, LA, hit_loc) → outcome probability.

The basic distribution shapes (LD%, GB%, FB%, BIP, EV mean/max, BAR, HHi)
match within a few percent. The per-PA event log is internally consistent
with OOTP's output; the gaps are about discovering OOTP's exact thresholds.

### `BIP` definition

OOTP excludes sacrifices (`sac > 0`, both bunts and SF) from BIP counts.
`bip = COUNT(*) WHERE result IN (4,5,6,7,8,9) AND sac = 0`.

### Scope / source tables for IE files

Each of the 21 IE files maps to one or more dump tables:

| IE file | Primary dump source |
|---|---|
| `batting_stats_1`, `batting_stats_2` | `players_career_batting_stats` |
| `pitching_stats_1`, `pitching_stats_2` | `players_career_pitching_stats` |
| `fielding_stats` | `players_career_fielding_stats` (use `split_id=0`) |
| `batting_ratings`, `batting_potential`, `pitching_ratings`, `pitching_potential`, `fielding_ratings`, `individual_pitch_ratings`, `individual_pitch_potential`, `position_ratings` | `players_scouted_ratings` (filter `scouting_team_id=4 AND league_id=203`) |
| `batting_superstats_1`, `pitching_superstats_1` | `players_at_bat_batting_stats` |
| `batting_superstats_2`, `pitching_superstats_2` | F-tier (per-pitch zone/type data — not in dump) |
| `default`, `popularity_info`, `personality___morale` | `players` (+ scouted_ratings for OVR/POT) |
| `financial_info` | `players_contract` (+ players for age) |

## DEF rating formula (decoded 2026-05-03)

The `DEF` column shown in `batting_ratings`, `batting_potential`, and
`position_ratings` is **the player's fielding rating at their primary
position** — not max-of-positions, not an average.

```sql
CASE players_scouted_ratings.position
    WHEN 1 THEN fielding_rating_pos1   -- P
    WHEN 2 THEN fielding_rating_pos2   -- C
    WHEN 3 THEN fielding_rating_pos3   -- 1B
    ...
    WHEN 9 THEN fielding_rating_pos9   -- RF
END
```

Verified: 220/220 exact match across all three IE files. The previous
"max-of-positions" hypothesis was wrong because a 3B with strong 1B/LF
backup ratings would show his 3B number in IE, not the higher backup rating.

`batting_potential.DEF` shows **current** primary-position rating, not
potential — OOTP's potential view doesn't separately surface a "DEF
potential" because each per-position rating already has its own
`fielding_rating_posN_pot`.

### Audit population caveat

The ratings CTEs filter `scouted_ratings` by `scouting_team_id=4 AND
league_id=203`, which restricts joins to MLB-level players (24 of 220 IE
rows). Each Red Sox-org player has exactly 1 row at `scouting_team_id=4`
across all leagues, so dropping the league filter would broaden the
audit population to all 220 IE rows without introducing duplicates.

## Codebooks decoded 2026-05-03 (from helpful_files cross-reference)

### Popularity (`players.local_pop`, `players.national_pop`) — 7-bucket scale

| int | IE string |
|---|---|
| 0 | Unknown |
| 1 | Insignificant |
| 2 | Fair |
| 3 | Well Known |
| 4 | Popular |
| 5 | Very Popular |
| 6 | Extremely Popular |

Verified empirically: 220/220 exact match in IE `popularity_info`.

### Scouting accuracy (`players_scouted_ratings.scouting_accuracy`) — 1..5

| int | IE string |
|---|---|
| 1 | V.Low |
| 2 | Low |
| 3 | Avg |
| 4 | High |
| 5 | V.High |

Verified empirically: 220/220 exact match in IE `popularity_info.SctAcc`.

### Personality bucket (`players.personality_*`)

The 5 personality fields (`personality_leader`, `personality_loyalty`,
`personality_greed`, `personality_work_ethic`, `personality_intelligence`)
are 0–200 internal values. IE shows them as `'Low' | 'Normal' | 'High' | 'Unknown'`.

| value range | IE string |
|---|---|
| < 60 | Low |
| 60 – 139 | Normal |
| ≥ 140 | High |

The "Unknown" label appears for ~4 of 220 players who are 2029 acquisitions
with `experience ≤ 1` — the org hasn't fully scouted their personality yet.
Those players still have a hidden true value in the dump, so the bucket
formula returns Low/Normal/High and the matcher records 4 mismatches per
trait (216/4/0). That's a known limitation, not a formula flaw.

The IE `Type` column ("Captain", "Selfish", "Humble", "Sparkplug", etc.)
is a derived **personality archetype**, not a sixth trait — it's some
combination of the 5 trait values plus scouting_accuracy. Left F-tier;
formula TBD if we ever care about archetypes.

## hit_xy spray decode (partial — exact boundary TBD)

`players_at_bat_batting_stats.hit_xy` is a 16×16 packed coordinate:
`x = floor(hit_xy / 16)`, `y = hit_xy % 16`. **Empirically `hit_xy`
is batter-relative** (verified 2026-05-12): mean hit_xy on HRs is
≈71 for both LHB and RHB hitters — same pull-side band for both
hands. If the coord were field-absolute the means would diverge by
hand. So the player-page spray splits use a hand-INDEPENDENT rule:
`x ≤ 5` → pull, `6..9` → center, `x ≥ 10` → oppo. (The earlier
"naive bins" noted under-counted Pull% vs IE by ~5-10pp — that
analysis applied a hand-dependent rule that we now know was
incorrect; the new hand-independent rule still doesn't perfectly
match IE magnitudes but the direction is reliable.) E-tier match
quality stays the same — magnitudes still ~5-10pp off vs IE
because OOTP probably weights `hit_loc` into its spray label too.

## League-level pre-computed sabermetrics (big future unlock)

`league_history_batting_stats` and `league_history_pitching_stats` already
ship with per-league/year/level pre-computed:

- batting: `wOBA`, `RC`, `RC/27`, `ISO`, `OPS`, `BABIP`, `K%`, `BB%`
- pitching: `FIP`, `ERA`, `WHIP`, `WAR`, `RA9-WAR`, `K-BB%`, `H/9`,
  `K/9`, `BB/9`, `HR/9`, `BABIP`, `K%`, `BB%`, `KBB ratio`

Implication: the planned **league constants module** doesn't have to
*compute* anything — it can just read these pre-computed league lines
from the dump and use them directly to derive ERA+, OPS+, wRC+, etc.
This collapses most of the C-tier outstanding (RC, RC/27, wOBA, FIP,
ERA+, OPS+) into a simple lookup pattern.

## HOF induction

`players.inducted` (int, 0 = not inducted, otherwise = induction year)
and `players.hall_of_fame` (0/1 flag) are direct columns. No need to
reconstruct from `players_awards` cross-references.

## All-Star 2029 gap

`league_history_all_star.csv` data goes 1933 → 2028 with no 2029 entries.
Years 2020 and 2030 are also missing. The 2029 absence is consistent
with the helpful-files cross-reference (their save also stops at the
last completed season). Likely the file is only written at year end /
during postseason rollup, so a Nov dump captured before that step has
no current-year entry. Not a formula issue; treat it as "data not
available until next dump."

## Statcast superstat calibration (2026-05-04)

Empirical findings from grid-searching against IE values for the 9
MLB-only single-level Red Sox players (Mayer, Gonzales, Encarnacion,
Abreu, Anthony, Rafaela, Langeliers, Campbell, Narvaez):

### Regular-season filter

`players_at_bat_batting_stats` includes spring training (`game_type=2`)
and postseason (`game_type=3`) events. PCB `split_id=1` is regular-season
only. To match IE, restrict at_bats to `JOIN games g ON g.game_type=0`.
Without this filter, BIP/EV/HHi inflate by 5-15% for MLB regulars.

### EV bucket cutoffs (Soft / Avg / Solid)

OOTP uses **75 / 95** — *not* the standard Statcast 80/95 split.

| bucket | rule |
|---|---|
| Soft% | `0 < exit_velo < 75` |
| Avg% (Med% on pitching) | `75 ≤ exit_velo < 95` |
| Solid% | `exit_velo ≥ 95` |

Verified: with these cutoffs, 9/9 Soft% match within 2pp on MLB-only
Sox players (vs 0/9 with the old 85/100 placeholder).

### Barrel formula

OOTP does NOT use the Statcast expanding-cone definition. The empirical
best fit is a flat threshold:

```
exit_velo ≥ 100  AND  launch_angle BETWEEN 10 AND 42
```

Grid-search on 9 MLB-only Sox players: 4/9 exact, 6/9 within ±1, total
absolute error 11. The Statcast cone produced total error 32 on the
same set. (Across the wider 220-player population, the simple formula
is roughly equivalent to the cone — within 3pp of match% — because
both formulas match equally poorly for non-MLB players whose at_bat
data is incomplete.)

### HHi (HardHit)

`exit_velo ≥ 95` — matches IE within 1-2 events for MLB regulars.
Standard Statcast definition; OOTP uses the same cutoff.

### BIP — use PCB, not at_bats

`AB - K + SF + SH` from `players_career_batting_stats` (level-aware,
filtered to the right level for the player's primary playing context)
matches IE BIP exactly for MLB-only players. The at-bat-counted BIP
will diverge for minor-leaguers whose foreign-league at-bats aren't in
`players_at_bat_batting_stats`. Future improvement: switch the
superstats CTE's BIP denominator from at_bats COUNT to PCB-derived.

### What still has structural ceilings

Even with the calibrations above, the Statcast columns can't hit 100%
across the full 220-player roster because:

1. IE shows stats from the player's *primary* level (typically the
   highest US-affiliated level reached this season). Multi-level
   players (called up mid-season) need level-segmented derivations.
2. `players_at_bat_batting_stats` only covers in-scope leagues
   (MLB + affiliated minors + KBO + indy). Players who appeared in
   foreign leagues have incomplete at-bat data. We can't reproduce
   their IE numbers from the at-bat log alone.
3. The Pull/Cent/Oppo% classification doesn't fit a simple x-bin model
   on `hit_xy`. Empirically, the hit_xy x-centroid for almost every
   `hit_loc` value is ~7.5 (dead center) — confirming `hit_loc` represents
   fielding position not spray direction. Only hit_loc 80, 98-105 are
   LF-specific. OOTP must use per-event spray logic we can't reverse-
   engineer from these fields alone.

## SIERA decoded (2026-05-04)

OOTP's IE SIERA matches the **Fangraphs canonical formula** (the long
version with quadratic and interaction terms):

```
SIERA = 6.145
      - 16.986 · (K/PA)
      + 11.434 · (BB/PA)
      - 1.858  · ((GB - FB) / PA)
      + 7.653  · (K/PA)²
      - 6.664  · ((GB - FB) / PA)²
      + 10.130 · (K/PA) · ((GB - FB) / PA)
      - 5.195  · (BB/PA) · ((GB - FB) / PA)
```

- Verified Crochet IE 2.27 vs calc 2.25 (off 0.02).
- 95% match across MLB-only Sox pitchers (96/101 within ±0.1).
- Aggregated across all levels (no level filter; net_GB is the player's
  cross-level groundball-vs-flyball net rate).
- Note: OOTP's `gb`/`fb` columns lump pop-ups in with fly balls, so the
  `(GB - FB)` term implicitly excludes the standard "PU" subset. That's
  consistent with the Fangraphs simplification used here.

## All C-tier cells eliminated (2026-05-04)

After the third reconciliation pass, **zero columns remain in C-tier**.
The audit went from 30+ C-tier columns at start to 0 via:
- League-constants module (lookup over `league_history_*_stats`):
  OPS+, ERA+, FIP, RC, RC/27, wOBA, ISO
- Empirical decode: pLi, RA, RSG, CG%, IRS%, GO%, PPG
- SIERA via Fangraphs formula
- Contract data via `players_contract_extension` + `players_roster_status`

## Pitching counter decodes (2026-05-04)

Three previously-mysterious columns in `pitching_stats_2` decoded by
inspecting how counts move with starter vs reliever roles:

| IE col | Formula | Verification |
|---|---|---|
| **RA** (relief appearances) | `g - gs` | Lei 64=64; Tolle 74=74; Crochet 33-33=0; 97% match |
| **RSG** (run support per start) | `rs / gs` (0 for pure relievers) | Crochet 94/33=2.85≈IE 2.8; Valera 18/8=2.25≈IE 2.2; 99% |
| **pLi** (avg leverage index) | `SUM(li) / SUM(bf)` | Crochet 706.1/735≈0.96; Lei 624/270≈2.31; 100% |

Critical: `career_pit.li` is the **cumulative** sum of leverage index
across all batters faced, NOT an average. The dump's column dictionary
calling it "average leverage index" was misleading.

## VELO and G/F int→string decodes (2026-05-04)

OOTP's IE shows pitcher velocity as a band string like "89-91 Mph". The
underlying `pitching_ratings_misc_velocity` is a 0-19 ordinal:

| int | string |
|---|---|
| 0 | (no value, "-") |
| 1 | 75-80 Mph |
| 2 | 80-83 Mph |
| 3 | 83-85 Mph |
| 4-19 | 84-86 / 85-87 / ... 99-101 Mph (advances by 1 mph per level) |

G/F (`pitching_ratings_misc_ground_fly`, 0-100) buckets:

| range | label |
|---|---|
| 0-43 | EX FB |
| 44-48 | FB |
| 49-58 | NEU |
| 59-63 | GB |
| 64+ | EX GB |

Both verified 100% match across 220-player Sox roster.

## Sabermetric stat formulas (2026-05-04)

Empirically verified against MLB-only Red Sox players using
`league_history_*_stats` for league context:

### OPS+
```
OPS+ = ROUND(100 * (OBP/lgOBP + SLG/lgSLG - 1) / (1 + (park.avg - 1) / 2))
```
Halved park factor — each player plays half home / half road.
8 of 9 MLB-only Sox match exact (e.g., Mayer naive 107.6, Fenway halved 1.025, → 105 = IE).

### ERA+
```
ERA+ = ROUND(100 * (lg_ERA / pERA) * (1 + (park.avg - 1) * 0.8))
```
Empirical park multiplier ~1.04 for Fenway (avg=1.05). Note: this is
NOT the halved park factor used for OPS+.
Verified Crochet IE 127 = 121.9 * 1.04; Suarez 149 = 142.9 * 1.04.

### RC (Bill James technical)
```
RC = ((H + BB - CS + HBP - GIDP) *
      (TB + 0.26*(BB + HBP) + 0.52*(SH + SF + SB))) / PA
```
100% match on tested players. Mayer: 72.5 = 72.5 exact.

### RC/27
```
RC/27 = RC * 27 / (AB - H + GIDP + SH + SF + CS)
```
99% match.

### wOBA
```
wOBA = (0.69*uBB + 0.72*HBP + 0.89*1B + 1.27*2B + 1.62*3B + 2.10*HR)
       / (AB + uBB + SF + HBP)
```
where uBB = BB - IBB. Standard Fangraphs linear weights.
79% match within 0.01 tolerance — slight variance from non-Fangraphs
weights or league-calibrated wOBA-scale.

### FIP
```
FIP = (13*HR + 3*(BB + HBP) - 2*K) / IP + cFIP
cFIP = lg_ERA - lg_(13*HR + 3*(BB + HBP) - 2*K) / lg_IP
```
69% match within 0.1 tolerance. lg_ERA and lg counting stats from
`league_history_pitching_stats` per (league_id, year, level_id).

### Cross-level player caveat

For players who split a season across levels (AAA call-up, etc.),
IE shows the **combined total slash line** but applies a level-weighted
park factor we don't fully model. These players will mismatch this
formula by ~5-15 OPS+ points. Logged as a known limitation.

## xBA / xSLG / xwOBA — structural-limit D-tier (2026-05-04 EDA)

Two probes (`scripts/xstats_eda.py`, `scripts/xstats_3d.py`) tested whether
the at-bat log alone (EV, LA, hit_loc, hit_xy) can replicate IE's xstats.
Conclusion: **no.** Logging here so we don't re-attempt this from scratch.

### Probe 1: 2D EV × LA bucket model (5 EV × 6 LA = 30 cells)

Built empirical (BA, SLG, wOBA) lookup per (EV-bucket, LA-bucket) across
all 781K regular-season MLB BIP. Applied per-player using AB as denominator
(K's correctly count as 0-hit attempts).

| Stat   | MAE    | Pearson r | match-rate within IE display tol |
|--------|--------|-----------|-----------------------------------|
| xBA    | 0.048  | 0.29      | 12.9% (±0.010)                    |
| xSLG   | 0.082  | 0.55      | 12.9% (±0.020)                    |
| xwOBA  | 0.057  | 0.47      | 3.5% (±0.015)                     |

### Probe 2: 3D EV × LA × hit_loc with Empirical-Bayes shrinkage

89 distinct hit_loc values × 30 (EV,LA) cells = 1,366 populated 3D cells.
Thin cells (n<20) shrunk toward the 2D fallback at k=20.

| Stat   | MAE    | Pearson r | bias    |
|--------|--------|-----------|---------|
| xBA    | 0.048  | 0.34      | +0.036  |
| xSLG   | 0.086  | 0.55      | +0.061  |
| xwOBA  | 0.058  | 0.49      | +0.048  |

Adding hit_loc moved r by 0.05 at most. Almost no signal.

### What this means

1. **The +0.036 bias is the smoking gun.** Every high-BIP player has derived
   xBA ~0.025-0.045 *higher* than IE. That's 3× the spread of IE xBA values
   themselves (sd ~0.022 among 200+ BIP players). It's a real adjustment OOTP
   is making, not noise.
2. **r plateaus at ~0.5 even with hit_loc.** EV+LA+hit_loc explains less than
   half of IE's xstat variance. Something else dominates.
3. **Most likely candidates** for the missing input — neither recoverable
   from the at-bat log:
   - `players_batting.contact` / `gap_power` / `power` rating (OOTP reads
     batter rating directly into expected-outcome)
   - Per-pitch / per-pitcher quality adjustment (a 95mph LD against a Cy
     Young is "expected" differently than vs. AAA filler)

### Verdict

xBA/xSLG/xwOBA are **structural-limit D-tier** — same category as the
F-tier plate-discipline columns from D5. We have the cleanest possible
inputs (99.9% EV/LA coverage) and a 3D bucket model represents the
empirical ceiling at MAE ~0.05 / r ~0.4. Reaching IE display tolerance
(±0.010) would require reading player ratings directly, which is
self-referential since ratings are themselves audit inputs.

xERA was not separately probed but expected to behave identically
(same input shape on `opponent_player_id`).

EDA scripts retained at `scripts/xstats_eda.py` and `scripts/xstats_3d.py`
as the empirical evidence behind this finding.

## Trade attribution semantics (2026-05-06)

Findings while wiring `trade_event` to `player_movements.trade_id` via
the new `f_trade_participant` long-format roster (1,275 rows = 445 trades
× ~2.9 players each).

**Trade-event shape.** `trade_event` is one row per trade with up to 10
player slots per side (`player_id_0_0..9`, `player_id_1_0..9`), plus 5
draft-pick and cash/IAFA-cap slots per side. `message_id` is unique per
trade and is the canonical `trade_id`. Empirically max non-zero player
slots used = 5 per side (so the 10-slot allocation is generous).

**Org rollup is required.** Trade rows record `team_id_0` / `team_id_1`
at MLB-org level (e.g., 4 = Boston). But the snapshot may show the
player on a farm team (e.g., 35 = Worcester, parent_team_id=4). The
attribution join therefore rolls farm team_ids up to their MLB parent
via `COALESCE(NULLIF(parent_team_id, 0), team_id)` and matches at the
org level on both sides.

**Dump-date label vs. capture time.** Dumps are labeled with the 1st of
the month (sortable identifier per `dump_name_to_date`) but the OOTP
export captures end-of-month state. So a trade dated June 29 typically
shows up in the dump labeled June 1 — i.e., **before** the trade in
calendar order. Attribution uses a ±60-day window around
`dump_date_observed` to handle this.

**Coverage.** With both-side org match + ±60-day window:
- 1,270 of 1,275 trade participants (99.6%) attributed.
- 100% of trades have ≥1 matched player.
- 1,270 of 50,796 `team_change` rows (2.5%) carry a `trade_id` —
  the rest are intra-org promotions/demotions, waiver claims, etc.

**The 5 residual misses** are all "DFA-paired" or "release-immediately-
after-trade" patterns: player appears in a trade roster, but the
snapshot diff shows the matching team_change as `released → signed`
instead of `team_change`. Examples: Sammy Peralta (trade_id=13520),
Hunter Stratton (trade_id=4151), Brock Burke (trade_id=11158), Ron
Marinaccio (trade_id=4132), Ryan King (trade_id=2247). Not worth
chasing for v1; the trades themselves are still all surfaced via
`f_trade_participant`.

**The `<entity:type#id>` summary parser** is now lower priority — the
structured columns covered the use case for movement attribution.
Reserve the parser for richer narrative surfaces (3-team trade
storytelling, draft-pick / cash flow visualization, AI summary copy).

## player_movements — movement_type taxonomy (2026-05-06)

After trade attribution shipped, the generic `team_change` value was
split into 5 specific subtypes using the org rollup + level data we
already had. The full enumeration on `player_movements.movement_type`:

| value | rule | rows | share |
|---|---|---:|---:|
| promotion | same org, `to_level_id < from_level_id` | 20,141 | 21.1% |
| demotion | same org, `to_level_id > from_level_id` | 18,325 | 19.2% |
| first_appearance | first dump in which we observed the player | 15,992 | 16.7% |
| signed | from no team (0) to a team | 12,243 | 12.8% |
| released | from a team to no team (0) | 11,766 | 12.3% |
| intra_org_lateral | same org, same level (or one level NULL) | 6,288 | 6.6% |
| waiver_or_other | different org, no trade attribution | 4,772 | 5.0% |
| retired | retired flag turned on | 2,526 | 2.6% |
| drafted | from the draft source | 2,320 | 2.4% |
| trade | team change matched to a `trade_event` (carries `trade_id`) | 1,270 | 1.3% |
| unretired | retired flag turned off | small | small |

OOTP level conventions: 1=MLB, 2=AAA, 3=AA, 4=A+, 5=A, 6=Rookie/FCL,
7+=DSL/etc. **Lower level_id = closer to the majors**, so a promotion
moves *to* a smaller level_id. Filter `to_level_id = 1` for
"promotions to MLB specifically."

Org rollup (used both here and in trade attribution):
`COALESCE(NULLIF(parent_team_id, 0), team_id)` — if a team has a
parent_team_id it's a farm club and rolls up; if parent_team_id = 0
it IS the parent (MLB level).

`waiver_or_other` is a catch-all for cross-org moves with no trade
attribution. Most are waiver claims; some may be paid transfers or
MiLB Rule 5 selections that OOTP doesn't surface as trades.

## Real MLB history backfill — Lahman + Statcast (2026-05-06)

The OOTP simulation is the canonical "MLB" from save start onward, but
without real historical data the all-time records leaderboard is just
a few decades of OOTP-imported careers (Bonds, Ruth, McGwire absent).
We backfill once at app setup with two open data sources:

  - **Lahman** (1871–save_start-1): classic counting + rate stats per
    (player, year, team-stint) plus awards, HoF voting, all-stars, teams.
    One zip download (~9.5 MB) from `cdalzell/Lahman` (mirror of the
    SeanLahman archive — the original `chadwickbureau/baseballdatabank`
    GitHub repo is gone as of 2026).
  - **Statcast** (2015–save_start-1): season-aggregated EV / barrel /
    hard-hit / sweet-spot leaderboards via `pybaseball.statcast_*_exitvelo_barrels`.
    Per-PA Statcast is intentionally out of scope for v1 — season-grain
    is the right shape for record leaderboards.

CLI: `diamond fetch-history`. Idempotent (cached zip, INSERT OR REPLACE
table builds), but designed to be run **once** as a setup step. We
deliberately don't refresh annually — once the historical floor is
set, OOTP's universe owns everything from save_start_year onward.

**Save-start derivation** (`diamond.history._save_start_year`): parsed
from the earliest dump folder name. The current Sox save's earliest
dump is `dump_2026_03`, so save_start_year = 2026 and we cap historical
backfill at 2025.

**Lahman mirror's age**: `cdalzell/Lahman` was last updated through
2019 — meaning real-life retirees from 2020-2024 (Pujols 703 HR,
Cabrera 511 HR, Wainwright, Votto, etc.) show stats only through 2019
in the Lahman tables. Players still active at OOTP save start (Judge,
Trout, Freeman) have full real careers via OOTP's import, so this
gap mostly affects players who retired between 2020-2024. Backlog
item: fill 2020-2024 via `pybaseball.batting_stats_bref` /
`pitching_stats_bref` (Baseball-Reference scraping works; FanGraphs
returns 403 to pybaseball as of 2026).

**`f_record_player` and `f_award_career_player` UNION**: the L3 record
+ awards tables source-tag every row (`source = 'save'` | `'lahman'`).
The `--era` CLI flag filters: `--era save` for OOTP-only, `--era lahman`
for real-life-only, `--era all` (default) for the combined leaderboard.
Within-source ranks are stored; the CLI re-ranks across sources
dynamically when displaying combined.

**Lahman award-string → AwardId mapping** (in `_build_f_award_career_player`):
  - Most Valuable Player → MVP (5)
  - Cy Young Award → CY_YOUNG (4)
  - Rookie of the Year → ROOKIE_OF_THE_YEAR (6)
  - Gold Glove → GOLD_GLOVE (7)
  - Silver Slugger → SILVER_SLUGGER (11)
  - World Series MVP → POSTSEASON_SERIES_MVP (15)
  - Reliever of the Year Award + Rolaids Relief Man Award → RELIEVER_OF_THE_YEAR (13)
  - All-Star (from `history_lahman_allstar` table) → ALL_STAR (9)

Lahman awards we don't model (TSN All-Star, Hank Aaron Award, Lou Gehrig
Memorial, Roberto Clemente, Hutch, Branch Rickey, Triple Crown,
Comeback Player, Outstanding DH) get dropped at L3 build — we don't
synthesize new AwardId values just for Lahman categories.

**Player identity bridge**: not yet wired up. OOTP-save Aaron Judge
(player_id=23867) and Lahman Aaron Judge (playerID="judgeaa01") show
as separate rows in records / awards. OOTP's `players.historical_id`
column would let us link them, but that's a future feature. For now,
records using `--era all` may show a player's real-life pre-save
career and OOTP-save career as two adjacent rows when ranks are close.

**WAR + QS are save-only** — Lahman doesn't carry them (WAR is a
derived stat from FG/B-R, not in the Lahman base). `--era lahman
--category WAR` returns empty.

## f_draft_class — player retention + the `drafted` first-MLB gotcha (2026-05-06)

**Player retention probe**: of the 2,344 distinct draftees across
classes 2026–2029, 100% are still present in `players_current` (the
latest dump's snapshot). Released, retired, and unsigned draftees
all stick around in `players_snapshot` rather than getting purged.
Confirms it's safe to derive draft-class outcomes from `players_current`
without survivorship bias.

**The `drafted` first-MLB gotcha**: `_build_player_movements` synthesizes
a `drafted` row per player with `to_team_id = draft_team_id`. Draft
teams are always at MLB org level (`level=1`), so a naïve
`MIN(dump_date_observed) WHERE to_level_id = 1` over `player_movements`
would falsely flag every drafted player as "ever made MLB" on their
draft day — even if they never actually appear on a major-league
roster afterward.

The fix (in `_build_f_draft_class`'s `first_mlb` CTE): exclude
`drafted` movement_type. The player's genuine MLB debut shows up
as a later `promotion`, `first_appearance`, `signed`, `trade`, or
`waiver_or_other` row.

Outcome distribution after the fix, on the live warehouse:

| class | n | mlb_star+regular | mlb_callup | in_draft_org | traded_away | released | retired |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026 | 598 | 7 | 52 | 281 | 181 | 44 | 33 |
| 2027 | 566 | 0 | 24 | 473 | 49 | 3 | 17 |
| 2028 | 562 | 2 | 9 | 546 | 24 | 0 | 2 |
| 2029 | 573 | 0 | 0 | 572 | 1 | 0 | 0 |

The 2026 class is the most useful as a hit-rate calibration: 3 years
out, ~10% reached MLB at all and ~1% are MLB regulars (≥1.0 career
WAR). The 2029 class shows the expected pattern — barely anyone has
moved out of their org yet.


## OOTP per-PA exit velocity vs Statcast — calibration gap

**Findings** (probe 2026-05-07, year 2029 MLB, league_id=203, level_id=1):

| metric | save (OOTP) | real (Statcast 2015–2025) |
|---|---|---|
| league avg EV | 82.9 mph | 88–89 mph |
| std EV | 17.3 mph | ~13 mph |
| top max EV | 126.4 mph (Hector Santiago, 379 BBE) | 122.9 mph (Cruz / Henderson) |
| top avg EV | 88.5 mph (Henderson) | 95+ mph (Judge / Stanton) |
| top hard-hit% | 34.2% (Judge, save) | 65%+ (Judge, real) |

OOTP's `f_pa_event.exit_velo` runs **~5 mph lower at the league mean**
than real Statcast and has a **wider tail** (some non-everyday batters
top 125+, vs real-life ceiling of ~123). Top-end stars sit ~5–7 mph
*below* their real-life counterparts on avg EV, so HARD_HIT_PCT
(absolute 95-mph cutoff) scales proportionally lower (~half the
real-life leader rate).

**Implication for `f_record_player`:** save-side EV records and real
Statcast EV records are **NOT comparable head-to-head** within the
same leaderboard. They UNION into the same (scope, discipline, category)
tuple under different `source` values (`save` vs `statcast`), and the
renderer uses source-color to disambiguate. `--era statcast` filters
to real-only, `--era save` filters to save-only, `--era all` mixes
them with the source column visible.

**Why we don't recalibrate**: shifting OOTP EV by +5 mph would preserve
relative ranking but distort the absolute scale, and there's no
internally-consistent way to map OOTP's wider distribution to the
narrower real-life one without losing information. Better to surface
both as-is and let the user know they're different scales.


## f_record_player.direction — ASC vs DESC ranking

Added 2026-05-07 alongside pitching Statcast records. Each row in
`f_record_player` carries a `direction` value in {`'asc'`, `'desc'`}
that controls whether `rank_in_source = 1` means *highest* or *lowest*
value:

- `direction = 'desc'` (default — counting stats, peak EV, batting
  Statcast rate stats) — rank 1 = highest value. The CLI title prefix
  reads "Most HR", "Most MAX_EV", etc.
- `direction = 'asc'` — pitching contact-allowed rate stats: AVG_EV,
  HARD_HIT_PCT, BARREL_PCT, SWEET_SPOT_PCT (single-season only). Rank
  1 = lowest value, the achievement (best contact suppressor). Title
  prefix reads "Fewest BARREL_PCT", etc.

Within a single (scope × discipline × category × source) tuple all
rows agree on direction (it's a tuple-level attribute, enforced via
the smoke test). The `ranked` CTE's `ORDER BY` uses
`CASE WHEN direction = 'asc' THEN value ELSE -value END ASC` so
both directions cohabit one ranking expression.

Pitching MAX_EV / MAX_DIST stay `desc` because they describe the
single hardest/longest ball a pitcher gave up — a feat in the
curiosity sense, not a positive achievement.


## f_award_career_player merged source — Lahman + mlbapi dedup

Added 2026-05-07. Replaced the previous {save, lahman, mlbapi} 3-source
design with {save, merged} via bbref_id collapse.

- `source = 'save'` — career awards from `f_award_event` (in-save dumps
  2026+, plus OOTP's historical-seed import of pre-save real awards
  for active players: Trout 2014/2016/2019 MVPs land here).
- `source = 'merged'` — Lahman 1871-2017 awards + Lahman All-Stars +
  MLB Stats API 2018+ awards, collapsed by bbref_id × award × league,
  filtered to **bbref_ids NOT active in the user's save**. So
  retired/historical players (Bonds, Aaron, Ruth, Pujols) live in
  merged; active OOTP imports (Trout, Judge, Ohtani) live in save.
  Verified spot-check: Bonds 7 MVPs (1990–2004) sits in merged
  alongside Ohtani 7 MVPs (2021–2028) in save with no double-count.

The previous design surfaced the same player twice (`source=lahman`
and `source=save` for Trout's 2014/2016 MVPs, since Lahman didn't
filter active save bbref_ids). Awards-CLI `--era` is now {`all`,
`save`, `merged`}; the `--lahman-id` flag was renamed `--bbref-id`
to reflect that all merged-source identities are bbref.

PK = `(source, league_id, award_id, identity_key)` where
`identity_key = COALESCE(external_id, player_id::VARCHAR)`. DuckDB
PKs only accept column names so identity_key is materialized as a
post-CTAS column.


## Statcast inputs ARE in the OOTP per-PA dump (verified 2026-05-09)

I had previously implied — twice across two different planning notes —
that OOTP's per-PA log might not carry exit velocity / launch angle and
so a per-season Statcast cohort might not be feasible. **That was wrong
both times.** Verified the inputs directly:

- `f_pa_event.exit_velo` (DOUBLE) and `.launch_angle` (BIGINT) are
  populated 100% on `bip_flag = 1` rows.
- `f_pa_event` carries 877,363 PAs total in this save; **573,958 are
  BIP** (bip_flag = 1), all 573,958 with EV + LA values.
- EV range observed: **0.0 – 126.4 mph** (avg 81.8). LA range:
  **-75 – +88°** (avg 9.7°). Both realistic.
- Underlying L0 source: `l0_players_at_bat_batting_stats.exit_velo`
  + `.launch_angle` (and the same fields on `at_bats_event` in L1).

Calibration nuance carries over from the existing 2026-05-07 note on
save-side EV records: OOTP's EV scale runs ~5 mph below real Statcast
(save league-avg ~83 mph vs real ~88-89; save Henderson 88.5 vs real
Judge ~95). HARD_HIT_PCT scales proportionally lower. We surface the
save's own scale internally and call out the gap when comparing to
real-history Statcast tables.

L3 materialization shipped 2026-05-09 — `f_player_season_statcast_batting`
+ `_pitching` per (player, year, league_id, level_id) with BIP ≥ 30.
Six cohort fields per row: bip, max_ev (90th-percentile EV per
Statcast convention, NOT absolute peak), avg_ev, hard_hit_pct (EV ≥
95), sweet_spot_pct (LA ∈ [8°, 32°]), barrel_pct (Statcast expanding
window: EV ≥ 98 + LA ∈ [GREATEST(8, 26-(EV-98)), LEAST(50, 30+(EV-98))]).
Sample (Aaron Judge 2029 MLB): 112.0 maxEV / 86.8 avgEV / 34.2% HH /
17.1% Brl / 40.2% SS — recognizably-Judge profile on the save's
calibrated scale.


## players_pitching.csv — present in the dump, NOT in L0, useless in this save

Discovered 2026-05-09 during a comprehensive dump-CSV vs L0 audit (70
CSVs in dump, 69 L0 tables — one ingest gap).

**The file**: `players_pitching.csv` ships in every monthly dump. 67
columns: `player_id`, `team_id`, `league_id`, `position`, `role` plus
62 pitching rating cols matching the structure of
`l0_players_scouted_ratings`'s pitching subset (overall / vsR / vsL /
talent × 8 components, + 12-pitch arsenal cube × {current, talent},
+ misc velocity / arm_slot / stamina / ground_fly / hold).

**Why it exists**: OOTP exports two parallel rating views — objective
(true hidden values) and scouted (filtered through team scout
accuracy). `players_pitching.csv` is the objective view; the scouted
counterpart is `players_scouted_ratings.csv` (which IS in L0 as
`l0_players_scouted_ratings`).

**Why it's not in L0**: L0 ingest spec was written when scouted-
ratings was the focused need; objective `players_pitching.csv` was
never picked up. Same gap doesn't exist for batting (`l0_players_batting`
IS ingested) or fielding (`l0_players_fielding` IS ingested) — only
pitching.

**Why it doesn't matter for this save**: Verified by full-file scan
across 3 dumps (early / mid / latest of save's 45-dump history):
**every rating column reads `0` for every row.** OOTP zeroes the
objective files when scouting is enabled in the league settings —
your "Building the Green Monster" save has scouting on for the entire
lifespan. The 5 ID/state cols that ARE populated all duplicate fields
already in `players_current` / `roster_status_current` /
`players_ratings_current`.

**Conclusion**: defensive ingest fix only (closes the 70/69 gap, helps
portability if scouting is ever toggled off mid-save or a different
save is ingested with scouting disabled). No actionable data unlocks
in this save. Queued in BACKLOG, not prioritized.

**Same pattern probably applies to `players_batting.csv` /
`l0_players_batting`**: verified non-zero values only on
`running_ratings_*` cols (which we DO use, folded into
`players_snapshot`). The 28 batting rating cols are likely zeroed
for the same scouting-mode reason — the existing L1 builder only
folds running_ratings_* into snapshots, which is correct given the
scouting mode reality.


## The unused per-position fielding cube in players_fielding_snapshot

Discovered 2026-05-09 — same audit pass.

**`players_fielding_snapshot`** (L1, materialized from `l0_players_fielding`)
carries 19 columns we don't read anywhere:

- **`fielding_rating_pos1` through `fielding_rating_pos9`** — current
  fielding rating per position on the 20-80 scale, populated.
  Matches the convention from `l0_players_scouted_ratings` (which has
  the same 18 cols mirrored into `players_ratings_current`).
- **`fielding_rating_pos1_pot` through `_pos9_pot`** — ceiling
  fielding rating per position, populated.
- **`fielding_experience0` through `fielding_experience9`** — plays
  per position (objective experience metric). Index 0 is DH-ish;
  1-9 map to standard positions per `POSITION_NAMES`. Values appear
  to cap at ~200 (saturated experience).

**Sample — Justin Gonzales** (your 2029 MLB 1B, latest dump):

```
              current   ceiling   experience
pos1 (P)      0         60        0
pos2 (C)      0         0         0
pos3 (1B)    50        50       200    ← primary; saturated
pos4 (2B)     0        20         4    ← effectively can't play
pos5 (3B)     0        20         0
pos6 (SS)     0         0         0
pos7 (LF)    65        65       197    ← BETTER than 1B current
pos8 (CF)    50        50       200
pos9 (RF)    60        65       184
```

So Gonzales is currently a 50-rated 1B but a 65-rated LF with three
near-saturated OF positions. The ratings + experience answer "where
can this guy play?" definitively per player per dump.

**Other 10 fielding-skill cols**
(`fielding_ratings_infield_range` / `_arm` / `_error`,
`fielding_ratings_outfield_range` / `_arm` / `_error`,
`fielding_ratings_catcher_arm` / `_ability` / `_framing`,
`fielding_ratings_turn_doubleplay`) — same scouting-mode story as
`players_pitching.csv` above. Zeroed in this save because scouting is
on. Equivalent values ARE available scouted in
`players_ratings_current` / `players_ratings_snapshot`.

**This is the highest-value find of the audit**. **Shipped 2026-05-10**
as the "Defensive Profile" section on the player page:

- New `players_fielding_current` view registered alongside the other
  `_current` views in `l1_snapshot.py` (filters
  `players_fielding_snapshot` to latest `dump_date`). Brings the
  total to 7 `_current` views.
- New `PlayerPositionFielding` Pydantic schema; route handler
  unpivots the 9 `fielding_rating_pos1..9` + `_pot` +
  `fielding_experience1..9` triplets into a list of 9 rows
  (always — empty rows render as em-dashes via null normalization).
  ``fielding_experience0`` is intentionally not exposed (DH/unused
  bucket).
- `DefensiveProfileTable` in `PlayerStatsTab.tsx` — Pos / Current /
  Ceiling / Plays columns, sorted by experience desc so the spots
  the player has actually logged innings at appear first; rows with
  no rating + no experience are hidden. Cells color-coded by 20-80
  rating (≥70 emerald-bold, ≥60 emerald, 50 default, 40s amber,
  <40 rose).

Hover-flyout on roster rows is deferred — the player-page section
gives users the answer in two clicks, and a hover-flyout would
duplicate state machinery. Re-evaluate if the roster needs a
"defensive cohort filter" later.


## Combined bWAR / pWAR — OOTP supplies WAR directly (verified 2026-05-10)

Initially estimated as a multi-week build (defensive-runs model from
scratch). Revised 2026-05-09 to half-day. **Then revised again 2026-05-10
to ~2 hours** after a one-line audit query: OOTP **directly supplies**
the canonical combined WAR.

```sql
SELECT table_name, column_name FROM information_schema.columns
WHERE column_name IN ('war', 'ra9war') ORDER BY table_name;
```

returns six tables — every fact table in the warehouse already has
`war` populated. Audit (`reconcile.py` line 211 + 393) had been
reconciling these against IE WAR as **A-tier** (direct dump field)
since 2026-05-04 with tolerance 0.10-0.15:

```
Mayer    PA=582  warehouse 3.2 vs IE 3.2  ✓ EXACT
Anthony  PA=535  warehouse 0.9 vs IE 0.9  ✓ EXACT
Crochet  IP=178.2 warehouse 5.5 vs IE 5.5 ✓ EXACT
Whitlock IP=55.0  warehouse 0.4 vs IE 0.4 ✓ EXACT
```

**What OOTP packs into the WAR field**:
- For batters (`players_career_batting.war`): offense (wRAA) +
  defense (`zr` + `framing` + `arm`) + positional adjustment +
  base-running. The full bWAR equation, with OOTP's own scaling.
- For pitchers (`players_career_pitching.war`): FIP-WAR with
  leverage adjustment for relievers + OOTP's replacement-level
  scaling. Runs ~1.5-2 wins higher than our custom flat-1.13
  `pit_war` for top starters.
- Pitchers also have `players_career_pitching.ra9war` — the
  runs-allowed parallel (sensitive to defense + sequencing).

**What was actually built** (2026-05-10):
- `f_player_season_advanced_batting.b_war` = `SUM(f_player_season_batting.war)`
  per (player, year, league, level), `split_id=1`.
- `f_player_season_advanced_pitching.p_war` =
  `SUM(f_player_season_pitching.war)` (same grain).
- `f_player_season_advanced_pitching.p_ra9_war` = parallel for `ra9war`.
- Surfaced on roster Advanced view (replacing the offense-only `oWAR`
  / custom-FIP `pit_war`) and on the player page Advanced sections
  (alongside the custom variants — gap reveals the defensive component
  for batters / leverage + replacement-scaling differences for pitchers).

**Custom WAR alternatives still live in the warehouse** for the
glossary cross-reference. A user reading the Advanced section sees:
- `oWAR` (offense-only, wRAA-based formula) vs `bWAR` (combined,
  OOTP-supplied) → gap = defensive runs + positional adjustment +
  base-running.
- `pit_WAR` (FIP-only, flat-1.13-replacement) vs `pWAR` (FIP-WAR
  with leverage, OOTP-supplied) → gap = leverage + scaling.
- `pWAR` vs `RA9_WAR` → gap = sequencing/defense vs skill differential.

**Defensive components remain in `f_player_season_fielding`** — `zr`
+ `framing` + `arm` + the difficulty-bucketed `opps_made_X / opps_X`
columns are still there, just folded into the canonical WAR rather
than recomputed. They're available for an inspectable Diamond-side
dWAR if we ever want one (the original "build from scratch" plan).
For now: surfacing OOTP's value gives users the IE-canonical number
in one column with provenance documented; the inspectable variants
sit alongside it.


## Service-time encoding in `roster_status_current` (decoded 2026-05-10)

`roster_status_snapshot.mlb_service_years` + `mlb_service_days` follow
the MLB / MLBPA convention exactly:

- **172 service days = 1 service year**. Players accrue up to 172 days
  per season (the regular-season day count); Sept call-ups can finish
  with <172 even if rostered all month.
- `mlb_service_years` = `floor(mlb_service_days / 172)`. Whole years.
- `mlb_service_days` = total accumulated days, career-to-date.
- `mlb_service_days_this_year` = days credited in the current calendar
  year (the in-season component of total days).

**Display convention** (Bref / MLBPA): "Xy Yd" where Y = leftover days
= `mlb_service_days - 172 * mlb_service_years`. Examples:

```
Mayer:    years=4,  days=816   → "4y 128d"   (816 - 4*172 = 128)
Crochet:  years=9,  days=1576  → "9y 28d"    (1576 - 9*172 = 28)
Devers:   years=12, days=2134  → "12y 70d"   (2134 - 12*172 = 70)
```

**FA / arb boundaries** — service days drive contract status:

```
< 516 days  (3.000y)  → pre-arb        (renewable contract)
< 1032 days (6.000y)  → arb-eligible   (3 arb years before FA)
≥ 1032 days (6.000y)  → FA-eligible    (free agency at end of contract / season)
```

The route's `_service_class()` helper bucket-maps total days to a
class id (`pre_arb` / `arb_y1` / `arb_y2` / `arb_y3` / `fa_eligible`)
and a display label.

**Super-Two qualifiers** — the early-arb edge case for high-service-day
pre-arb players (typically the top ~22% of 2-3y players by service
days each year) — are NOT modeled in v1. OOTP handles internally and
exposes no public flag on `roster_status_*` that I've found. A small
fraction of "Pre-arb" labels in the UI will technically be Super-Two
arb-eligible; the gap is one year of arbitration leverage and the
display class doesn't drive any computation. Revisit if Diamond ever
ships a salary-projection / arb-decision tool.

**Options** — `options_used` follows MLB's 3-options-per-player
convention: once a player has been optioned to AAA/MiLB across 3
distinct years, they're out of options. `options_used_this_year`
ticks up only on the first option of a calendar year. Distribution
across the warehouse: 0 (most), 1, 2, 3 — matches expectation. After
3 options used, a player can no longer be sent down without DFA;
this is what makes "out of options" a roster-construction constraint
worth surfacing on the player page.

**Status flags** (`is_active` / `is_on_secondary` / `is_on_dl` /
`is_on_dl60` / `designated_for_assignment` / `is_on_waivers`) — all
booleans (BIGINT 0/1 in the warehouse, normalized to bool in the API).
The November end-of-season snapshot has every transactional flag
cleared (DL/DFA/waivers all 0). In-season ingests will surface them.
The UI renders only truthy flags as small color-coded chips so the
header stays calm in the offseason.

**Fields not surfaced (semantics unclear)**:
- `years_protected_from_rule_5` — every row in this save reads 4 or
  5; could be "years remaining of Rule 5 protection" or a related
  cap, but I haven't been able to verify the semantics from data
  alone. Skip for v1.
- `has_received_arbitration` — every row reads 0 in the November
  snapshot. Likely a flag/count tied to the in-season arb hearing
  cycle (February-March); skip until a winter ingest surfaces nonzero
  values.

## Pre-save MLB league baselines via Lahman + BREF (2026-05-12, D20)

OOTP imports pre-save real-history player counting stats (Bonds 2001,
Mantle 1956, Pedro 2000, Trout 2018, etc.) into `players_career_*` —
this save has 410,909 batting rows from 1871-2025 in
`f_player_season_batting`, 234,677 of them at split_id=1. But OOTP does
**not** emit corresponding `league_history_*` rows for those years, so
the L3 advanced builders (which LEFT JOIN by `(league_id, year, level_id)`)
emit nulls for every advanced stat on imported player-seasons.

D20 closes the gap by UNIONing two component views:
- **`_lg_constants_advanced_native`** — sources from
  `league_history_*_event` (OOTP-native, save years only — 2026-2029
  in this save).
- **`_lg_constants_advanced_imported`** — sources from
  `history_lahman_batting/_pitching` for 1871-2019 + `history_bref_batting/_pitching`
  for 2020-2025, summed across AL/NL/AA/FL/NA/PL/UA into the OOTP
  MLB league_id=203, level_id=1 (matching D11's "no AL/NL split"
  convention).

The final consumer-facing view `_lg_constants_advanced` is a
UNION ALL with a NOT EXISTS guard — native rows always win on key
collision (which can only happen if `fetch-history` ever loads
post-save years; the loader's `MAX_HISTORY_YEAR = save_start - 1`
prevents it, but the guard is defensive).

**BREF level filter**: BREF carries level codes `Maj-AL` and `Maj-NL`
(not `MLB`). Filter must be `Lev IN ('Maj-AL','Maj-NL')`. Discovered
in implementation — earlier code drafted as `Lev = 'MLB'` returned
zero BREF rows.

**Self-consistency**: empirically verified that Lahman 2001 NL+AL
aggregates match OOTP-imported player-row aggregates within 0.5%:
Lahman AB 166,234 = OOTP AB 166,234 (exact); Lahman H 43,879 = OOTP
H 43,879 (exact); minor IBB / HBP edge cases drift ≤1 PA. OOTP
imports Lahman directly, so league baselines are *guaranteed*
consistent with the player rows that JOIN against them. No risk
of "Bonds 2001 wOBA above league" producing a wrong wRC+ because
the league denominator is mis-sourced.

**Coverage delivered** (live warehouse spot-checks):
- `_lg_constants_advanced` view: **1871-2029 continuous, 215 rows**
  (60 native + 155 imported).
- `f_player_season_advanced_batting`: 30,440 → **244,183 rows** (8×).
- `f_player_season_advanced_pitching`: similar fill.
- Bonds 2001: wOBA .550, OPS+ 257 (BBR 259), b_WAR 12.5 (BBR 12.5 — exact).
- Pujols 2003: OPS+ 189 (BBR 189 — exact), b_WAR 9.6.
- Trout 2018: OPS+ 198 (real Fangraphs 198 — exact), b_WAR 8.3.
- Pedro 2000: ERA+ 285 (BBR 291 — within 6 pts), p_WAR 9.8.
- Mantle 1956: OPS+ 220 (BBR 210 — modern Yankee Stadium PF gap).

**Lahman historical sparsity** is the principal limitation:

| Column | First populated | Pre-track behavior |
|--------|-----------------|--------------------|
| IBB | 1955 | nulls coalesced to 0 |
| SF | 1954 | nulls coalesced to 0 |
| HBP | 1887 | nulls coalesced to 0 |
| SH | 1894 | nulls coalesced to 0 |
| SO (batting) | ~1913 (varies by team) | nulls coalesced to 0 |

This is the Fangraphs convention; OOTP imports zeros for
pre-tracking columns too, so player-rows + league-rows stay
self-consistent. Pre-1955 wOBA scale calibrates against the
partial-data sums, which means absolute values won't match
modern Fangraphs historical wRC+ exactly — but they're consistent
across the era.

**Park factors for pre-2026** are the second known limitation.
OOTP `f_player_season_*.team_id` is the player's *current-day*
team (or whichever team OOTP imported them under), and that
team_id joins to the modern `teams.park_id` → `parks.avg`. So a
2001 SF Giants row resolves to Oracle Park (1.003), not 2001
Pacific Bell. Park enters OPS+ at half-leverage and ERA+ at
80%-leverage, so the bias is small in practice (most parks haven't
shifted dramatically) — but real fix needs BREF historical team-year
park factors plus an (OOTP team_id, year) → bbref_team_id
crosswalk. Backlogged. wOBA / wRC+ / wRAA aren't park-adjusted in
our formulas anyway, so they're unaffected.

**Pre-save *minor*-league seasons** (Lahman MiLB, OOTP league_ids
204-218 and friends) stay null for advanced stats. Lahman's MiLB
coverage is spotty and the OOTP↔real league_id crosswalk for
IL/PCL/EL/etc. isn't bijective. Backlogged. Counting stats for
those rows are unaffected.

**Soft-skip behavior**: `build_l3_advanced` checks for
`history_lahman_batting/_pitching` + `history_bref_batting/_pitching`
in `information_schema.tables`. If any are missing (fresh warehouse
that hasn't run `diamond fetch-history` yet), the imported view is
not registered and `_lg_constants_advanced` falls back to native-only
with a yellow `!` indicator instead of a hard fail. Smoke test runs
in fresh in-memory DBs and exercises this fallback cleanly.

**wRC+ formula caveat (pre-existing, surfaces more here)**: Diamond's
wRC+ is park-blind (no parkFactor term in the formula). It runs
~10-15% higher than real Fangraphs canonical values for the same
season (Mookie Betts 2018: ours 217 vs real 185). This is not
introduced by D20 — same bias hits save-side data (it's just less
visible without a real-world reference). OPS+ *is* park-adjusted
(halved factor) and matches real BBR within 1-3 points. Fixing wRC+
to be park-adjusted is a separate refactor; the current values are
useful for cross-season comparisons within a player's own career
arc but should not be compared 1:1 with published Fangraphs wRC+.
