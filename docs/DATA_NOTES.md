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
| `players_at_bat_batting_stats.csv` | **Resets at season start (Feb-Mar dump).** `dump_2026_11` and `dump_2026_12` are byte-identical (95 MB). `dump_2027_03` is 3 MB (spring training only). | The Nov dump IS the canonical season at-bat snapshot. |
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

## Pending codebooks (not yet decoded)

- `players_awards.award_id` — 13 distinct values; likely MVP, CY, RoY, Manager of Year, Gold Glove (×9 positions?), Silver Slugger, All-Star, HOF, etc.
- `players_league_leader.category` — 60 distinct values; map of stat code → stat name
- `players_streak.streak_id` — 21 distinct values; types likely include hitting streak, on-base streak, games-played streak, K-streak (pitcher), no-hit-allowed, etc.
- `players_injury_history.body_part` — integer code

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
- **Athletics' DSL team** (id 177) has `parent_team_id = 0` — only MLB-org affiliate where the FK is missing. Cross-check with `team_affiliations.csv` instead of relying on `parent_team_id` alone.
- **`players.inducted` is the year of HOF induction**, not a boolean (e.g., Hank Aaron's row shows `inducted = 1982`).
- **`import_export` org reports show ALL of a player's season stats**, including time on prior orgs (mid-year trades), team_id=0 (amateur/college), and short-season prospect leagues (lg=75). Do NOT filter by team_id when reconciling.
- **`players_league_leader.csv` only covers post-save years** — pre-save year leaders aren't recorded. For "Building the Green Monster" save (started 2026), only 2026-2029 leader data exists. Historic leaders must be derived from `players_career_*` aggregates.
- **`league_history_all_star.csv`** has 5,869 rows over 95 years but no entries for 2029 yet — All-Star game may not have been played in current sim cycle. Investigate.
- **OOTP IP convention**: stored as `outs` integer; display as `FLOOR(outs/3) + (outs%3)*0.1`. E.g., 517 outs = 172 innings + 1 out remainder = displayed "172.1" (NOT 172.4).
- **`players_career_*` stints**: when a player plays for multiple teams in one season (trade, recall), they get multiple rows with incrementing `stint`. Sum across stints for season totals.
- **Trade summaries** in `trade_history.csv` use `<entity:type#id>` tags (e.g., `<Houston Astros:team#12>`, `<Bryan King:player#20728>`) — parseable into structured player/team references.

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
- **`hit_xy`**: 0-255 lateral position. Low = LF-side, high = RF-side. Used for Pull/Cent/Oppo derivation. ZERO values represent "no spatial coordinate" (~50 BIP per result code).
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
