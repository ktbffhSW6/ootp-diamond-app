# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-04 (in-game year 2029) — second sweeping pass: financial_info 12/12, superstats BIP swap, contract extensions decoded

---

## One-line summary

Diamond is in **audit phase** — we're confirming what data we can reliably
extract from OOTP monthly dumps before designing the warehouse schema and
building the ingest pipeline.

## What works today

- **Project skeleton**: Python 3.14 + DuckDB + Polars + Typer, package at `src/diamond/`, editable install via `pip install -e .[dev]`
- **CLI commands**: `diamond decode`, `diamond decode-codes`, `diamond reconcile`, `diamond coverage`, `diamond advanced`
- **Codebook decoder** ([src/diamond/audit/decode.py](src/diamond/audit/decode.py) + [decode_codes.py](src/diamond/audit/decode_codes.py)) — empirically discovers OOTP integer-code meanings. Verified codebooks live in [src/diamond/constants.py](src/diamond/constants.py):
  - **First pass** (at-bat domain): `GameType`, `SplitId`, `AtBatResult` — all verified by exact aggregate match
  - **Second pass** (awards/leaders/streaks/injuries): `AwardId` (13 codes, cross-ref'd with league_history), `LeaderCategory` (47 of 60 cleanly matched), `StreakId` (21 codes profiled), `BodyPart` (12 codes profiled)
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py)) — per-column comparison of `import_export` Red Sox roster CSVs against derivations from monthly dump CSVs. **~210 of ~360 columns reconcile cleanly** across all 21 files at the full 220-player Red Sox org tree (MLB + AAA + AA + A+ + A + Rookie + DSL × 2 + FCL). See the per-file scorecard below.
- **Coverage audit** ([src/diamond/audit/coverage.py](src/diamond/audit/coverage.py)) — profiles dump CSVs supporting 11 user-facing features (standings, playoffs, awards, leaders, streaks, HOF, movements, records, all-stars, league history, injuries).
- **Advanced stats library** ([src/diamond/advanced/](src/diamond/advanced/)) — 5 tiers of modern advanced stats from at-bat data (~25 metrics):
  - `league_constants.py` — per-league-year linear weights, FIP const, lgERA (verified against real MLB norms)
  - `enriched.py` — reusable at-bat view with bip/risp/late-close/spray flags
  - `contact.py` — Tier 1: HardHit% buckets, SweetSpot%, Barrel% (Statcast formula), Squared%, EV by GB/LD/FB, Pull/Cent/Oppo, pitcher contact-quality allowed
  - `situational.py` — Tier 2: empirically-derived RE matrix, RE24 exposure, RISP/2-out/loaded splits, pinch/late-close, by-inning, leverage tiers, vs-pitcher H2H
  - `sabermetric.py` — Tier 3: wOBA, wRAA, wRC, wRC+, OPS+, ERA+, FIP, Power-Speed, Speed Score, isoP/isoD
  - `defensive.py` — Tier 4: RF/9, RF/G, Catcher Framing+, OF Assist Rate
  - `approach.py` — Tier 5: 2-strike performance, count-state splits, 4-pitch BB%, 3-pitch K%

## Most-recent change (second sweeping pass, 2026-05-04 evening)

Tackled the "what's left" backlog. Changes:

- **financial_info: 2/12 → 12/12 at 100%**. Decoded ECV (sum of `players_contract_extension.salary*`), ETY (extension years), MLY/SECY (mlb_service_years/secondary_service_years), OPT/OY (options_used/options_used_this_year), ON40 (is_active OR is_on_secondary). Also fixed SLR/CV/YL: SLR uses `salary[current_year]` (current_year is 0-indexed, not 1-indexed); CV sums salary0..14 (was just 0..7, missed 12-yr deals); YL = `years - current_year` (dropped the +1). Matcher now strips `(arbitr.)` annotation in addition to `(auto.)`.
- **batting_superstats_2 / pitching_superstats_2 lifted from 0% F-tier to 3 A-tier each**. Added TM (teams.name; appends '(INT)' for `players_roster_status.league_id < 0` pseudo-leagues like the international FA pool — 100%), LG (leagues.abbr — 100%), PI (sum of `pitches_seen` / `pi` — 95-96%). Plate-discipline % cols stay F-tier per D5.
- **Superstats BIP swap**: replaced at-bat-counted BIP with PCB-derived `AB-K+SF+SH` summed across US-affiliated levels. batting BIP 7%→80%, pitching BIP 9%→72%. Foreign-league players whose at-bats aren't in the dump now get correct BIP from PCB.
- **Multi-level OPS+/ERA+ explored**: confirmed mismatches are caused by IE using a level-weighted park factor (vs our halved-Boston-park). Logged for future; ~5-10pp error on 12 multi-level players.
- **hit_xy spray boundaries grid-searched**: no x-bin variant gives meaningfully better Pull/Cent/Oppo% than current. Suspect OOTP uses `hit_loc` not `hit_xy` for spray classification. Left as-is.

**16 of 21 files now at 100% reconciliation coverage (A+B).**

## Earlier today (first sweeping pass)

Sweeping reconciliation pass — pushed everything we could to 100% match while preserving the audit's full 220-player population. Highlights:

- **All 6 ratings/potential files at 100% A-tier**: VELO and G/F integer→string mappings decoded (VELO 0-19 → '75-80 Mph' band, G/F 0-100 → EX FB / FB / NEU / GB / EX GB buckets).
- **pitching_stats_2 unknowns decoded**: `RA = G - GS` (97% match), `RSG = rs / GS` (run support per START, 99%), `pLi = SUM(li) / SUM(BF)` (100%), `CG%` and `IRS%` (100% each).
- **League-constants sabermetrics wired up** via inline CTE pulling from `league_history_*_stats`: RC (100%), RC/27 (99%), wOBA (79%), OPS+ (60%), ERA+ (62%), FIP (69%). All previously C-tier, now B-tier. Bill James technical RC verified Mayer 72.5=72.5 exact. OPS+/ERA+ formulas verified against MLB-only Sox players (8/9 exact).
- **Small rounding edges fixed**: OPS 79→100%, HR/9 95→100%, K/9 91→100%, BB/9 100%. Pitching WAR 84→90% (some multi-stint cascade still).

Notable formula discoveries documented in DATA_NOTES:
- OPS+ = `100 * (OBP/lgOBP + SLG/lgSLG - 1) / (1 + (park.avg - 1) / 2)` (halved park factor)
- ERA+ = `100 * (lg_ERA / pERA) * (1 + (park.avg - 1) * 0.8)` (Boston empirical fit ~1.04)
- RC (Bill James technical): `((H+BB-CS+HBP-GIDP) * (TB + 0.26*(BB+HBP) + 0.52*(SH+SF+SB))) / PA`
- RA (relief appearances) = `g - gs`; RSG = `rs / gs`; pLi = `sum(li) / sum(bf)`

## Earlier this session

Cross-referenced reconciliation notes from a separate OOTP audit project (`docs/helpful_files/`) and closed several gaps in one pass:

- **Popularity codebook** decoded: 7 buckets, 0=Unknown..6=Extremely Popular. `popularity_info` now 6/6 A-tier (was 3/5).
- **Personality buckets** decoded: 0–200 personality values bucket as <60=Low, 60–139=Normal, ≥140=High. `personality___morale` now 6/6 A-tier (was 1/6); 4 fresh-acquisition rookies show `Unknown` in IE which we can't recover from a hard bucket — that's a small known mismatch.
- **Scout accuracy codebook**: 1=V.Low, 2=Low, 3=Avg, 4=High, 5=V.High. Added as a 6th column to `popularity_info`.
- **HOF year** confirmed direct via `players.inducted`. No `players_awards` cross-ref needed.
- **All-Star 2029 gap** explained: `league_history_all_star` only writes at year-end / postseason rollup, so a Nov dump captured before that step has no current-year row. Not a formula issue.
- **hit_xy spray decode** landed (partial): `x = floor(hit_xy/16)` with switch hitters using opposite of pitcher.throws. Naive [0,4]/[5,10]/[11,15] bins under-count Pull% by ~5–10pp consistently — exact OOTP boundary still TBD.
- **Big future unlock surfaced**: `league_history_*_stats` already ships per-league/year/level wOBA/RC/FIP/ERA/WHIP/WAR/etc. pre-computed. The "league constants module" is mostly a lookup, not a recompute.

Codebooks added to `src/diamond/constants.py` as `Popularity`, `ScoutingAccuracy`, and `personality_bucket()` helper. See [docs/DATA_NOTES.md](docs/DATA_NOTES.md) for verification details.

## Reconciliation status (most recent run)

**All 21 `import_export` files now audited.** Below: the per-file scorecard with
columns reconciled / total cols. Tier counts: A=direct, B=trivial calc,
C=needs league constants or formula TBD, D=modeled (xstats), E=at-bat aggregation,
F=cannot replicate (per D5 or string-format), G=needs scale conversion.

| File | Reconciled | Outstanding |
|---|---|---|
| `batting_stats_1` | **24/24** | — (OPS+ wired up via league constants 2026-05-04) |
| `batting_stats_2` | **18/18** | — (RC/RC27/wOBA wired up 2026-05-04) |
| `pitching_stats_1` | **25/25** | — (ERA+/FIP wired up 2026-05-04) |
| `fielding_stats` | **12/12** | — |
| `batting_ratings` | **18/18** | — |
| `batting_potential` | **11/11** | — |
| `pitching_ratings` | **12/12** | — (VELO + G/F int→string decoded 2026-05-04) |
| `pitching_potential` | **10/10** | — (VELO + G/F decoded 2026-05-04) |
| `fielding_ratings` | **9/9** | — |
| `individual_pitch_ratings` | **15/15** | — (VELO decoded 2026-05-04) |
| `individual_pitch_potential` | **15/15** | — (VELO decoded 2026-05-04) |
| `position_ratings` | **10/10** | — |
| `pitching_stats_2` | **25/26** | — SIERA C-tier (only). RA/RSG/pLi/CG%/IRS% all decoded 2026-05-04 |
| `batting_superstats_1` | partial 22/25 (E-tier) | EV-bucket cutoffs need investigation; xBA/xSLG/xwOBA (D); Pull%/Cent%/Oppo% need hit_xy decode |
| `pitching_superstats_1` | partial 13/17 (E-tier) | same EV/bucket issues; xBA/xSLG/xwOBA/xERA (D) |
| `batting_superstats_2` | **3/20** | 17 plate-discipline % cols F-tier per D5 (no per-pitch data); TM/LG/PI all 100% |
| `pitching_superstats_2` | **3/19** | 16 plate-discipline % cols F-tier per D5; G/GS/PI all 100% |
| `default` | 3/6 | SLR/YL string-formatted; MLY TBD |
| `popularity_info` | **6/6** | — (Nat./Loc. Pop. + SctAcc decoded 2026-05-03) |
| `personality___morale` | **6/6** | — (LEA/LOY/FIN/WE/INT bucketed 2026-05-03; 4 rookie mismatches expected) |
| `financial_info` | **12/12** | — (ECV/ETY decoded from players_contract_extension; MLY/SECY/OPT/OY/ON40 from players_roster_status; SLR/YL/CV current-year-salary semantics fixed 2026-05-04) |

Headline numbers: across the 21 files, of ~360 total IE columns:
- **~250 reconcile cleanly (A/B)** — gained ~40 from 2026-05-04 sweeping pass
- ~50 are F-tier by design (D5: plate-discipline; string-formatted display fields)
- 0 G-tier (all int→string mappings decoded: DEF, popularity, personality, SctAcc, VELO, G/F)
- ~5 C-tier remaining (SIERA, contract extension/option fields)
- ~15 D-tier (xstats — xBA/xSLG/xwOBA/xERA, modeled from EV/LA)
- ~25 partial-match E-tier (Statcast superstats — spray boundary, multi-level players' BIP denominator)
- 15 of 21 files at **100% reconciliation coverage** (A+B):
  fielding_stats, batting_ratings, batting_potential, pitching_ratings, pitching_potential,
  fielding_ratings, individual_pitch_ratings, individual_pitch_potential, position_ratings,
  popularity_info, personality___morale, batting_stats_1, batting_stats_2, pitching_stats_1, pitching_stats_2 (25/26)

Latest reports (audit_output/ — gitignored, regenerate with the CLI commands):
- [decoder_report.md](audit_output/decoder_report.md) — `diamond decode`
- [codes_decoder_report.md](audit_output/codes_decoder_report.md) — `diamond decode-codes`
- [reconciliation_report.md](audit_output/reconciliation_report.md) — `diamond reconcile`
- [coverage_report.md](audit_output/coverage_report.md) — `diamond coverage`
- [advanced_stats_report.md](audit_output/advanced_stats_report.md) — `diamond advanced`

## What's next (per user direction)

User has chosen to **finish the audit phase before any schema/ingest design**.
Audit completion order from [BACKLOG.md](BACKLOG.md):

1. ~~Reconcile the remaining 16 `import_export` files~~ — **DONE**.
2. ~~Investigate the **DEF rating formula**~~ — **DONE**. Was `fielding_rating_pos[player.position]`.
3. ~~**Popularity / Personality / SctAcc** integer→string mappings~~ — **DONE** (this session, via helpful_files cross-ref).
4. ~~All-Star 2029 gap, HOF induction year~~ — **DONE** (no formula needed; `players.inducted` is direct, all-star file just doesn't write until year-end).
5. ~~Broaden the ratings-CTE audit population~~ — **DONE** (this session). league_id=203 filter dropped, joined population now full 220-player Red Sox org tree.
6. **NEXT**: **Build league constants module** (now mostly a lookup over `league_history_*` pre-computed wOBA/FIP/ERA/WHIP/WAR — see DATA_NOTES). Unlocks the ~30 C-tier sabermetric holdouts.
7. Resolve small rounding edges (OPS 79%, HR/9 95%, K/9 91%, pitching WAR 84%).
8. Calibrate `hit_xy` spray boundaries — basic decode landed but Pull%/Oppo% under-/over-count by ~5–10pp; grid-search x boundaries against IE values.
9. Remaining integer→string mappings: VELO ranges, G/F categories, contract auto-renew, personality "Type" archetype.
10. Decode `<entity:type#id>` tags in `trade_history.summary` for structured movement parsing.
11. Investigate OOTP's exact EV-bucket cutoffs for Soft%/Avg%/Solid% (Statcast superstats_1).
12. Decode `pLi` (`career_pit.li` is "average leverage index" per dump dictionary — but neither sum nor avg matches IE; possibly per-stint compounding).
13. Decode `RA` in pitching_stats_2 (small int that doesn't match raw `r` or per-9 RA).
14. Bonus: verify the 13 unmapped `LeaderCategory` codes by computing the missing sabermetric stats.

After full reconciliation: schema design + ingest pipeline (per the L0-L4 layers sketch from earlier sessions).
