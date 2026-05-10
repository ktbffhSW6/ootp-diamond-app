# Project Status

> **Read this first at the start of every session.** It describes the current
> state of the project, what was last done, and what is most likely next.
> Update this file at the end of every substantive session.

**Last updated**: 2026-05-17 (late evening) — **D40 committed: Phase 4 (Audit Closure + Warehouse Maximization), Phase 5 (Almanac), Phases 6-8 sketched.** Post-D39 strategic discussion surfaced four orthogonal architectural insights: (1) OOTP writes authoritative wOBA / FIP / OPS / BABIP / WHIP / ISO directly to `l0_team_*_stats` columns and we never used them; (2) we have no game-grain fact table so "last 12 days Merrill" and time-series queries are impossible; (3) we under-applied the snapshot pattern — only state tables get per-dump history, never derived stats; (4) Phase 1 was closed prematurely with research items still on the carry-forward list. **D40 is the strategic commitment to close audit properly + maximize the warehouse before continuing to the Almanac.** Goal: richness × accuracy × flexibility, save-agnostic by construction. **See DECISIONS.md D40 for the full architectural commitment + phase-by-phase plan.**

**Earlier same day**: D38 Padres reconciliation pass + wOBA formula correction. After D37 stabilized the Padres save, user provided OOTP control data (`docs/helpful_files/recon/Padres/`: 21 stat CSVs + 65 screenshots, all 7/31/2028) and asked to reconcile sim stats to OOTP IE before layering in baseball history. Three D38 changes:

| # | Item | Result |
|---|---|---|
| 1 | **Multi-save reconciler infra** — `_resolve_ie_path` org-agnostic suffix match + `--ie-dir`/`--save` CLI flags + scouting-stamp fix so audit reads from any folder of IE CSVs on any save | Reconciliation now works on Padres (was Sox-only); 21 FileSpecs unchanged |
| 2 | **wOBA formula correction** — OOTP uses BASE linear weights × PA denominator (not the FanGraphs scaled-weights × (AB+uBB+SF+HBP) form). Verified against Bastidas 2028 IE=.357 — old Diamond .372, new Diamond .356. Fix landed in `l3_advanced.py` (player_woba + lg_woba in both Native/Imported views) and `reconcile.py` BATTING_DERIVED_CTE | wOBA tier: 76% → **94%** match (8 small-sample DSL outliers remain) |
| 3 | **Accuracy floor documented** — 197 A-tier columns at 100%, 43 B-tier at 94-100% (rounding-grade). Statcast aggregation (33 E-tier cols), xBA/xSLG/xwOBA (7 D-tier), and pitch-tracking (36 F-tier) flagged for future investigation; pitch-tracking permanently unrecoverable (OOTP-internal). | ~85% of reconcile columns at OOTP-canonical accuracy |

**Verification post-fix**: Bastidas 2028 wOBA Diamond .356 vs IE .357 ✓; Ocopio .287/.288 vs IE .282 ✓; Merrill OPS+ 124 vs IE 125, b_war 3.6 vs IE 3.6 ✓. All 21 reconcile files run cleanly; output at `audit_output/reconciliation_padres_2028_07.md`.

**Deferred to future sessions** (all in BACKLOG / todo list):
- Statcast spray classification (Pull/Cent/Oppo at 5-18% match) — hit_xy encoding semantics deep-dive
- Statcast aggregation alignment (EV/LA/HHi/Barrel% at 53-86%) — BIP cutoff + weighting
- xBA/xSLG/xwOBA formula divergence — OOTP IE includes non-BIP credit?
- Phase 1+ work (HoF Lahman drop, lref_player_*, Retrosheet, Almanac UI, stretch comparator)

---

## Active phase map (post-D40, committed 2026-05-17 evening)

**Goal: richness × accuracy × flexibility, save-agnostic by construction.**

```
Phase 1 — Audit (initial pass)            ✓ 2026-05-04 (milestone close; residuals open)
Phase 2 — Warehouse + analytics           ✓ 2026-05-06
Phase 3 — UI implementation               ✓ ~85% shipped; residuals fold into 4b UI work
─────────────────────────────────────────
Phase 4a — Audit closure                  ← NEXT, ~2-3 dev-days
Phase 4b — Maximize the warehouse         ← THEN, ~5-6 dev-days
Phase 5  — The Baseball Almanac           ← ~10-14 dev-days
Phase 6  — Multi-save scaffolding         ← ~3-5 dev-days
Phase 7  — AI as analytical layer         ← ~3-5 dev-days
Phase 8  — Polish + distribution          ← deferred post-summer
```

**See DECISIONS.md D40** for the full architectural commitment including dependency chain, storage projection, non-goals, and per-phase exit criteria. Summary below.

### Phase 4a — Audit Closure (~2-3 dev-days)

Closes the carry-forward research queue before any new warehouse work. Each deliverable resolves a specific open item:

| # | Deliverable | Closes |
|---|---|---|
| 1 | **L0 inventory pass** (`scripts/inventory_l0_coverage.py`) — every L0 column ↔ where it's consumed | Definitive "what we missed at the start" |
| 2 | **Authoritative team-stat columns wired** — `l0_team_*_stats.{woba,fip,babip,whip,ops,iso,...}` exposed via L1 views; new L2 facts for `players_value` / `players_league_leader` / `players_individual_batting_stats` / `players_salary_history` | Unused-authoritative-data class |
| 3 | **MiLB levels 5-8 advanced-stats backfill** — Short-Season A / Complex / DSL / AFL coverage | Pre-2026 minor rows rendering "—" |
| 4 | **EV-bucket OOTP-canonical calibration** — grid-search Soft/Avg/Solid against IE | DATA_NOTES "OOTP EV cutoffs unknown" |
| 5 | **`hit_loc` semantic decoding** — map every code to a field zone | `IFH%` permanently NULL, sharper-spray blocker |
| 6 | **Multi-level OPS+/ERA+ refinement** — ~5-10pp error on multi-stint players | BACKLOG carry-forward #1 |
| 7 | **Permanent-limitation writeup in DATA_NOTES.md** — codes 44+49, OOTP developed-pitch state, F-tier pitch-tracking | Audit hygiene |

**Exit criteria**: BACKLOG's `Audit phase — carry-forward` section is either resolved, re-classified to a later phase, or marked permanent. Zero ambiguity.

### Phase 4b — Maximize the Warehouse (~5-6 dev-days)

Adds four snapshot tiers + invariants watchdog + per-player calibration. Save-agnostic — every builder reads `<save>/diamond/diamond.duckdb`, no IDs hardcoded.

**Tier A — Game-grain fact tables** *(time-series foundation, ~0.5 day)*

```
f_player_game_batting / _pitching / _fielding   PK includes (player_id, year, game_id)
```

Built from existing L0 + `games_event` JOIN to denormalize `date` directly. DuckDB sort key on `(player_id, date)`. Unblocks "last 12 days Merrill", calendar heatmaps, streak engine inputs, Phase 5 stretch comparator.

**D40 invariants watchdog (`_diamond_invariants`)** *(self-validation, ~1 day)*

New table written after every `diamond ingest` recording per-team / per-league drift across 10 high-leverage metrics (team wOBA / FIP / BABIP / WHIP / OPS, league wOBA, event-count consistency PA/K/HR/AB). Sources of truth: `l0_team_*_stats` and `career_bat` / `career_pit` aggregates. Surfaces: CLI summary, `GET /api/admin/invariants` endpoint, cockpit drift status pill (green / amber / red), historical drift trends across dumps.

**Tier B — Per-dump derived-stat history snapshots** *(SCD Type 2 on L3, ~1 day)*

```
f_player_season_advanced_batting_history    PK = (..., dump_date)
+ pitching / statcast batting+pitching / xstats batting+pitching
```

Every ingest appends a new row per player-year-dump. Current L3 fact tables become `_current` views filtered to `MAX(dump_date)`. Unblocks trajectory queries, real sparklines, engine-patch detection, reconciliation history.

**Tier C — Per-dump leaderboard snapshots** *(as-of records, ~0.5 day)*

`f_record_player_history` + `f_award_race_history`. Enables "who was leading on June 1?" — impossible today.

**Tier D — Rolling-window views** *(query accelerators, ~0.5 day)*

Materialized: `v_player_last_7_batting / _15 / _30`, `v_player_last_5_starts_pitching`, `v_player_calendar_heatmap`.

**Per-player calibration improvements** *(~0.5 day)*

Replace D39 flat constants with player-rating-aware functions:
- Spray: `players_ratings.batting_pull` + park handedness → per-player Pull/Cent/Oppo boundary. Target: 40% → 70-80% match.
- xBA: piecewise EV-bucket scalers replacing flat ×1.22. Target: 89% → 95%+.

**UI rollout** *(~1 day)*

Cockpit drift pill, "last N days" toggles on player pages, real Tier-B sparklines on spotlight cards, `/settings/invariants` admin page.

**Exit criteria**: Padres recon at 98%+, "last 12 days Merrill" runs in <100ms, every monthly ingest emits a self-validation report, every screen has a time-windowed path.

### Phase 5 — The Baseball Almanac (~10-14 dev-days)

Save-agnostic complete-history layer. Pre-2026 = static reference (lref_* + Lahman + Retrosheet + Baseball Savant), 12/31/2025 boundary machine-enforced. 2026+ = pure OOTP sim. Era-agnostic views bridge.

Sequence:
1. HoF Lahman drop — `lref_master.lahmanID` swap (~2 hrs)
2. `lref_player_*` ingest (~1 day)
3. `lref_statcast_*` ingest (Baseball Savant 2015-2025, real-MPH scale labeled) (~1 day)
4. Unified player resolver `/api/players/{key}` (~1 day)
5. Era-agnostic views (`v_player_season_*`, `v_player_game_*`, `v_game_log`) (~1 day)
6. `lref_game_log` (Retrosheet GL files, every MLB game 1871+) (~1 day)
7. `f_game_log` from OOTP — already built in Phase 4b Tier A, JOIN only (~free)
8. First Almanac page `/history/year/[YYYY]` MVP (~1-2 days)
9. `lref_game_player_*` (Retrosheet events via Chadwick tools) (~2-3 days)
10. **Stretch comparator (Mantle vs Merrill flagship)** — built on Tier A (~2-3 days)
11. Streak engine / calendar heatmap / park-trip splits (~1 day each)

Cross-cutting: source-attribution tooltips + Statcast scale labels (real-MPH vs OOTP-sim ~5mph low).

### Phase 6 — Multi-save scaffolding (~3-5 dev-days)

Save-comparison views, cross-save player tracker, reconcile-as-CI across all saves with control data, archive/restore tooling, multi-save overlays on cockpit. Exit criteria: 5+ concurrent saves runnable through summer with no manual switching pain.

### Phase 7 — AI as analytical layer (~3-5 dev-days)

Trajectory tools (`get_player_trend`, `get_hot_cold`, `get_streak`), calendar/window-aware NL, Almanac comparator tool, trade recommendation engine, hot/cold narrative generation. Leverages Phase 4b Tier A + Tier B and Phase 5 era-agnostic views.

### Phase 8 — Polish + distribution (deferred decision)

Gated on "ready to share Diamond beyond solo use." Possible: code signing + MSI installer, auto-update, Mac/Linux ports, web-share path per D16. Scope decided post-summer.

### Dependency chain

```
Phase 4a ─→ Phase 4b ─┬─→ Phase 5  (Almanac needs game-grain facts + drift surface)
                      ├─→ Phase 6  (multi-save needs invariants per save)
                      └─→ Phase 7  (AI narratives need time-series + snapshots)

Phase 5 ─┬─→ Phase 7  (Almanac comparator needs era-agnostic views)
         └─→ Phase 6  (cross-save comparison meaningful only with rich data)

Phase 8 — independent, gated on "ready to share"
```

**Phase 4 is the bottleneck. Every later phase benefits from it.**

### Non-goals (NOT in Phase 4-7 scope)

- Re-ingesting any save from scratch (no L0 rewrites)
- Migrating off DuckDB (it's the right engine)
- Replacing the L0/L1/L2/L3/L_REF layer model
- Adding a database server / daemon
- Authentication or multi-user
- Cloud hosting / sync

### Cross-cutting commitments

- D15 dictionary stays the single source of truth for stat labels
- Reconcile harness runs on every code change (multi-save CI lands in Phase 6)
- Save-agnostic by construction throughout
- Theme system + IA stable through Phases 4-7

---

## Recent ships (chronological, most-recent-first)

**2026-05-17 (evening)** — **D39 Statcast reconciliation deep-dive (Padres 95%).** Four sub-fixes:
- **D39a (spray)**: `hit_xy` IS batter-relative (HR analysis across 1,889 MLB 2028 HRs confirms it). Boundaries calibrated: Pull<114, Cent 114-195, Oppo≥196. Pull% 5%→38%, Cent 18%→56%, Oppo 9%→40%.
- **D39b (game_type=0)**: L3 Statcast tables were aggregating spring training + playoffs. Filter applied to all three L3 builders + `_f_pa_event_xstats` view.
- **D39c (LA buckets)**: Recalibrated to GB<12 / LD 12-26 / FB 27-51 / PU≥52. LD% 31%→88%, GB% 60%→73%, FB% 4%→69%, IFFB 22%→72%, HR/FB 65%→79%, GB/FB ratio 3%→57%.
- **D39d (x-stats)**: Three sub-bugs — integer-EV interp zeroing 15-25% of BIPs; per-BIP avg instead of IE-style SUM/AB; empirical scalers (×1.22 xBA, ×1.09 xSLG). Batting xBA 0%→89%, xSLG 0%→89%, xwOBA 0%→78%; Pitching xBA 0%→96%, xSLG 0%→97%, xwOBA 0%→82%, xERA 0%→87%.

Total D38→D39 scorecard: 85% → **95%** match. Plus save-aware report header. Commit `88664c6`.

---

**2026-05-17 (morning)** — **D37 in-progress season league constants + multi-save endpoint resilience.** Day after D36 shipped, user opened the Padres save mid-2028 (`dump_2028_07`, mid-July) and reported the cockpit was showing a giant red "0" headline metric on every spotlight player + "No qualifiers yet" on the MLB Pressure board + History → Hall of Fame returned 500. Three distinct fixes:

| # | Issue | Where |
|---|---|---|
| 1 | **2028 league constants empty** — OOTP only writes `league_history_*_stats.csv` rows for completed seasons, so mid-season dumps have zero `(year, league, level)` rollup rows for the active year (only DSL leagues that complete by July had 2028 entries). Without league constants, `_lg_constants_advanced_native` emitted no row for (2028, MLB), so OPS+/wRC+/ERA+/FIP/wOBA all came back NULL across every in-progress player. New `agg_bat_fallback` + `agg_pit_fallback` CTEs in the view aggregate from `f_player_season_*` (already dump-deduplicated to latest dump) for combos NOT in `league_history_*`, gated to years that already have SOME `league_history` coverage so pre-save Lahman-imported rows stay routed to `_lg_constants_advanced_imported`. Post-fix: 25 rows for 2028 (was 2); Merrill 2028 OPS+ 124, Mason Miller ERA+ 252, full pressure board populated. | `src/diamond/schema/l3_advanced.py` |
| 2 | **Cockpit not graceful for NULL metrics** — `int(metric) if metric is not None else 0` server-side coerced NULL → 0, which the heat-scale lib rendered as red "low-band" + the insight generator wrote "Off year — 0 down from 135 peak." `headline_metric_value` is now `int \| None`; cockpit passes through None; frontend renders "—" with `text-content-muted`; insight is suppressed entirely when current metric is None. | `src/diamond/api/{routes/cockpit.py, schemas/cockpit.py}`, `web/app/page.tsx` |
| 3 | **`/api/hof` 500 when `history_lahman_people` missing** — Padres save was created without running `diamond fetch-history`, so the warehouse has zero `history_*` tables. The HoF endpoint LEFT JOIN-ed `history_lahman_people` for `bbref_id` resolution; missing table is a compile-time error, not a row-resolve error. New `_history_loaded(con)` probe + template-based query construction substitutes `NULL::VARCHAR AS bbref_id` and drops the JOIN entirely when the table's absent. Saves without backfill render the inductees list with no plaque images; saves with backfill (Sox) get the full plaque gallery. | `src/diamond/api/routes/hof.py` |
| ★ | **Bonus** — `/api/admin/dump-status` reported `ingested_count: 0` even though the warehouse had 29 ingests. Endpoint opened its own `duckdb.connect(read_only=True)` which fails on Windows with IOException because uvicorn's RW connection holds an exclusive lock. The `except duckdb.Error` fallback returned "everything pending" → permanent amber "29 new dumps" badge. Switched to `Depends(get_cursor)` shared-cursor pattern. | `src/diamond/api/routes/admin.py` |

**Verification**: 25 rows in `_lg_constants_advanced` for 2028 (was 2); Merrill 2028 OPS+ 124, Mason Miller 2028 ERA+ 252 (career-year insight reads "Career year — 252 vs prior peak 229"); HoF returns 200; dump-status returns ingested=29/pending=0; all 14 main API endpoints return 200 against the Padres warehouse.

**Note on the "short history" question**: The Padres cockpit shows "2005-2028 · Pre-save history + in-save" (vs the Sox save's 1871-2029). That's a property of how OOTP was configured when the Padres save was created (~"import last 20 years" instead of "full Lahman history"), NOT a Diamond bug. Pre-2026 Padres player rows still resolve advanced stats via the lref_era_stats-backed `_lg_constants_advanced_imported` view. To extend Padres history backward, the user would need to start a new save with full Lahman import.

---

**2026-05-16 (end-of-day)** — **D36 multi-save productionization** (Padres save smoke test). Drove a real second save (`The Fathers.lg`, San Diego Padres, audit_team_id=23, 29 dumps 2026_03 → 2028_07) end-to-end through Diamond and surfaced + fixed every place the system implicitly assumed Sox / Building the Green Monster. Five distinct issues, each shipped as its own commit on top of D35:

| # | Issue | Where | Commit |
|---|---|---|---|
| 1 | **Save-aware AI prompt** — opened with "the user is the GM of the Boston Red Sox (organization_id=4, MLB league_id=203) in the 'Building the Green Monster' save" + named all four Sox affiliates by hand. New `_resolve_org_context(cursor, save)` substitutes team city/name/org_id from `MLB_TEAMS_BY_ID` + warehouse-probes latest/earliest seasons. Org-structure block becomes generic. Both sync + stream chat handlers wire it in. | `src/diamond/api/routes/ai.py` | `95c13ce` |
| 2 | **Save-aware desktop chrome** — `launcher.py` and `single_instance.py` both hardcoded `WINDOW_TITLE = "Diamond — Building the Green Monster"` (and the latter used it for `FindWindowW` lookups, so single-instance focus was Sox-only). Splash HTML had a hardcoded Sox-save title. New `diamond.saves.get_active_window_title()` is the single source of truth; reads `~/.diamond/active_save.toml` directly so the desktop launcher (which boots before FastAPI) can use it. Splash gets a placeholder substituted at load time. | `src/diamond/saves.py`, `desktop/launcher.py`, `desktop/single_instance.py`, `desktop/splash.{py,html}` | `95c13ce` |
| 3 | **VARCHAR-defensive scope filters** — The Fathers' `l0_trade_history.{team_id_0, team_id_1, player_id_0_*, player_id_1_*, message_id, date}` + `l0_league_playoff_fixtures.{league_id, team_id0, team_id1}` all came in as VARCHAR (string-quoted ints + ISO dates) where Sox had BIGINT/DATE. Naive `team_id IN (BIGINT_LIST)` died with `Binder Error: Cannot compare VARCHAR and BIGINT`; `trade_date BETWEEN TIMESTAMP ...` died with the same shape. `_SCOPE_PLAYER` / `_SCOPE_TEAM` / `_SCOPE_LEAGUE_HARDCODED_15` / `_SCOPE_TRADE` now wrap LHS in `TRY_CAST(... AS BIGINT)`; `f_trade_participant` builder TRY_CASTs every team_id, player_id (in UNNEST), message_id, and `date` (→ DATE). NULL-on-failure semantics safely excludes any non-numeric ID rows. | `src/diamond/schema/l1_event.py`, `schema/l3.py` | `95c13ce` |
| 4 | **JS local-TZ date parsing** — `fmtDate("2028-07-01")` did `new Date("2028-07-01")` which JS interprets as UTC midnight, then `toLocaleDateString` shifts it back a day in any TZ west of UTC (your "Last sync" was showing Jun 30 instead of Jul 1). Three pages had the same pattern (cockpit / league standings / history streaks); all three now defensively parse date-only ISO strings via `new Date(y, m-1, d)`. | `web/app/{page,league/page,history/streaks/page}.tsx` | `101573e` |
| 5 | **dump_date end-of-month convention** — User pointed out `dump_2028_07` is exported when OOTP advances *into* August, so its data represents "stats through 7/31/2028", not 7/1/2028. `dump_name_to_date()` was returning 1st-of-month; now returns last-day-of-month via `calendar.monthrange` (handles leap years: 2024-02-29, 2028-02-29). New `migrate_dump_dates_to_eom()` runs DuckDB's `LAST_DAY()` over every `dump_date` column on every BASE TABLE (filters out views — DuckDB can't UPDATE views), idempotent via `_diamond_settings.dump_date_convention='end_of_month'` setting marker, with `WHERE dump_date <> LAST_DAY(dump_date)` optimization. New `diamond migrate-dump-dates [--save NAME]` CLI command runs it explicitly. **NOT auto-run on warehouse open** — a 10+ minute API stall on first connect would be unacceptable for the legacy Sox save (45+ dumps × 80+ snapshot tables × millions of rows). | `src/diamond/schema/build.py`, `cli.py` | `5b66839` |

**Padres ingest result**: 29 monthly dumps (2026_03 → 2028_07) → 288 MB warehouse with 208 tables (27 lref_*, 22 facts, 37 events). Padres MLB roster: 51 players, org pyramid: 245, scope: 13,222 players. Season range: 2005-2028 (24 years incl. pre-2026 historical baselines). 2027 top OPS+: Jackson Merrill 124 (3.9 bWAR), Ozuna 120, Salvy 112. 2027 top pWAR: Vasquez 2.7, Chapman 1.6 (163 ERA+). Active save flipped to `The Fathers.lg`; cockpit window now reads "Diamond — The Fathers" with full Padres-aware AI prompt.

**Migration status**:
- `The Fathers.lg`: ✓ MIGRATED (dump_2028_07 → 2028-07-31, setting marker stamped). Took ~30s.
- `Building the Green Monster.lg`: NOT migrated. Run `diamond migrate-dump-dates --save "Building the Green Monster.lg"` when ready (expect 10-15 minutes for the full row rewrite).

**Hardcoded Sox leftovers intentionally kept**:
- `BUILDING_THE_GREEN_MONSTER` singleton in `config.py` — fallback default for `_resolve_initial_save()` when `~/.diamond/active_save.toml` is missing (first-launch case).
- `audit/reconcile.py` — Sox-specific IE roster CSV reconciliation; the audit harness ran during Phase 1 and isn't user-facing.

---

**2026-05-16 (later) — D35 AI sidebar polish: Claude.ai-style rendering + SSE streaming.** Four-tier rebuild of the AI sidebar fixing the "table renders as raw `| Stat | ... |` text" gap visible in the post-D33 screenshots. The model was producing perfect GFM markdown the whole time; the sidebar was just `whitespace-pre-wrap`-dumping it. Plus new SSE streaming endpoint so the model writes character-by-character with an animated cursor.

**D35 four-tier delivery**:

| Tier | What | Where |
|---|---|---|
| **A — Markdown rendering** | Assistant text now renders via `react-markdown` + `remark-gfm` + `rehype-katex` + `remark-math`. Tables get borders + zebra stripes, headings get hierarchy, lists indent properly, inline + block code get monospace + subtle bg. Per-text-block card chrome dropped — assistant prose flat against panel bg. | `web/components/ai/MarkdownMessage.tsx` (new, ~140 LOC) |
| **B — Visual polish** | Consecutive assistant turns coalesce into one labeled response group (the tool loop produces 3-4 turns; the user perceives one answer, so we render one Diamond label). User messages: subtle right-aligned pill (`bg-surface-card`, max 85% width). Assistant: full-width flat with ✦ glyph + accent label. Hover-revealed copy button. Panel default width 440 → 520. | `AISidebar.tsx` rewrite (`Group` + `groupTurns`) |
| **C — SSE streaming** | New `POST /api/ai/chat/stream` returns `text/event-stream`. Provider-agnostic event vocabulary: `text_delta`, `tool_use`, `tool_result`, `iteration`, `error`, `done`. Both adapters implement native streaming (Anthropic SSE + OpenAI delta-chunk SSE); `AIClient.chat_stream` has a default fallback that re-emits `chat()` results. Frontend `streamChat()` parses SSE incrementally with abort support. UI shows a blinking ▍ cursor at the end of streaming text + a Stop button replacing Send. | `src/diamond/api/routes/ai.py` (`_stream_chat`); `src/diamond/ai/adapters/{anthropic,openai}.py` (`chat_stream`); `web/lib/ai-chat.ts` (`streamChat`) |
| **D — Chrome polish** | Mode pills moved into the header (no longer compete with input area). Drag-to-resize via 2px handle on left edge of panel; width persists to localStorage (380-900px range). "Jump to latest" button appears when scrolled away from bottom mid-stream. | `AISidebar.tsx` header + drag handlers + scroll observer |

**Provider-agnostic streaming protocol** (Anthropic + OpenAI both speak this):

```
event: iteration\ndata: {"n": 1}\n\n
event: text_delta\ndata: {"text": "Looking up "}\n\n
event: text_delta\ndata: {"text": "Garrett Crochet..."}\n\n
event: tool_use\ndata: {"id": "tu_01", "name": "get_career_arc", "input": {...}}\n\n
event: tool_result\ndata: {"tool_use_id": "tu_01", "content": {...}, "is_error": false}\n\n
event: iteration\ndata: {"n": 2}\n\n
event: text_delta\ndata: {"text": "At age 30..."}\n\n
event: done\ndata: {"stop_reason": "end_turn", "iterations": 2}\n\n
```

Frontend mutates a `StreamingState` in place per event (text_delta → append to last text block; tool_use → push to current assistant turn; tool_result → push user turn with tool_result). On done, streaming state drains into the committed thread.

**Files touched**: 5 source + 1 new component (`MarkdownMessage.tsx`). pnpm deps added: `react-markdown@^10`, `remark-gfm@^4`, `rehype-katex@^7`, `remark-math@^6`.

**Compat**: existing `POST /api/ai/chat` (synchronous) endpoint stays; the new streaming endpoint is additive. Both share the same tool loop + system prompt + 6-iteration cap.

**Sync endpoint not deprecated** — kept for tests, non-streaming integrations, and as a fallback if the streaming code path ever needs to be bypassed. Frontend uses streaming exclusively.

---

**2026-05-16 (earlier) — Phase 3: D34 cleanup pass.** Three small commits on top of yesterday's D32 desktop shell + D33 AI sidebar work, removing pre-D32 vestigial code and tightening the surface. Plus six same-day D33 follow-ups landed: model auto-migration, DuckDB timeout fix, describe_table tool, persona setting + tool-plumbing hide, page-payload wiring, get_career_arc tool with cite-your-sources prompt.

**D34 cleanup (today)**:

| # | What | Files / LOC |
|---|---|---|
| 1 | **Launcher consolidation** — delete `api.bat` + `web.bat` + `kill-stale.bat`; inline kill loop into `dev.bat`; export PYTHONIOENCODING in Makefile; `dev.bat` calls `make api` / `make web` directly. Launcher count 5 → 2 (`Diamond.vbs` + `dev.bat`). | -3 files, -~85 LOC |
| 2 | **Remove header Quit button** — pre-D32 vestige. Window X + tray Quit cover it. Removed `QuitButton.tsx`, `shutdownApp()` helper, `<QuitButton />` from layout, `POST /api/admin/shutdown` route, and the 100-line `_KILL_SCRIPT` constant + its 5 imports. | -1 file, -~240 LOC |
| 3 | **Tray "Show Diamond" focuses native window** — was opening cockpit in default browser; now uses Qt signal to un-minimize/raise/activate the existing window. Tray gains optional `on_show` parameter; launcher wires it via `showRequested` signal. | +50 LOC, -8 LOC |

**D33 same-day follow-ups (also today)**:

- **Anthropic snapshot auto-migration** — `claude-3-5-haiku-20241022` retired upstream; `RETIRED_MODELS` map rewrites stale model strings to `claude-haiku-4-5` on load; default flipped to rolling alias. (`061e2f6`)
- **DuckDB timeout removed** — `SET statement_timeout` is Postgres syntax; DuckDB 1.5.x rejects it. Was hitting every tool call. Dropped; LIMIT 1000 + read-only + single-statement is the bound. (`03943aa`)
- **LIMIT injection skips non-SELECT + new `describe_table` tool** — `DESCRIBE players_current LIMIT 1000` was a syntax error; now LIMIT only applies to SELECT/WITH. New tool gives the model a clean schema-discovery path with strict alphanumeric validation. (`3de5bbd`)
- **Persona + tool-plumbing hide** — new `persona` setting (free-form, appended to chat system prompt); 5 presets in `/settings/ai`. Tool_use/tool_result blocks hidden by default in the sidebar; "Tools" toggle in header for debug; Metabase cards + errors stay visible. (`fe74739`)
- **Page-payload wiring** — `<PagePayloadProvider>` Context + `<PagePayloadBridge>` server-component bridge with 16KB cap. Cockpit + player page publish their data; AISidebar reads via `usePagePayload()` and includes in `page_context.payload`. Model now sees what the user sees. (`2381f0b`)
- **`get_career_arc` tool + cite-your-sources prompt** — fixes the Crochet-vs-Ryan hallucination class (model claimed Ryan career pWAR 1,650.6 vs actual 117.9; got year-to-age mapping wrong). Tool returns deterministic age-per-year + warehouse-aggregated career WAR. System prompt: "cite tool sources for every specific number; never from training-data memory." (`5711f98`)

**API surface today** (34 endpoints — D34 removed `/api/admin/shutdown`; D35 added `/api/ai/chat/stream`).

**Tool count**: 8 (query_warehouse, describe_table, get_career_arc, get_player, compare_players, get_glossary, list_leaderboard_stats, create_metabase_card).

**Run modes** (D34 final):

| Command | Use |
|---|---|
| `Diamond.vbs` | Production / single-window experience |
| `dev.bat` | Engineering hot-reload (two cmd windows + browser tab) |
| `python -m diamond.desktop --dev` | Native window over running dev servers (best of both) |
| `make api` / `make web` | Single-server start in current terminal |
| `make desktop` / `make desktop-package` | Desktop validation / full PyInstaller bundle |

---

**2026-05-16 (earlier) — Phase 3: AI sidebar shipped (D33) + Metabase link fix.** Diamond's AI is no longer a single "Summarize career" button — it's a full sidebar reachable from every page with tool use, page context, GM-copilot modes, and Metabase card creation. Plus a fix for QtWebEngine target=_blank links (Metabase Workshop deep-links now route to the system browser).

**D33 four-tier shape**:

| Tier | Capability | Implementation |
|---|---|---|
| **T1: Page-aware** | Sidebar reads `usePathname()`; system prompt includes "user is on /player/123" | `web/components/AISidebar.tsx` + `_build_system_prompt` |
| **T2: Tool-using analyst** | 6 tools wired into warehouse + dictionary | `src/diamond/ai/tools.py`; route's tool loop |
| **T3: GM copilot** | 4 modes (chat / callup / trade / draft) prepend structured prompts | `_MODE_PROMPTS` + frontend mode pills |
| **T4: Prompt-to-dashboard** | `create_metabase_card` POSTs MBQL spec to Metabase REST API | `tools.py:_create_metabase_card` |

**Tools** (all read-only, return `{"ok": False, "error": ...}` on failure rather than raising):

- `query_warehouse(sql)` — DuckDB cursor with single-statement guard, regex-blocked mutations, default LIMIT 1000, 5s timeout
- `get_player(player_id)` — bio + career bWAR/pWAR
- `compare_players(player_ids)` — 2-5 players side-by-side
- `get_glossary(stat_id)` — definition + formula + interpretation from `diamond.dictionary.STATS`
- `list_leaderboard_stats()` — discovery
- `create_metabase_card(name, sql, viz_type)` — POSTs to Metabase, returns card_url

**Frontend rendering** of the conversation thread is rich:
- Plain text in standard chat bubbles
- `tool_use` blocks render as collapsible `<details>` with the model's input args + a "Tier 4" badge for `create_metabase_card`
- `tool_result` blocks special-case warehouse query results (preview table, first 25 rows, SQL inline) and Metabase card creations (green ✓ link to open in browser)
- Errors render in rose styling

**Empty-state suggestions** are page-aware: on `/player/[id]` you get "Summarize this player's career…", on `/league` you get "Who should I call up from AAA?" (mode=callup), on `/movements` you get a trade analysis prompt, etc.

**Metabase link fix**: QtWebEngine doesn't handle `target="_blank"` by default — the Workshop tab's "New question / Sample dashboard / Browse warehouse" cards opened nothing. Subclassed `QWebEnginePage` to override `createWindow`; new-window navigation now routes to the system default browser via `QDesktopServices.openUrl`.

**Files**:

```
src/diamond/ai/
  client.py                AIClient gains chat() abstract method
  tools.py                 new — 6 tools + Tool dataclass + ToolContext
  adapters/anthropic.py    adds chat() — pass-through (Anthropic-native shape)
  adapters/openai.py       adds chat() — translates messages + tool_calls

src/diamond/api/
  schemas/chat.py          new — ChatTurn / ChatContentBlock / ChatRequest / ChatResponse / PageContext
  routes/ai.py             adds /api/ai/chat endpoint + system-prompt builder + tool loop

src/diamond/desktop/
  launcher.py              ExternalLinkPage subclass routes target=_blank to system browser

web/
  lib/ai-chat.ts           new — sendChat() helper
  components/AISidebar.tsx new — full sidebar (~470 LOC)
  app/layout.tsx           wires <AISidebar /> into root layout
```

**API surface today** (34 endpoints — D33 added `/api/ai/chat`).

**Caveats**:
- **No streaming v1** — synchronous request/response; sidebar shows "Thinking…" until the full loop finishes. SSE streaming is a v2 follow-up.
- **Iteration cap = 6** — prevents tool spirals; if hit, the model gets a graceful "I've used max tool calls" close.
- **No conversation persistence** — threads live in component state; "New" resets. Per-save thread persistence is a v2 follow-up.
- **`create_metabase_card` requires Metabase running** — checks port 3001; surfaces a friendly error inline if not. D32's auto-launch makes this rare in practice.

---

**2026-05-15 (late evening) — Phase 3: Native desktop shell shipped (D32).** Diamond now ships as a native Windows app — one `Diamond.exe`, no browser tab, no flapping cmd windows, clean shutdown via Windows Job Object. Single-window-morph pattern (Qt signal swaps splash HTML for main URL); PySide6 + QtWebEngine for the chrome (bundled Chromium — no end-user WebView2 install needed); PyInstaller for the bundle. Five-slice ship in a single session, plus same-day pivot from pywebview → PySide6 (pywebview's hard `pythonnet` dep on Windows has no Python 3.14 wheel).

| Slice | Headline | Files |
|---|---|---|
| **1. Launcher MVP** | `src/diamond/desktop/launcher.py` orchestrates lifecycle. uvicorn runs in a daemon thread (in-process, no `python.exe` subprocess needed inside the frozen bundle). Next.js standalone runs as a hidden `node server.js` child via `CREATE_NO_WINDOW`. Both bind 127.0.0.1; ports auto-fallback to OS-assigned if 8000/3000 are busy. | `desktop/{launcher,sidecar,paths}.py`, `desktop/__main__.py`, pyproject `[desktop]` extra |
| **2. Standalone build** | Flipped `web/next.config.mjs` to `output: 'standalone'`. New `scripts/build_desktop.py` runs `next build` + copies `.next/static` and `public/` into the standalone tree (Next omits these by default). `make desktop` chains build + run. | `web/next.config.mjs`, `scripts/build_desktop.py`, `Makefile` |
| **3. Lifecycle hardening** | Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) — every spawned child PID is assigned to it; hard-killed launcher takes its kids down too. **Eliminates stale-process failure mode entirely.** Single-instance lock via `CreateMutexW` + `Local\\Diamond.OOTP.Desktop.SingleInstance`; second double-click sees `ERROR_ALREADY_EXISTS`, calls `FindWindowW` + `SetForegroundWindow` on the running window. | `desktop/{win_jobobject,single_instance}.py` |
| **4. PyInstaller bundle** | `src/diamond/desktop/diamond.spec` is a one-folder spec (not `--onefile` — the standalone tree's thousands of small files would add 2-3s per-launch unpack to TEMP). Datas: web standalone tree → `web_standalone/`, asset folder → `desktop_assets/`. Hidden imports cover all 23 API route modules + uvicorn dynamic imports + PySide6 widgets/QtWebEngine + pystray + PIL. `make desktop-package` builds → `dist/Diamond/Diamond.exe`. | `desktop/diamond.spec`, `scripts/build_desktop.py --package` |
| **5. Polish** | **Splash → main morph** (single window — one `QApplication` + `QMainWindow` + `QWebEngineView`; boot thread emits a Qt signal carrying the URL, slot runs on the GUI thread and calls `view.load(QUrl(...))` — Qt auto-marshals via the meta-object system). Splash HTML in `assets/splash.html` matches D18 dark theme. **No WebView2 runtime dependency** — QtWebEngine ships its own Chromium, so end-users on Win10 don't need to install anything separately. **Tray icon** via pystray in a daemon thread (Show / Open Metabase Workshop / API docs / Quit). Tray and splash both fail-soft. | `desktop/{splash,tray}.py`, `desktop/assets/splash.html` |

**What changes for the user**:

- Double-click `Diamond.exe` → splash window in ~200ms → main window in ~3-5s. **No browser. No terminals.**
- Close the window → process tree empty. No leftover uvicorn / node / DuckDB locks.
- Tray icon (Win11 notification area) → Show / Open Metabase / Quit.
- Second double-click while running → focuses the existing window (no duplicate copy).
- Hard-kill via Task Manager → Job Object kills the children too. **`kill-stale.bat` is deprecated** for the desktop path.

**What stays unchanged**:

- `dev.bat` and the two-terminal hot-reload workflow — kept for engineering. Desktop shell is the production user surface, not a replacement for the dev path.
- Metabase Workshop launcher (D31) still opens in default browser (acceptable: Metabase is the explicit BI escape hatch, and rendering it inside another QtWebEngine instance buys nothing).
- All API routes, schemas, theme system, dictionary, warehouse — zero touch.

**Run modes**:

| Command | Use |
|---|---|
| `dev.bat` | Engineering — two cmd windows + browser tab, hot-reload |
| `python -m diamond.desktop --dev` | Iterating on launcher / tray / splash code (assumes dev.bat is up) |
| `make desktop` | Validate production path locally — runs `next build` + opens native window |
| `make desktop-package` | Full bundle → `dist/Diamond/Diamond.exe` |

**Documented**: `docs/DESKTOP.md` (architecture / build pipeline / troubleshooting / when-not-to-use); `docs/DECISIONS.md` D32 (full architectural reasoning vs Tauri / Electron / static-export).

**Caveats / known follow-ups**:
- Code signing (Windows SmartScreen friendliness) deferred — `Diamond.exe` will trip SmartScreen on first run; user clicks "More info" → "Run anyway". Acceptable for single-user local. Tracked in BACKLOG.md.
- Inno Setup MSI installer for Start Menu integration + uninstall deferred — manual `dist/Diamond/Diamond.exe` for now.
- Auto-update deferred — relaunch Diamond after a `git pull` + `make desktop-package`.
- Mac/Linux deferred — PySide6 supports both but Diamond's saves path is hardcoded to Windows; cross-platform is a separate scope.
- Node still required on PATH — bundling Node would add ~50MB; deferred to a future "no external deps" slice.

---

**2026-05-15 (evening) — Phase 3: Metabase integration shipped (D31).** Diamond now has a self-hosted, save-aware Metabase as its full-BI workshop — Pattern A (single Database connection follows the active save). Five commits this evening: spike → integration → port-flip (3000→3001) → SSR cleanup → iframe-to-launcher pivot.

| Phase | Headline | Commit |
|---|---|---|
| **Spike** | Java 21 + Metabase 0.59.10 + DuckDB driver 1.5.2.0 installed at `~/.diamond/metabase/`. 5 cards + 1 dashboard built via REST API in 8 min — proved the AI-assisted dashboard workflow works (write MBQL/native-SQL spec, POST to `/api/card`, dashboard renders). Verified 296 BTGM 2029 qualified hitters resolve through Metabase. | (spike, no commit) |
| **Integration** | `src/diamond/api/metabase.py` coordination module (auth + cached session at `~/.diamond/metabase_session.txt` + `repoint_active_save()`). `POST /api/saves/active` extended with Pattern A hook: PUT new database_file + sync_schema. Best-effort + silent-on-failure (Metabase down / no creds → save switch still succeeds). | `8451168` |
| **Port flip** | Metabase moved from `:3000` (collides with Next.js) to `:3001` everywhere — `metabase.bat`, `metabase.py`, `MetabaseWorkshop.tsx` (with `NEXT_PUBLIC_METABASE_URL` override). | `0f3d4ff` |
| **SSR fix** | `/explore` page hoisted data-fetching to single top-level async server component (avoids inline-async-child quirk in Next App Router that surfaced as "server-side exception"). Workshop mode no longer fetches chart_builder API on entry. | `68ae5ce` |
| **Launcher pivot** | Hit Metabase OSS's `X-Frame-Options: DENY` — interactive embedding is paid Pro only. Pivoted Workshop tab from iframe to launcher (same shape as Tableau Desktop / Power BI Desktop sidecars). Click → opens Metabase full-screen in a new tab. Three deep-link cards (New question / Sample dashboard / Browse warehouse). New `GET /api/admin/metabase-status` for same-origin liveness probe. | `2b3f03f` |

**Final shape**:

- **Install**: `~/.diamond/metabase/` holds metabase.jar (520 MB), DuckDB driver plugin (84 MB), H2 metadata (cards + dashboards + accounts), logs, `metabase.bat` launcher (localhost-only, telemetry off, update-check off, port 3001, 2 GB heap)
- **Credentials**: `~/.diamond/metabase_credentials.toml` for the save-switch hook (gitignored by virtue of being outside repo)
- **Pattern A**: every save switch in Diamond UI auto-flips Metabase's Database 1 to the new save's DuckDB + triggers schema re-sync. Cards keep working because Diamond's schema is identical across saves; only data changes.
- **Workshop tab** at `/explore?mode=workshop` shows a launcher card + three deep-link cards. Click any → Metabase opens full-screen in a new tab.
- **Status endpoint** `/api/admin/metabase-status` returns `{running, configured, active_save_db, message}` for the frontend liveness probe.

**Why launcher, not iframe**: Metabase OSS's `frame-ancestors 'none'` blocks cross-origin iframing. Allowing it requires interactive-embedding (Pro feature, paid). Launcher pattern is functionally equivalent — same warehouse, same Pattern A, same AI-assisted dashboard workflow. Just two browser tabs instead of one. Mirrors how every BI sidecar (Tableau Desktop, Power BI Desktop) integrates with web apps.

**Documented**: `docs/METABASE.md` (install / ops / Pattern A / threat model / troubleshooting / AI workflow). `docs/DECISIONS.md` D31 (full architectural reasoning vs Power BI / SQL Server / custom Vega-Lite).

**Net outcome of evening**: Diamond now has a real chart-building / BI surface that's modern (drag-and-drop, 30+ chart types, dashboards, calculated fields, drill-through), embedded in the IA (Workshop tab in /explore), local-first (no cloud), free (OSS), and AI-assistable (Claude can build cards/dashboards via REST API).

**Caveats / known follow-ups**:
- Dashboards live only in Metabase's H2 metadata DB right now. Reset Metabase = lose them. v2: `diamond metabase deploy` CLI reads YAML specs from `diamond/metabase/dashboards/*.yaml` + POSTs to API. Source-controlled, reproducible. ~1.5 days.
- No pre-built starter dashboards beyond the spike's 5 cards / 1 dashboard. v2 plan: ship a battery of leaderboards / distributions / career arcs / team summary / pressure cohort / rookie tracker as YAML.
- Don't run `diamond ingest` while Metabase is reading the DB (lock collision). Documented in METABASE.md.

---

**2026-05-15 (afternoon) — Phase 3: capability wave shipped (Slices A/B/C/D, D30).** Four slices in one session moving the platform from "trustworthy + data-complete" (post-L_REF) to **visibly more capable** (leverage stack, real assets, OOTP-canonical geometry). Five commits across 25 files; +1,400 LOC; typecheck clean.

| # | Slice | Headline | Commit |
|---|---|---|---|
| **A** | **Leverage stack — WPA / LI / RE24 / Clutch** | New `f_player_season_leverage_batting` (32,767 rows) + `_pitching` (32,338). WPA from L0 (current-year only), LI from L0 (per-PA Tango = SUM(li)/SUM(bf), empirically decoded), **RE24 multi-year** from `lref_re288_table` joined to `f_pa_event` via window-function after-state. Clutch = WPA / LI per Tango. Wired into player page Advanced columns + leaderboards catalog (6 new stats) + 4 glossary entries. Eldridge 2029: WPA +5.81 / RE24 +49.4 (top in MLB). Crochet RE24-against trajectory 21.8 → 28.8 → 17.3 → 8.3 across 2026-2029. Yesavage 2029 Clutch +3.61 (Cy-tier). | `dec326d` |
| **B** | **Real OOTP team logos** across 5 surfaces | `GET /api/photos/teams/{team_id}.png?size=N` streams from `<save>/news/html/images/team_logos/` with size-snapping (16/25/40/50/110/full) + same revalidation pattern as player headshots. New `<TeamLogo>` component with abbr-pill fallback. Wired into cockpit standings strip + spotlight cards, league standings rows, movements ledger (logos flank the from→to arrow), leaderboards team column, and player page bio header. CockpitSpotlightCard schema gains team_id. | `fe41688` |
| **C** | **Spray chart sources OOTP-canonical 7-seg geometry** | `StadiumSprayChart` accepts a `parksApi` prop carrying `/api/parks` (240 parks from `lref_pt_ballparks`). Adapter (`stadiumFromApi`) converts 7-segment OOTP geometry to the renderer's 5-point spline (LL→lf_line, LCF→lcf, CF→cf, RCF→rcf, RL→rf_line) + matching wall heights. Hand-coded `web/lib/stadiums.ts` remains as fallback for missing parks + cosmetic feature flair (Green Monster / ivy / splash hits). Verified: Fenway API returns LL=310 / LCF=379 / CF=390 / RCF=383 / RL=302 + walls 37/9/3 — corrects the dead-CF wall (9 OOTP-canonical vs 17 hand-coded — 17 was the LCF triangle, not dead-CF). | `1cd365b` |
| **D** | **Real HoF plaques on /history/hof** | Three pieces: (1) `GET /api/photos/hof/{bbref_id}.png` streams from install `hof/` folder; (2) `GET /api/photos/hof` manifest endpoint enumerates the 8 plaques actually present on disk (Bagwell, Carter, Ford, Gibson, Griffey Jr, Kaline, Sandberg, Ozzie Smith); (3) `HofPlayer.bbref_id` resolved via name + birth-year-disambiguated JOIN against `history_lahman_people` — populates for hundreds of real-life HoFers (Cabrera, Pujols, Cano, etc.) even though only 8 PNGs ship. Frontend gets a horizontal-scroll plaque gallery above the inductees table; thumbnails deep-link to `/player/{id}` when resolvable, else open the PNG in a new tab. Lazy-loaded (each plaque is 5-8 MB at full res). | `d5bbfaf` |

**Net outcome (D30 captures the rationale)**: pre-D30 the platform was "trustworthy" (data-complete, OOTP-canonical baselines from L_REF) but not visibly more capable than yesterday. This wave changes that — leverage stack is a brand-new analytical surface (clutch / context-aware metrics that OOTP supplies but we never exposed); team logos transform the visual density across every page that mentions a team; spray chart geometry is now exact-by-construction match to OOTP's in-game UI; HoF page gets a marquee gallery. Roughly: data trust ✓ (post-L_REF) → product capability + polish ✓ (post-D30).

**Next** — return to either (a) deeper analytical work: full WPA leveraging `lref_wpa_table` per-PA (currently L0-aggregated only, current-year-only), batter LI from `lref_li_table` (decode the 5-column variable-width score-diff format), xISO via OOTP's 6-zone LSA classifier; or (b) more visible polish: real team logos in roster headers, save switcher, more cockpit slots; or (c) net-new features from BACKLOG.md.

---

**2026-05-14 (end of day) — Phase 3: L_REF Slices 1 + 2 + 3 + 4 + 5 + 6 (data layer) shipped in one marathon session.** Today drained the analytical L_REF backlog and added the parks API:

1. **Slice 1** — L_REF ingest layer with per-save freeze (D27). 27 reference tables / 575,587 rows snapshot into per-save DuckDB on first `diamond ingest`; SHA1 + mtime provenance in `_diamond_settings.lref.{frozen_at,source_root,ootp_version,table_count,files_json}`; `--refresh-lref` opt-in path with diff preview.
2. **Slice 2** — Calculation-parity swap. `f_player_season_xstats_batting` (20,787) + `_pitching` (21,504) materialize OOTP-canonical xwOBA/xBA/xSLG per BIP via 1D linear interpolation of `lref_xwoba_table` / `lref_xba_table` / `lref_xslg_table`. Player page shows `wOBA | xwOBA` side-by-side; leaderboards catalog gains 3 new stats; 3 KaTeX glossary entries.
3. **Slice 5** — MiLB pre-save baselines via `lref_era_stats_minors`. Closes the deferred backlog item: pre-2026 minor-league player-seasons went from `—` everywhere to **84,000 newly-resolved player-seasons** (88k MLB-only → 172k MLB+MiLB with non-null wOBA). Real historical AAA legends now resolve: Joe Lis 1972 IL wRC+ 289, McCovey 1959 PCL 284, Trout 2012 PCL 190.
4. **Slice 4** — Replaced Lahman+BREF UNION with `lref_era_stats` (1870-2025 MLB league averages, 156 rows × 82 cols). Single OOTP-canonical source; drops the 2019/2020 boundary; values stay essentially identical (Bonds 2001 OPS+ 267, Pujols 2003 193, Trout 2018 201). Soft-skip predicate flipped from `history_loaded` → `lref_era_loaded`.
5. **Slice 3** — Era-aware park factors with LH/RH splits via `lref_era_ballparks` (3,105 rows 1871-2025). Replaces `history_lahman_teams` BPF/PPF source. Adds `bat_park_avg_lh/rh`, `pit_park_avg_lh/rh` to `_park_factor_resolved`. Builder applies handedness: bats=L → LH PF, bats=R → RH PF, bats=S → 60/40 blend (Tango). Pre-2026 handed hitters in handed-PF parks shift toward BBR: Bonds 2001 OPS+ 267→262 (BBR 259); Walker 1999 215→191; modern save (2026-2029) invariant.
6. **Slice 6 (data layer only)** — `/api/parks` returns all 240 modern ballparks from `lref_pt_ballparks` with 7-segment outfield geometry + LH/RH split factors per stat. Frontend refactor (delete `web/lib/stadiums.ts`, swap `StadiumSprayChart` to fetch + 7-segment renderer) deferred to Slice 6 v2 — touches the renderer's geometry model deeply.

**Skipped slices with rationale**:
- **Slice 7** (Master crosswalk drops Chadwick) — `lref_master` carries `playerid` ↔ `lahmanID` ↔ `retroID` ↔ `BBrefMiLBid` but **no `mlb_id` and no `BBrefMLBid`**. The current Chadwick consumers (HoF MLB-API integration, awards leaderboard) all go from `mlb_id` → `bbref_id`, which lref_master can't satisfy. Master.csv complements but doesn't replace Chadwick.
- **Slice 8** (real team logos) — deferred. Requires manual team_abbr → `.oi` filename catalog plus FastAPI image-serving route plus frontend `<TeamLogo>` component to replace `font-mono BOS` chips across 5+ pages. Real cosmetic work, ~45 min, not data-quality.
- **Slice 9** (real HoF plaques) — deferred. Requires lref_master `hofID` → bbref crosswalk + plaque-PNG endpoint + `/history/hof` UI rewiring. Cosmetic.
- **Slice 10** (schema doc fold + brand colors) — partially **blocked**. `colors/*.xml` files turn out to be uniform-asset metadata pointing to `.oi` PNG files for caps/jerseys/pants — they do NOT contain hex color palettes as D26 implied. No brand-colors source available. Schema doc fold (db_structure_ootp27_csv.txt content into DATA_NOTES) is straightforward but low-leverage.

The bulk of L_REF's analytical value is now shipped. **Pre-save advanced stats are now end-to-end OOTP-canonical**: league baselines (era_stats), MiLB baselines (era_stats_minors), park factors (era_ballparks with handedness splits), per-PA xwOBA/xBA/xSLG (xwoba_table grids), all frozen with the save per D27.

**2026-05-14 (morning, earlier today) — Phase 3: L_REF Slice 1 shipped.**

**2026-05-14 (morning) — Phase 3: L_REF Slice 1 shipped.** New `src/diamond/schema/l_ref.py` ingest module reads from the OOTP install folder into 27 per-save `lref_*` tables (575,587 rows total) with first-ingest freeze + SHA1 provenance per **D27**. Three tiers loaded: `misc/` analytical lookup tables (xwoba/xba/xslg @ 106 LA-rows, xiso 6-zone, re288 24-row, li 432-row, wpa 480-row, pi 3-row), `database/` baselines + park factors (pt_ballparks 240, era_ballparks 3,105, era_stats 156 years 1870-2025, era_stats_minors 2,335, era_modifiers/fielding/total_modifiers 153-155, financials 156, weather 513, default_players 12,854), `stats/` crosswalks (master 24,746, milb_master 212k, teams_history 3,142, milb_leagues 2,317, milb_teams 23,075, eos/od_rosters ~100k each, uni_numbers 86k, series_post 411). Wire-in: `ensure_lref()` runs from `rebuild_l1_l2()` on every CLI invocation; idempotent skip when `_diamond_settings.lref.frozen_at` is set; opt-in refresh via `diamond ingest --refresh-lref` (implies rebuild — downstream calcs may JOIN to lref_*). Verified: first ingest → 27 tables loaded; second invocation → "already frozen at ..." silent skip; `compute_lref_diff()` returns 0 changes; spot queries pass (Fenway 7-segment dimensions, Bonds Master crosswalk `bondsba01`, Coors 1995 BPF 1.106 / HR 1.344). Reference doesn't drift mid-save. **Slice 2 (calculation-parity swap) is the natural next-up** — wire `lref_xiso_table` into barrel%/SS%/HH% computation, add bilinear-interpolated `xwoba_pa` to `f_pa_event`, optionally RE24/WPA/LI from the remaining lookup tables.

**2026-05-13 (evening, in-game year 2029→2030) — Phase 3: marathon day + LSEG density refactor + L_REF architectural finding.** Earlier-day shipped:

1. **Five major UI slices in the morning** (Custom leaderboards / Spray + EV-LA charts / Historical park factors D22 / AI overlay D14 / Setup wizard D3 v2)
2. **IA shuffle**: `/explore` is now the Chart Builder workshop only; per-player charts moved inline to player page; league-wide tools moved to `/league/*`. Permanent 308 redirects keep old URLs working.
3. **Setup wizard v2.1**: per-save scope (audit_team_id + league_ids + reference_scope) persisted to `~/.diamond/save_configs.toml`; division-grouped 30-team picker UI; `diamond ingest --save NAME` flag; legacy-default bootstrap migration.
4. **Auto-ingest at launch**: `dev.bat` chains `diamond ingest --all` before uvicorn binds. Plus an in-app `↻ Refresh` button (`RefreshButton.tsx`) — polls `GET /api/admin/dump-status` every 60s, badge when pending dumps detected, click triggers synchronous `POST /api/admin/ingest`. Plus `diamond status` CLI for terminal introspection.
5. **Photo cache (D24)**: ETag + Last-Modified revalidation with `Cache-Control: no-cache`. Newly-rendered face PNGs appear instantly when OOTP regenerates instead of after 24h browser cache. Verified: 2,038 → 18,564 player photos after user ran "FORCE UPDATE / GENERATE ALL PLAYER PICTURES" — 100% coverage on every active player including all newgens.
6. **LSEG-Workspace density refactor (D25)**: full-width layout (drops `max-w-6xl`); compact sticky header with backdrop-blur; `useElementWidth` hook drives responsive Plot charts (EvLaScatter + ChartBuilder fill containers, StadiumSprayChart caps at 720px); page-headers across 9 main pages collapsed from `text-3xl space-y-8` → LSEG-uniform `[CATEGORY] [Title · context]` pattern with `space-y-4`.

**Earlier today (2026-05-13 morning)**: Pre-2020 OPS+/ERA+ now use Lahman BPF/PPF via a 30-row OOTP↔Lahman franchID crosswalk (Bonds 2001 OPS+ 257→267 vs BBR 259, Pujols 2003 189→193 vs BBR 189, Trout 2018 198→201 vs BBR 198, Coors 1995 BPF 1.29). Custom leaderboards / Spray + EV-LA / Chart Builder / AI overlay / Setup wizard all live.

**Major architectural findings (D26 + D27 + D28, end-of-evening)**: two meticulous deep-dives ran in tandem 2026-05-13 evening — one on the OOTP **install** folder, one on the **save** folder. Combined surface area:

**Install folder** (`<docs>/Out of the Park Developments/OOTP Baseball 27/`, ~500MB of static reference data we'd been ignoring) — uncovered three tiers: (1) **calculation-parity tables in `misc/`** — OOTP's canonical xwOBA / xBA / xSLG / RE288 / WPA / LI / xiso lookup tables that the engine uses at sim time (reading these directly = guaranteed in-game-UI parity, replaces ~200 LOC of formula code); (2) **source-replacement tier** — `database/era_stats.txt` (82-col league avgs replacing D20 Lahman+BREF UNION), `era_stats_minors.txt` (2,335 rows unblocking the deferred MiLB pre-2026 baselines), `era_ballparks.txt` with LH/RH splits, `era_modifiers.txt` + `era_fielding.txt` + `total_modifiers.txt`, `stats/Master.csv` (24,747-row OOTP↔Lahman crosswalk replacing Chadwick); (3) **engine + cosmetic** — `major_league_baseball.json` (authoritative league rules), `financials.txt` (salary engine), `db_structure_ootp27_csv.txt` (version-current schema doc replacing the ootp21 fallback we'd been using), `hof/` real plaque PNGs, `colors/*.xml` brand palettes, 1,829 logos in `logos/` (`.oi` files are PNGs). **D26 commits to an `L_REF` reference layer** sitting alongside L0-L3. **D27 pins L_REF as per-save, frozen at first ingest, opt-in refresh** — mirrors OOTP's engine convention of capturing reference data at save creation and ignoring subsequent install-folder edits.

**Save folder** (`<save>/<save_name>.lg/`) — surfaced four classes of content not currently used: (a) **stable archives**: `temp/text_data.sqlite3` (188MB SQLite, 4 years retained, contains `league_news` 16,718 / `team_news` 43,206 / `league_transactions` 149,769 / `team_transactions` 350,169 / `player_history` 314,678 / `league_injuries` 63,065 / draft logs / etc.); (b) **ephemeral** (verified empirically — game_id resets each season): `news/html/box_scores/*.html` (18,982 files all dated 2029, single-batch mtimes), `replays/*.rpl` (6,481 files, same recycling); (c) **OOTP-internal binary**: `players.dat` (158MB) / `retired.dat` (157MB) / `faces.dat` (651MB) / etc. — redundant with dump CSVs we already ingest; (d) **operational config**: `settings/db_monthly_dump_csv.cfg` controls what tables OOTP exports per dump cycle (toggles `73-75 ratings modes`, `79-80 messages`, `81 game_logs` are OFF by default; user-tunable via OOTP's "Database Export" UI). **D28 pins**: dumps remain primary; ephemeral box-score-HTML and replay sources are deliberately ignored (the structured data they display is already in our dumps via D19's multi-year `f_pa_event`); `messages/` folder dropped per user preference; SQLite-backed `L_NEWS` layer is **deferred** until UX need pulls it in (would augment movements with OOTP's authoritative `transaction_type`, add player career bio timeline as new capability, add cockpit news ticker as new capability). When implemented, L_NEWS follows a **per-save append-only mirror pattern** keyed on source `*_id` (different from L_REF's freeze-at-first per D27). User explicitly chose to keep monthly dump cadence.

L_REF (D26 + D27) is committed and slated as next major work — 10-slice breakdown in BACKLOG.md. L_NEWS sits behind it in BACKLOG.md as deferred.

Earlier today (2026-05-12) — **Phase 3: History tab fully drained + Pressure board + Cockpit v2 + visual polish + Salary stream + Compare + Headshots.** Marathon push today: all five History stubs (Records / Awards / HoF / Streaks / Draft), the Pressure board, three visual primitives (heat-scale + Sparkline + CareerArc), real Cockpit dashboard at `/`, then three more — Salary stream on the player page (contract bar viz + options + no-trade), Compare under `/explore/compare` (4-up side-by-side career cards with WAR sparkline overlay), and PlayerAvatar headshots streaming OOTP-generated face PNGs across player page / cockpit / roster. Backed by `GET /api/records?scope=&discipline=&category=&era=` — UNIONs save data + Lahman 1871-2019 + BREF 2020-2025 + cross-source merged career rollups + Statcast 2015-2025 batted-ball quality. Three flat picker rows (Scope / Discipline / Era) + a Category strip dynamically populated from the available leaderboards in `f_record_player`. Source chips color-coded (emerald=save, indigo=lahman, sky=bref, violet=merged, amber=statcast); rows clickable through to `/player/<id>` when the underlying record carries an OOTP player_id, plain-text otherwise. Server re-ranks rows globally when era=all so duplicates between `save` (OOTP-imported) and `lahman` (real-life) sit adjacent — confirms the data integration story (Bonds 73 / 73, McGwire 70 / 70, etc.). Earlier today shipped the situational-splits stack (5 slices, 14 splits per year/level) + the **D20 pre-save MLB baselines maintenance pass** that drains `—` from advanced stats on every imported real-history player-season.

Maintenance slice — **D20 pre-save MLB baselines** (closed earlier today): The `_lg_constants_advanced` view is now a UNION of `_native` (OOTP `league_history_*` — save years only) and `_imported` (Lahman 1871-2019 + BREF 2020-2025, summed across AL/NL into MLB league_id=203, level_id=1). `f_player_season_advanced_batting` jumped from 30k → **244,183 rows** — every imported MLB player-season pre-2026 now resolves wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR. Headline spot-checks: Bonds 2001 wOBA .550 / OPS+ 257 / b_WAR 12.5 (vs BBR 259 / 12.5); Pujols 2003 OPS+ 189 (BBR 189 — exact); Trout 2018 OPS+ 198 (real 198 — exact); Pedro 2000 ERA+ 285 (BBR 291); Mantle 1956 OPS+ 220 (BBR 210, modern Yankee Stadium PF gap). Soft-skip on missing history tables means smoke / fresh warehouses still build cleanly. Park factors for pre-2026 use the team's *current-day* park (deferred follow-on); minor-league pre-save baselines stay null (Lahman doesn't carry them). Reconcile harness clean — no save-side regression.

Earlier-today slices (situational stack) in order:
1. **Batter situational splits** — first version of the section: All / RISP / RISP 2-out / Late & Close per (year, level), OPS color-coded vs the All baseline (≥25 pts emerald, ≤-25 rose). Single-season at first (limited by `f_pa_event` shape).
2. **Multi-year `f_pa_event`** (architectural — D19) — the "OOTP replaces at_bats_event.csv on rollover" caveat was build-side, not storage-side. L0 retains every ingested dump's rows by `dump_date`, so we rebuilt `f_pa_event` to read L0 directly with cross-dump dedup keyed on (game_id, season_year). Discovered along the way that **OOTP recycles `game_id` across seasons**, so PK was promoted to (year, game_id, batter_id, pa_in_game_seq). Row counts: `f_pa_event` 877k → 5.1M; `f_player_season_statcast_*` 3,305 / 3,692 → 20,800 / 21,513; `f_record_player` 1,840 → 4,550.
3. **Pitcher situational splits** — same SQL template keyed on `pitcher_id` instead of `batter_id`. Slash columns reflect what the pitcher allowed; UI color logic inverts (emerald when OPS-allowed BELOW baseline = clutch). Crochet 2027 RISP 2-out **.316 OPS allowed**; 2029 .839 (regressed).
4. **Bases + platoon splits** — added `bases_empty` / `bases_loaded` (off `base1/2/3`) and `vs_left` / `vs_right` (LEFT JOIN to `players_current` for handedness; switch-hitters resolve to opposite of pitcher's hand). Side-aware labels: batter card "vs LHP/RHP", pitcher card "vs LHB/RHB". Sanity invariant: `vs_left + vs_right = all` ✓.
5. **Counts + spray splits** — added `first_pitch` / `two_strike` / `full_count` (count BEFORE the resolving pitch) and `pull` / `center` / `oppo` (BIP-only spray; UI skips color coding since denominators differ). Empirically verified `hit_xy` is **batter-relative**, not field-absolute (mean hit_xy on HRs ≈71 for both LHB and RHB — same pull-side band), corrected DATA_NOTES.

**Next — non-L_REF work.** L_REF analytical layer is complete; remaining L_REF backlog is cosmetic (Slices 6-frontend / 8 / 9) plus partial / deferred items (7, 10). The next high-leverage work is back to UI/UX:
- **Slice 6 v2** — Frontend swap of `StadiumSprayChart` from hand-coded 5-point geometry (`web/lib/stadiums.ts`) to API-driven 7-segment renderer. Data layer is shipped (`/api/parks`); just needs renderer + delete-old.
- **Slice 8** — Real team logos via `.oi` files. Manual filename catalog + `/api/logos/{abbr}` route + `<TeamLogo>` component to replace `font-mono BOS` chips. Cosmetic but visibly elevates the IA across 5+ pages.
- **Slice 9** — Real HoF plaques on `/history/hof`. Needs lref_master.hofID → bbref crosswalk + `/api/hof/plaque/{bbref}.png` route. Cosmetic.

Or pivot back to analytical: RE24/WPA/LI columns on `f_pa_event` from `lref_re288_table` + `lref_wpa_table` + `lref_li_table` — pure additive work that unblocks high-leverage / clutch leaderboards.

**Architectural pin (D27, 2026-05-13 evening)**: L_REF is **per-save and frozen at first ingest**. On first `diamond ingest` for a save, L_REF tables snapshot into `<save>/diamond/diamond.duckdb` and stay pinned to that vintage for the save's lifetime. Subsequent ingests skip L_REF re-ingest by default; explicit `diamond ingest --refresh-lref` opts into pulling new data with CLI diff preview. This mirrors OOTP's own engine convention (saves capture reference data at creation; install-folder patches don't retroactively rewrite running saves) and makes "why did Bonds 2001 OPS+ shift between yesterday and today?" a non-question. Categories that would drift on patch if we didn't freeze: calculation tables (`misc/`), league baselines (`era_*.txt`), park factors (`era_ballparks.txt`, `pt_ballparks.txt`), engine config (`major_league_baseball.json`, `financials.txt`). Categories that wouldn't (additions are upgrades): crosswalks, schema docs, cosmetic assets. We freeze together for simplicity.

**Deep-dive on 2026-05-13 evening uncovered three tiers of value** in the parent folder:

1. **Calculation parity (highest leverage)** — `misc/` ships OOTP's canonical analytical lookup tables: `xwoba_table.txt` / `xba_table.txt` / `xslg_table.txt` (LA × EV grids), `re288_table.txt` (RE by outs/bases/count), `wpa_table.txt` (480-row win probability), `li_table.txt` (432-row Tango leverage index), `xiso_table.txt` (6-zone Statcast LSA classifier), `pi_table.txt` (pitch impact). Reading these directly **guarantees our numbers match OOTP's in-game UI exactly**. Replaces ~200 lines of formula code in `src/diamond/advanced/` with table joins.

2. **Source replacement** — `database/era_stats.txt` (157 rows × **82 cols**) replaces our D20 Lahman + BREF UNION; `database/era_stats_minors.txt` (2,335 rows × 47 cols) **unblocks the deferred MiLB pre-2026 advanced-stats backlog**; `database/era_ballparks.txt` (3,105 rows with LH/RH splits) replaces Lahman BPF/PPF and adds handedness dimension; `database/era_modifiers.txt` + `era_fielding.txt` + `total_modifiers.txt` add per-year talent + fielding + composite multipliers we currently don't have; `stats/Master.csv` (24,747 rows × 68 cols) replaces Chadwick.

3. **Engine config + cosmetic** — `database/major_league_baseball.json` (authoritative roster/IL/DH rules), `database/financials.txt` (salary-bracket engine), `database/db_structure_ootp27_csv.txt` (version-current schema doc — we'd been working from the ootp21 fallback), `hof/index.json` + 8+ real Hall-of-Fame plaque PNGs, `colors/*.xml` (per-team brand palettes), `tables/*` binary files (OOTP's saved column-layouts per view — reverse-engineerable to extract canonical column orderings).

**Re-ranked slice plan (10 slices, see `docs/BACKLOG.md` for full breakdown)**:

| # | Slice | Highlights |
|---|---|---|
| 1 | ✅ **L_REF ingest layer + per-save freeze** (shipped 2026-05-14) | 27 tables / 575,587 rows; `_diamond_settings.lref.*` provenance; `--refresh-lref` opt-in path |
| 2 | ✅ **Calculation-parity swap** (shipped 2026-05-14) | `f_player_season_xstats_batting` (20,787) + `_pitching` (21,504) via bilinear interpolation; player page wOBA \| xwOBA side-by-side; leaderboard catalog + 3 glossary entries |
| 3 | ✅ **Era-aware park factors with LH/RH splits** (shipped 2026-05-14) | `_park_factor_resolved` swapped to `lref_era_ballparks`; batter handedness blend (L/R/S); Bonds 2001 OPS+ 267→262, Walker 1999 215→191 |
| 4 | ✅ **D20 v2 era_stats source swap** (shipped 2026-05-14) | Lahman+BREF UNION dropped for `lref_era_stats` (1870-2025 single source); Bonds 2001 / Pujols 2003 / Trout 2018 essentially unchanged |
| 5 | ✅ **MiLB pre-save baselines** (shipped 2026-05-14) | `_lg_constants_advanced_imported` extended with 11 MiLB leagues × 124 yrs via `lref_era_stats_minors`; **84,000 newly-resolved player-seasons** that previously rendered `—`; Joe Lis 1972 IL wRC+ 289 |
| 6 | 🟡 **Ballpark integration (data layer shipped)** | `/api/parks` returns 240 parks with 7-segment geometry + LH/RH factors. Frontend swap of `StadiumSprayChart` deferred (renderer refactor) |
| 7 | ⏸ **OOTP↔Lahman crosswalk swap** | SKIPPED. Master.csv lacks `mlb_id` and `BBrefMLBid` — can't replace Chadwick for the existing `mlb_id → bbref_id` consumers (HoF MLB-API integration, awards). Complementary, not replacement. |
| 8 | ⏸ Real team logos | Deferred. Requires team_abbr → `.oi` filename catalog + image route + `<TeamLogo>` frontend component |
| 9 | ⏸ Real HoF plaques | Deferred. Needs lref_master.hofID → bbref + plaque endpoint + `/history/hof` UI rewiring |
| 10 | ⏸ Schema doc + brand colors | Brand colors **blocked**: `colors/*.xml` is uniform-asset metadata, not hex palettes (D26 framing was wrong). Schema doc fold separable but low-leverage |
| 3b | Era-aware park factors (D22 v2) | Same row as #3 above |
| 4 | D20 v2 — replace Lahman+BREF UNION | Pull baselines from `lref_era_stats` instead |
| 5 | MiLB pre-save baselines | `lref_milb_master` + `lref_era_stats_minors` extend `_lg_constants_advanced_imported` |
| 6 | Ballpark integration | `/api/parks` from `lref_pt_ballparks`; delete `web/lib/stadiums.ts` |
| 7 | OOTP↔Lahman crosswalk swap | Replace Chadwick with `lref_master` |
| 8 | Real team logos | `/api/logos/{abbr}` + `<TeamLogo>` component everywhere |
| 9 | Real HoF plaques | `<ootp>/hof/*.png` + plaque text on `/history/hof` |
| 10 | Schema doc fold + brand colors | Fold `db_structure_ootp27_csv.txt` content; parse `colors/*.xml` |

Beyond L_REF, lower-priority backlog:
- **Distributions / cohort histograms** under /explore (extends Chart Builder)
- **Cohorts with set ops** (∪ ∩ −) — first-class saved sets
- **AI overlay v1.1** — pricing fetcher, daily cap auto-degrade, smart-tier auto-runs, Gemini / Ollama adapters
- **Per-save league_ids customization** in setup wizard (D3 v2.2)
- **Color-blind mode v2** — extend cb theme to swap verdict / badge palettes

---

## One-line summary

Phases 1-2 closed; analytical CLI surface complete; real MLB history through 2025 backfilled; Phase 3 UI live — five-tab IA (Club / League / World / History / Explore) wired into the layout; Club landing renders save metadata + tools grid; movement ledger covers all four direction buckets; roster page — full org tree grouped by level with Basic/Advanced/Contact stat-mode toggle; standings page on `/league` (sub-league × division × team from `team_record_snapshot`); player page Stats tab full (batting / pitching / fielding / advanced + **Defensive Profile** per-position cube + **Service & Status** card + **Situational batting / pitching** with 14 splits across leverage / bases / platoon / counts / spray); theme system supports light / dark / neutral / color-blind with dark as default; in-app Quit reliably kills both dev servers. L3 Statcast cohort + SIERA materialized; `f_pa_event` is now **multi-year** via L0 cross-dump dedup (D19) — 4 years of at-bat history queryable. Combined bWAR / pWAR via OOTP-supplied WAR (Mayer 3.2 = IE 3.2 etc.); per-position fielding cube sourced from `players_fielding_current` view over the snapshot. **Pre-save MLB league baselines** UNIONed in from Lahman 1871-2019 + BREF 2020-2025 (D20) — every imported real-history player-season now resolves wOBA / wRC+ / OPS+ / FIP / ERA+ / b_WAR on the player page (244k batting rows, vs 30k pre-fix).

## What works today

- **Project skeleton**: Python 3.14 + DuckDB + Polars + Typer; package at
  `src/diamond/`; editable install via `pip install -e .[dev]`.
- **CLI**: `diamond decode`, `diamond decode-codes`, `diamond reconcile`,
  `diamond coverage`, `diamond advanced`, `diamond ingest`,
  `diamond draft`, `diamond records`, `diamond awards`, `diamond hof`,
  `diamond fetch-history` (Lahman + Statcast one-time backfill).
  All audit/report commands write markdown to `audit_output/` (gitignored).
- **Reconciliation harness** ([src/diamond/audit/reconcile.py](src/diamond/audit/reconcile.py))
  — per-column comparison of all 21 `import_export` Red Sox roster CSVs against
  derivations from monthly dump CSVs across the full 220-player Red Sox org tree
  (MLB + AAA + AA + A+ + A + Rookie + 2 DSL + FCL). 16 of 21 files at 100% A+B.
  See scorecard below. This stays in the codebase as a permanent regression
  check (Decision D8).
- **Verified codebooks** ([src/diamond/constants.py](src/diamond/constants.py))
  — `GameType`, `SplitId`, `AtBatResult` (at-bat domain); `AwardId` (13 codes
  cross-ref'd with league_history), `LeaderCategory` (47 of 60), `StreakId`
  (21 profiled), `BodyPart` (12 profiled); `Popularity`, `ScoutingAccuracy`,
  personality bucket helper.
- **Advanced stats library** ([src/diamond/advanced/](src/diamond/advanced/))
  — 5 tiers of modern advanced stats from at-bat data (~25 metrics). Per-tier
  modules: `contact.py`, `situational.py`, `sabermetric.py`, `defensive.py`,
  `approach.py`. Shared at-bat view in `enriched.py`; advanced-lib-scoped
  per-league-year linear weights / FIP const / lgERA in
  `advanced/league_constants.py` (kept for now — produces wOBA-scale calibration
  the audit derivation doesn't need; consolidation is a post-warehouse task).
- **League-constants module** ([src/diamond/league_constants.py](src/diamond/league_constants.py))
  — top-level module that registers two DuckDB views (`lg_constants_bat`,
  `lg_constants_pit`) sourced from `league_history_*` and keyed by
  `(league_id, year, level_id)` per Decision D11. Replaces the inline CTEs
  formerly in `reconcile.py`. Verified byte-identical reconcile output post-refactor.
- **5-layer warehouse DDL** ([src/diamond/schema/](src/diamond/schema/))
  — full `build_l0` / `build_l1_machinery` / `build_l1_reference` /
  `build_l1_event` / `build_l1_snapshot` / `build_l2` pipeline. Each
  module holds its layer's specs and builders. `scripts/smoke_warehouse.py`
  exercises the full pipeline end-to-end against the latest dump in <60s,
  asserting layer invariants (PK enforcement, scope filters, dim flatten,
  D12 scouted-rating filter, idempotency). Layer counts:
  - L0: **69 raw tables** (5.76M rows from one dump)
  - L1: 12 reference + 35 event + 21 state-snapshot + 7 `_current` views + 2 machinery (`_scoped_*`) + 1 admin (`_diamond_ingests`)
  - L2: 8 facts (`f_player_season_batting/pitching/fielding`, `f_player_career`,
    `f_team_season`, `f_league_season`, `f_pa_event` *— multi-year as of
    2026-05-12 per D19; sourced from L0 with cross-dump dedup, PK includes
    `year` since OOTP recycles `game_id` across seasons*, `f_award_event`)
  - L3: 11 derived (`f_trade_participant`, `player_movements` w/ `trade_id`,
    `f_draft_class`, `f_record_player`, `f_award_career_player`,
    `f_award_franchise`, `f_player_streak`,
    `f_player_season_advanced_batting` + `_advanced_pitching` [the
    sabermetric stack — wOBA/wRAA/wRC/wRC+/OPS+/oWAR for batters; FIP
    + **SIERA** + ERA+/pit_WAR for pitchers; park_avg on both],
    **`f_player_season_statcast_batting` + `_pitching`** [BIP / max_EV
    P90 / avg_EV / hard_hit% / sweet_spot% / barrel% per (player, year,
    league, level), 30-BIP minimum, materialized from `f_pa_event`])
  - History backfill (one-time): 8 `history_lahman_*` tables +
    2 `history_statcast_*` tables + 2 `history_bref_*` tables +
    2 `history_mlbapi_*` tables (awards + HOF gap-fill 2018+) +
    `history_player_id_map` (Chadwick Register). f_record_player
    UNIONs five sources ('save' / 'lahman' / 'bref' / 'statcast' /
    'merged') with `--era` CLI filter. Career rows dedup across
    sources via bbref_id crosswalk: save wins for active players;
    Lahman + BREF + Statcast merge into 'merged' source for
    pre-save retirees (Pujols Lahman 656 + BREF 30 = merged 686 HR).
    Statcast adds EV/barrel/hard-hit categories.
    f_award_career_player UNIONs save + lahman + mlbapi (with
    same dedup-on-bbref_id-in-save filter for the gap-fill rows).
    `diamond hof --era lahman` shows real Cooperstown through 2026.
- **Empirical scripts retained** in `scripts/` — `xstats_eda.py` and
  `xstats_3d.py` are the evidence behind the structural-limit D-tier verdict
  on xBA/xSLG/xwOBA. Rerun rather than re-investigate.

## Phase 1 — Audit, closed 2026-05-04

Headline reconciliation: of ~360 IE columns,
- **~270 reconcile cleanly (A/B)**
- **0 C-tier**, **0 G-tier** — all formula puzzles and int→string mappings decoded
- ~50 F-tier by design (Decision D5: plate-discipline columns; string-formatted display)
- ~7 D-tier (xBA/xSLG/xwOBA/xERA — confirmed structurally non-derivable; see DATA_NOTES)
- ~25 E-tier partial (multi-level slash-line gaps, hit_xy spray boundary — research items)

Major decodes shipped during audit (full formulas in [DATA_NOTES.md](DATA_NOTES.md)):
- DEF rating, popularity, personality buckets, scouting accuracy, VELO band, G/F bucket
- OPS+, ERA+, FIP, RC, RC/27, wOBA via `league_history_*` + halved/non-halved park factors
- SIERA via Fangraphs canonical formula (quadratic + interaction terms)
- pLi (cumulative, not average), RA (g-gs), RSG (rs/gs)
- EV buckets (75/95), Barrel (flat threshold not Statcast cone), regular-season filter, PCB-derived BIP
- Contract data via `players_contract_extension` + `players_roster_status`; current_year is 0-indexed

## Reconciliation status (frozen at audit close)

| File | Reconciled | Outstanding |
|---|---|---|
| `batting_stats_1` | **24/24** | — |
| `batting_stats_2` | **18/18** | — |
| `pitching_stats_1` | **25/25** | — |
| `pitching_stats_2` | **26/26** | — |
| `fielding_stats` | **12/12** | — |
| `batting_ratings` | **18/18** | — |
| `batting_potential` | **11/11** | — |
| `pitching_ratings` | **12/12** | — |
| `pitching_potential` | **10/10** | — |
| `fielding_ratings` | **9/9** | — |
| `individual_pitch_ratings` | **15/15** | — (Sprague PIT 1/220 edge case — see BACKLOG) |
| `individual_pitch_potential` | **15/15** | — |
| `position_ratings` | **10/10** | — |
| `popularity_info` | **6/6** | — |
| `personality___morale` | **6/6** | — (4 fresh-acquisition Unknowns expected) |
| `financial_info` | **12/12** | — |
| `batting_superstats_1` | partial 22/25 | xBA/xSLG/xwOBA D-tier closed; spray E-tier |
| `pitching_superstats_1` | partial 13/17 | xBA/xSLG/xwOBA/xERA D-tier closed |
| `batting_superstats_2` | **3/20** | 17 plate-discipline F-tier per D5 |
| `pitching_superstats_2` | **3/19** | 16 plate-discipline F-tier per D5 |
| `default` | 3/6 | 3 string-formatted display fields F-tier |

Latest reports (regenerable, gitignored): `audit_output/{decoder,codes_decoder,reconciliation,coverage,advanced_stats}_report.md`.

## Phase 2 + analytical layer — closed 2026-05-06

Phase 2 (schema + ingest) closed 2026-05-05; the analytical layer + real-MLB
history backfill closed same-day 2026-05-06. Major shipped artifacts:

**L3 derived tables** (7):
- `f_trade_participant` — 1,275 rows; 1 per (trade × player)
- `player_movements` — 95,643 rows; refined `movement_type` (promotion / demotion /
  intra_org_lateral / waiver_or_other / trade) + `trade_id` attribution
- `f_draft_class` — 2,320 rows; outcome buckets (mlb_star/mlb_regular/mlb_callup/
  in_draft_org/traded_away/released/retired)
- `f_record_player` — 4,700 rows; UNIONs save + lahman + bref + statcast + merged
  with `--era` CLI filter; bbref_id career dedup. New `direction` column drives
  ASC vs DESC ranking (pitching contact-allowed rate stats sort ASC, "Fewest" wins).
  Save-side EV (MAX_EV/AVG_EV/HARD_HIT_PCT) computed off `f_pa_event` with
  50-BBE qualifier; calibration ~5 mph below Statcast scale (documented in
  DATA_NOTES.md).
- `f_award_career_player` — 9,953 rows; UNIONs save + merged (Lahman+mlbapi
  collapsed via bbref_id; merged filtered to non-save bbref_ids to avoid
  active-player double-count via OOTP historical-seed import).
- `f_award_franchise` — 1,856 rows
- `f_player_streak` — 2,098 rows; top-50 per (streak_id × scope), where
  scope ∈ {active, all_time}. `streak_label` from `StreakId` IntEnum.

**Real MLB history backfill** (one-time, capped at save_start_year - 1 = 2025):
- Lahman 1871-2019 (8 tables via cdalzell mirror)
- BREF 2020-2025 (2 tables via pybaseball — fills the Lahman cap)
- Statcast 2015-2025 (2 tables via Savant — EV / barrel / hard-hit)
- MLB Stats API 2018+ awards + 2019+ HOF (2 tables — fills Lahman award/HOF cap)
- Chadwick Register (1 table — bbref ↔ MLBAM crosswalk for cross-source linkage)

**CLI surface**:
- Audit: `decode`, `decode-codes`, `reconcile`, `coverage`, `advanced`
- Ingest: `ingest [<dump>] [--all] [--rebuild-only] [--force] [--no-rebuild]`
- Analytics: `draft <year> [--team]`, `records [--era] [--scope] [--category]`,
  `awards [--era] [--player] [--bbref-id] [--team] [--award]`,
  `hof [--era] [--candidates]`,
  `streaks [--all-time] [--category]`
- Setup: `fetch-history` (one-time real-history backfill, idempotent)

## What's next — Phase 3 (UI implementation)

Per [UI_DESIGN.md](UI_DESIGN.md). Build order:

1. ✅ **D13 reference scope expansion** — done 2026-05-07.
2. ✅ **D15 stat dictionary** thin v1 — done 2026-05-07. 39 entries.
3. ✅ **D16 tech stack pick** — done 2026-05-07. FastAPI + Next.js
   (App Router) with Pydantic-derived TS types.
4. ✅ **API + web scaffold** — done 2026-05-07, **verified live**:
   - Backend (`src/diamond/api/`) — FastAPI app + glossary + health
     routes + Pydantic schemas. `/api/health`, `/api/glossary`,
     `/api/glossary/{id}`, 404 path all live.
   - Frontend (`web/`) — Next.js 15 App Router + Tailwind + KaTeX
     + react-katex. Glossary list + detail pages render server-side
     against the live API; `pnpm build` succeeds clean.
   - Type-gen (`scripts/generate_types.py`) — Pydantic → TS pipeline
     working; `make types` overwrites `web/lib/types/api.ts` with
     auto-generated content carrying Pydantic docstrings as JSDoc.
   - Dev workflow (`Makefile` + `docs/DEV.md`) — `make api`, `make
     web`, `make types`, `make smoke` documented. Two-terminal flow.
   - Frontend dev deps installed on this machine: Node 24, pnpm 10,
     web/node_modules complete.
5. ✅ **Player page Stats tab — batting + pitching + fielding** — done 2026-05-07.
   - `GET /api/players/{player_id}` returns bio + per-(year, level,
     team) batting + pitching stints with synthesized per-season
     "TOT" rows + per-(year, position, team) fielding rows + career
     rollups (batting/pitching cross-year, fielding per-position).
     One big payload, one fetch. Pydantic schemas in
     `src/diamond/api/schemas/player.py`; route in
     `src/diamond/api/routes/players.py`; warehouse connection
     pool in `src/diamond/api/warehouse.py`.
   - `/player/[id]` page (URL uses internal `player_id`). Server
     component fetches player + glossary in parallel. Bio header,
     tab strip (Stats active; others placeholder), and three
     stacked stat sections.
   - `web/components/PlayerStatsTab.tsx` (client component):
     - **Batting / Pitching**: Bref-shaped disclosure-row tables.
       One row per year (TOT if multi-stint, single stint otherwise);
       chevron expands multi-stint years to indented per-(level,
       team) sub-rows. Career-totals row pinned at bottom.
     - **Fielding**: flat per-(year, position, team) rows — fielding
       isn't summable across positions in a meaningful way, so no
       TOT-style disclosure. Per-position career rollup rows pinned
       at bottom; explainer line below the table when a player has
       multi-position career rows ("cross-position totals omitted on
       purpose").
   - Column headers + tooltips read from `STATS[id]` (D15 contract):
     dictionary now 60 entries (+13 batting/pitching counting; +8
     fielding). Header overrides for K/9, BB/9, IP, INN where the
     display label diverges from the dictionary's `short_label`;
     tooltip still inherits from the parent entry.
   - Advanced cohort (wOBA / wRC+ / OPS+ / FIP / ERA+ / WAR /
     Statcast EV + barrel) still **deferred**. Advanced stats live
     as functions in `diamond.advanced.*`; surfacing them on the
     player page needs either per-season L3 materialization (the
     `f_player_season_advanced_*` work listed in `l3.py` docstring)
     or threading the on-demand computation through the request
     handler.
6. ✅ **Advanced stats column block** — done 2026-05-07.
   - New L3 module `src/diamond/schema/l3_advanced.py` materializes
     `f_player_season_advanced_batting` (244k rows) +
     `f_player_season_advanced_pitching` (151k rows) per
     (player, year, league_id, level_id). Linear weights computed
     inline via SQL (woba_scale calibrates against league OBP),
     park factor pulled from the dominant team's park (most PA /
     most outs), filters mirror the audit (PA > 0; outs >= 30 / 10
     IP for pitching).
   - `_lg_constants_advanced` view aggregates league_history at
     (league_id, year, level_id), exposing every constant the
     formulas need (linear weights, woba_scale, fip_constant,
     runs_per_pa, lg_obp/slg/era).
   - Player API extended with `advanced_batting` +
     `advanced_pitching` arrays. UI renders two new sections —
     "Advanced Batting" (PA / wOBA / wRAA / wRC / wRC+ / OPS+ /
     oWAR) and "Advanced Pitching" (IP / FIP / ERA+ / pit_WAR) —
     per-(year, level) flat rows with explainer footnotes.
   - Math verified: Crochet 2029 ERA+=127 (matches audit IE-recon
     127), Skubal 2029 FIP=2.65 (matches docs), Gunnar Henderson
     2029 oWAR=8.7 (matches docs). Top OPS+ leaders 2029 MLB:
     Kurtz 164, Henderson 164, Judge 159, Rooker 159, Santiago 155.
   - **D20 (2026-05-12)** closes this for MLB pre-save seasons:
     `_lg_constants_advanced` now UNIONs OOTP's native
     `league_history_*` rows with an `_imported` view sourced from
     Lahman 1871-2019 + BREF 2020-2025 (summed across AL/NL into
     league_id=203, level_id=1). f_player_season_advanced_batting
     30k → 244,183 rows; spot-checks Bonds 2001 OPS+ 257 (BBR 259),
     Pujols 2003 OPS+ 189 (BBR 189 — exact), Trout 2018 OPS+ 198
     (real 198 — exact). Minor-league pre-save baselines remain null
     (Lahman has spotty MiLB coverage; OOTP↔real league_id crosswalk
     non-bijective). Park factors for pre-2026 fall back to the
     team's *current-day* park — small bias on OPS+/ERA+, none on
     wOBA / wRC+ / wRAA. Documented in DECISIONS D20 + DATA_NOTES.
7. ✅ **Movement ledger** — done 2026-05-08.
   - New L0/L1/L2 paths weren't needed; entire feature consumes the
     existing `player_movements` (L3) joined to
     `f_player_season_advanced_*`. Single endpoint
     `GET /api/movements?year=YYYY` returns four direction buckets:
     internal (promotion/demotion), incoming (trade/signed/
     waiver_or_other from outside), outgoing (released/trade/waiver
     to outside). Verdict logic in Python: level-aware thresholds
     (MLB ≥100 = working, ≥120 = thriving; lower levels ≥90/130);
     inverted for departures (player mashing elsewhere = 🔴 we let
     someone good go).
   - Frontend `/movements` page sections all four buckets with
     Bref-style flat tables, per-row verdict glyphs (🟢🟡🔴⚪),
     pending-rows toggle (`?include_pending=1` reveals the
     too-small-sample rows hidden by default — EOS roster swarms
     are noisy), year picker, links to player pages.
   - Real signal surfaced 2029 Red Sox: six 🔴 departures
     (Brayan Bello released → 163 ERA+ elsewhere; Yoeilin Cespedes
     released → 146 OPS+ in 453 PA; Austin Ehrlicher released →
     142 ERA+; Isael Fis released → 186 ERA+; Franklin Primera
     waivered → 151 OPS+; Anderber Urbina waivered → 141 OPS+).
8. ✅ **Real landing page (Club view v0)** — done 2026-05-08.
   - `GET /api/save` returns active-save identity (save_name,
     org_team, latest_dump_date, dump_count, scope counts, season
     range). Pydantic schema in `src/diamond/api/schemas/save.py`,
     route at `routes/save.py`.
   - `/` page renders save header (BOS Red Sox · 2029 season) +
     warehouse-status grid (45 dumps, last sync 2029-11-01, 35,261
     players in scope across 264 teams, seasons 1871–2029) + Tools
     grid with `Live` / `Soon` status pills (Movement ledger,
     Glossary, Player page live; Roster, Pressure board, Charts
     tab queued).
9. ✅ **IA backbone (D17)** — done 2026-05-08.
   - Top nav: **Club** (`/`) · **League** (`/league`) ·
     **World** (`/world`) · **History** (`/history`) ·
     **Explore** (`/explore`) · Glossary · ThemeSwitcher · Quit
   - Four `TabStub` pages (League / World / History / Explore) —
     each renders a section grid showing planned content with
     status pills. Future features land in the right tab from
     day one rather than as orphan top-level routes.
10. ✅ **Theme system (D18)** — done 2026-05-08.
    - Four themes: light / dark / neutral (warm cream) / cb
      (Wong-palette color-blind safe). CSS variables under
      `:root` and `[data-theme="..."]` selectors in
      `web/app/globals.css`. Tailwind config exposes semantic
      tokens (`bg-surface-page`, `text-content-primary`,
      `border-border`, `text-link`, etc.) so components are
      theme-agnostic.
    - **Dark is the default.** No-flash inline `<script>` in
      `<head>` reads `localStorage["diamond.theme"]` and stamps
      `data-theme` before body paints.
    - `<ThemeSwitcher />` dropdown in the layout header. CB mode
      is "chrome only" in v1 — accent + link colors swap to
      Wong-safe blue/orange, but verdict glyphs and move-type
      badges still use the green/amber/rose palette. Full CB
      verdict swap is a backlog item.
    - Migrated to tokens: layout, landing, movements page (all
      four sections), glossary list + detail, FormulaBlock,
      player bio header, PlayerStatsTab (batting / pitching /
      fielding / advanced).
11. ✅ **In-app Quit button + dev.bat one-shot launcher** — done
    2026-05-08.
    - `POST /api/admin/shutdown` — kills both servers + their cmd
      windows. Five-stage kill: web nodes (pnpm + next CLI +
      start-server.js worker, all three needed because pnpm spawns
      them in detached process groups) → port 3000 → web cmd → API
      uvicorn → API cmd → port 8000. Subprocess fully detached via
      `cmd /c start /B` so taskkill cascade can't reach it. End-to-
      end verified: real `pnpm dev` + uvicorn → click Quit → both
      cmd windows close, both ports free.
    - `dev.bat` at repo root — spawns `api.bat` + `web.bat` in
      named consoles, then opens the browser at :3000 after a
      6-second compile pause. Documented in DEV.md.
12. ✅ **Roster page** — done 2026-05-09. `/roster` lists every active
    org-tree player grouped by current level (MLB / AAA / AA / A+ /
    A / Rk / DSL), separating position players + pitchers within each
    level. Filter pills: Level (single-select; All + every level
    present in the data), Role (All / Position / Pitchers), Hand
    (All / R / L / S). **Three-mode stat toggle: Basic ⇄ Advanced
    ⇄ Contact.** Server returns full ~200-player payload in one
    round-trip (~95 KB); all filter / sort / mode interactions are
    client-side. Names link to `/player/[id]` — closes the
    navigation loop. Wired into Club landing's Tools grid.
    - Backend: `src/diamond/api/routes/roster.py`,
      `src/diamond/api/schemas/roster.py`. Single SQL JOIN pulls
      every (player + current team + season stats + advanced +
      Statcast cohort) tuple, then Python folds into level groups.
    - Frontend: server component at `web/app/roster/page.tsx`
      delegates state to `web/components/RosterClient.tsx`
      (the client component holds filters + mode).
13. ✅ **Advanced + Statcast surface expansion** — done 2026-05-09.
    - **wRAA / wRC / park_avg surfaced** on the roster Advanced
      view. Were already in `f_player_season_advanced_batting` —
      pure UI work. Park factor renders as a small subscript per
      row.
    - **SIERA materialized** in `f_player_season_advanced_pitching`
      using the Fangraphs canonical quadratic regression.
      Inputs (K/BB/BF/GB/FB) all present in `f_player_season_pitching`.
      Crochet 2.25 SIERA matches IE-reconciled 2.27 to ±0.02. Now
      surfaced on the roster Advanced view.
    - **Statcast cohort L3 build** — Two new fact tables
      (`f_player_season_statcast_batting` 3,790 rows;
      `_pitching` 3,880 rows). Per-(player, year, league_id,
      level_id), BIP ≥ 30 quality threshold. max_EV is the 90th-
      percentile EV per Statcast convention (not absolute peak).
      Barrel uses Statcast's expanding-window definition. All
      formulas mirror `diamond.advanced.contact.*`. Surfaced via
      the Contact mode toggle on the roster — pitcher rows show
      allowed-contact (lower = better), batter rows show
      generated-contact (higher = better).
    - **Earlier (incorrect) claim corrected**: I had said in an
      audit-inventory pass that Statcast inputs might not exist in
      OOTP's per-PA log. They do — verified `f_pa_event.exit_velo`
      + `launch_angle` populated 100% on BIP rows (573,958 rows,
      EV range 0–126.4 mph, LA range -75°–88°, all realistic).
14. ✅ **Full dump-CSV audit pass** — done 2026-05-09 (no UI
    output; informs the next-up list).
    - Cross-checked every CSV in latest dump against L0 (70 vs 69):
      one ingest gap — `players_pitching.csv` (67 cols of objective
      pitching ratings: stuff, movement, control × overall/vsR/vsL/
      talent + 12-pitch arsenal cube + velocity/arm_slot/stamina/
      ground_fly/hold). **All rating columns are zeroed across all
      148,513 rows × all 45 dumps in this save** — OOTP only
      populates the `players_*.csv` objective files when scouting
      is disabled. Same data IS available via `l0_players_scouted_ratings`
      (Sox-scouted, populated). Net: no usable data; defensive
      ingest fix only, queued.
    - Cross-checked every L0 column against L1+ usage: highest-
      value find is **per-position fielding cube in
      `players_fielding_snapshot`** — `fielding_rating_pos1..9`
      (current 20-80 per position), `fielding_rating_pos1..9_pot`
      (ceiling per position), `fielding_experience0..9` (plays per
      position). Fully populated, never read by any L2/L3/UI
      surface. Sample (Justin Gonzales): pos3=50 (1B current),
      pos7=65 (better in LF!), pos8=50 (capable CF), pos9=60
      (high-ceiling RF), with experience 200/197/200/184 backing
      it up. This is the "where should this guy actually play"
      data — answers it definitively per player per dump.
    - Combined-WAR feasibility revised from "multi-week build"
      down to "half-day slice" — `zr` (Zone Rating, runs-style),
      `framing`, `arm`, plus 6 difficulty-bucketed `opps_made_X /
      opps_X` cols already in `f_player_season_fielding`. Adds
      defensive component to oWAR for combined bWAR.
15. ✅ **Combined bWAR / pWAR** — done 2026-05-10. Reframed mid-slice
    after a one-line audit query: OOTP **directly supplies** combined
    WAR via `players_career_batting.war` (bWAR — offense + defense
    + position + base-running) and `players_career_pitching.war` /
    `.ra9war` (FIP-WAR + RA9-WAR — both with leverage adjustment for
    relievers). Already aggregated into `f_player_season_*.war` and
    reconciled to IE WAR as A-tier (audit `reconcile.py` line 211
    + 393, audit dating to 2026-05-04). The slice was therefore
    plumbing-only:
    - **L3 column add** — `f_player_season_advanced_batting.b_war`,
      `f_player_season_advanced_pitching.p_war` + `.p_ra9_war`. SUMs
      across stints into the (player, year, league, level) grain.
    - **Verified** Mayer 3.2 = IE 3.2 (exact), Anthony 0.9 = IE 0.9
      (exact), Crochet 5.5 = IE 5.5 (exact), Whitlock 0.4 = IE 0.4
      (exact). The custom `o_war` / `pit_war` formulas (offense-only
      / flat 1.13 replacement) run ~1.5-2 wins different on top
      seasons since OOTP includes leverage + defense + position.
    - **Schema + types** — `RosterBattingLine.b_war`,
      `RosterPitchingLine.p_war` + `p_ra9_war`,
      `PlayerAdvancedBattingRow.b_war`,
      `PlayerAdvancedPitchingRow.p_war` + `p_ra9_war`. TS regenerated.
    - **UI** — Roster Advanced view: `oWAR` → `bWAR`, `pWAR` (custom
      pit_war) → `pWAR` (OOTP-canonical). Tooltips reference the
      glossary for the custom alternatives. Player page Advanced
      sections: kept oWAR + pit_WAR alongside bWAR / pWAR / RA9-WAR
      so users can see the gap (offense-only vs combined; FIP-WAR
      vs RA9-WAR signals defense / sequencing).
    - **Dictionary** — added `bWAR`, `pWAR`, `RA9_WAR`; deprecated
      the ambiguous `WAR` entry in favor of the role-specific pair.
      62 dictionary entries total.
16. ✅ **Per-position fielding view** — done 2026-05-10. New
    "Defensive Profile" section on the player page surfaces the
    9-position scouted-rating cube (current × ceiling × experience).
    Sorted by experience descending so the spots the player has
    actually logged innings at appear first; sub-meaningful rows
    (no rating + no experience) are hidden. Real signal verified:
    - Justin Gonzales (POS=1B): 1B current 50 / LF 65 / RF 60 /
      CF 50 — 197 LF plays, 200 CF plays, 184 RF plays.
    - Marcelo Mayer (POS=2B): 2B current 65 (200 plays) / 3B 45
      (124 plays) / SS 30 (58 plays); ceilings 65 / 65 / 60.
    - Crochet (POS=P): P current 45 only; everything else null.

    Implementation:
    - **L1**: new `players_fielding_current` view (filters
      `players_fielding_snapshot` to latest dump_date) added to
      `_CURRENT_VIEWS` in `l1_snapshot.py`.
    - **API**: new `PlayerPositionFielding` schema
      (position / position_name / rating_current / rating_potential
      / experience), `position_fielding: list[PlayerPositionFielding]`
      added to `PlayerResponse`. Route handler unpivots the 9
      `_pos1..9` columns into a 9-row block, normalizing zero ratings
      / experience to `null` so the UI renders em-dashes (OOTP encodes
      "never rated / never played there" as 0).
    - **UI**: `DefensiveProfileTable` in `PlayerStatsTab.tsx` —
      Pos / Current / Ceiling / Plays columns, color-coded by 20-80
      rating (≥70 emerald-bold, 60+ emerald, 50 default, 40s amber,
      <40 rose). Footer note explains the 20-80 scale + sort
      convention.
17. ✅ **Service-time / arbitration clock** — done 2026-05-10. New
    "Service & Status" card on the player page (between bio header
    and tab strip). Shows:
    - **MLB service**: "Xy Yd" with Y = days into current year
      (Bref / MLBPA convention; 172 service days = 1 year).
    - **Service class**: Pre-arb / Arb (Y1/Y2/Y3) / FA-eligible —
      computed from total service days (3.000y / 6.000y boundaries).
      Color-coded chip: emerald (FA), sky (arb), neutral (pre-arb).
    - **Days to FA**: max(0, 1032 - mlb_service_days). Hidden when
      already FA-eligible.
    - **Options**: "n/3 used" + "+m this season" delta when nonzero.
    - **Status flags**: Active / 40-man / 10-day IL / 60-day IL /
      DFA / Waivers. Color-coded; only renders flags that are true,
      so the November snapshot reads clean (Active + 40-man only).
      Mid-season ingests will surface DL / DFA / waivers.

    Verified: Mayer 4y 128d Arb(Y2) FA-216d / Anthony 4y 95d Arb(Y2) /
    Casas 7y 21d FA-eligible / Devers 12y 70d FA-eligible / Crochet
    9y 28d FA-eligible / Gonzales 1y 94d Pre-arb FA-766d.

    Implementation:
    - **API**: new `PlayerRosterStatus` Pydantic schema + fetcher;
      `_service_class()` + `_service_display()` helpers in
      `routes/players.py`. Constants `_DAYS_PER_SERVICE_YEAR=172` +
      `_DAYS_TO_FREE_AGENCY=1032`.
    - **UI**: inline JSX in `web/app/player/[id]/page.tsx` — a small
      card under the bio header. Tooltips explain Pre-arb / Arb /
      FA boundaries + options semantics.
    - Fields not surfaced (semantics unclear): `years_protected_from_rule_5`
      + `has_received_arbitration`. Add when needed.
    - Super-Two qualifiers (early-arb edge case for high-service-day
      pre-arb players) are NOT modeled — OOTP handles internally
      and exposes no public flag.
18. ✅ **Standings page** — done 2026-05-11. Fills the `/league` tab
    stub with real content. New endpoint
    `GET /api/standings?league_id=&year=` returns sub-league × division
    × team rows from `team_record_snapshot` at the MAX(dump_date)
    snapshot within the chosen year. Defaults: MLB (203) / latest year
    with data. Routing falls back to first-available rather than 404
    on bad query strings (deep-link forgiving).

    Implementation:
    - **Schemas**: `StandingsResponse` (league + year + dump_date +
      pickers + sub_leagues), `StandingsSubLeague`, `StandingsDivision`,
      `StandingsTeamRow`, `StandingsLeagueRef` in
      `src/diamond/api/schemas/standings.py`. Magic-number sentinels
      (`-1` clinched, `1000` not-applicable) collapse into
      `magic_number: int | None` + `clinched: bool`. Streak surfaced
      as signed int.
    - **Route**: `src/diamond/api/routes/standings.py`. Three queries
      per request — available-leagues (15 scoped, JOIN to `leagues`),
      available-years for the chosen league, the standings query
      itself. Filter `g > 0` drops the All-Star teams (they slot into
      `allstar_team_id0/1` but don't play a real schedule).
    - **Frontend**: `web/app/league/page.tsx` rebuilt as a real server
      component (was a `TabStub`). League picker grouped by level
      header (MLB / AAA / AA / A+ A / Rk DSL); year picker as a year
      strip. Sub-leagues stacked vertically (AL/NL on MLB); divisions
      laid out 2-up on lg+ breakpoints, 1-up on smaller. User's org
      row uses `border-l-2 border-l-accent` + a "You" pill so it's
      findable at a glance. Streak color-coded (emerald W / rose L /
      muted —). Clinched division leaders get an emerald "Clinched"
      pill. Below the standings: slim "Coming to League" stubs for
      Leaderboards / Awards races / FA pool so the IA stays scannable.

    Verified end-to-end: 2029 BOS Red Sox 93-69 in AL East (clinched
    with -1 streak); CHC 96-66 NL Central +9 streak (clinched); TEX
    AL West clinched -4 streak; full sub-league × division × team
    partition for MLB (30 + 100+ minor-league teams). AAA (1 sub-
    league with null name + 2 divisions) and AFL (absent from
    `leagues` reference table — niche limitation noted) handled.

    Known v1 limitations:
    - **AFL not in picker** — league_id=70 has team rows but no
      `leagues` reference row, so the JOIN drops it from
      `available_leagues`. AFL is a 30-game niche fall league;
      surfacing it requires a different query path.
    - **No Pythagorean / run differential** — `team_record_snapshot`
      carries W-L-Pct only; RS / RA would need a separate per-team-
      season aggregate.
    - **No team-page deep links** — abbr is shown but not yet
      clickable. Lands when team page ships.

19. ✅ **Clutch / RISP splits** on player page — done 2026-05-12.
    New "Situational batting" section on the player page Stats tab.
    Four splits per (year, level): All / RISP / RISP 2-out / Late & Close.
    Each row carries PA / AB / H / 2B / 3B / HR / BB / K + AVG/OBP/SLG/OPS.
    OPS beating the "All" baseline by ≥25 pts colors emerald (clutch);
    lagging by ≥25 colors rose (choke); inside ±25 stays neutral
    (sample-size noise on single-season cuts).

    Implementation:
    - **Schema** (`PlayerSituationalRow`) — per-(year, level, split)
      with all counting cols + server-computed slash. Empty array for
      pitchers + pre-2029 imports.
    - **SQL** (`_fetch_situational_batting`) — JOIN `f_pa_event` to
      `games_event` filtered to game_type=0 (= REGULAR_SEASON in
      `GameType`, NOT 1; verified). UNION ALL four splits within the
      base CTE for a clean tabular result. AB excludes sacrifices
      (`sac=0`); SF = (`sac=1 AND result=5`).
    - **UI** (`SituationalBattingTable`) — one per (year, level)
      tuple, but in this save the warehouse only holds 2029 splits
      (`f_pa_event` is single-season), so most players show one block.
      The "All" row is shaded as the baseline so the eye anchors there.
    - **Reconciliation**: Devers 2029 All row PA=636 / AB=535 /
      H=124 / HR=27 / BB=96 / K=158 — exact match against
      `f_player_season_batting` (split_id=1). Mayer 2029 All matches
      similarly (PA=582 / AB=529 / H=139 / HR=13 / BB=47 / K=116).
    Verified: Devers 2029 RISP .881 (emerald — clutch) / RISP 2-out
    .689 (rose — choked w/ 2 outs) / Late & Close .685 (rose).
    Mayer 2029 Late & Close .752 (emerald — slight clutch in tying-
    run windows). Crochet (pitcher) → 0 rows.

    **Pitcher splits** added 2026-05-12 same day — see item 21 below.
    **Bases / handedness splits** added same day — see item 22.

20. ✅ **Multi-year `f_pa_event` via L0 cross-dump dedup** — done
    2026-05-12. The earlier "single-season only" caveat was build-
    side, not storage-side: L0 retains every ingested dump's rows by
    `dump_date`. Rebuilt `_build_f_pa_event` (`schema/l2.py`) to read
    from L0 directly with cross-dump dedup. Two structural surprises
    surfaced:
    - **`game_id` is recycled across seasons** in OOTP. Empirically
      the integer 10001 is one game in dumps 2026-08 → 2027-02 (67
      PAs) and a different game in dumps 2027-09 → 2028-02 (73 PAs).
      Solution: include `year` in the canonical key. PK changed from
      `(game_id, batter_id, pa_in_game_seq)` to
      `(year, game_id, batter_id, pa_in_game_seq)`.
    - **`games.csv` resets together with at-bats** at rollover. The
      JOIN to `l0_games` requires `dump_date` matching to keep
      same-dump pairing for the year extraction.

    Dedup rule: for each `(game_id, season_year)`, pick the latest
    `dump_date` that observed at-bats for it (post-Nov dumps are
    stable; early-spring dumps trim the prior year's data). The
    `pa_in_game_seq` is then synthesized within that scope by
    file-seq order (per OPEN-4 resolution).

    `f_pa_event` carries `game_type` directly now so the situational
    fetcher no longer needs a JOIN to `games_event`. L1 `at_bats_event`
    + `games_event` stay single-dump (audit reconcile depends on per-
    dump comparison).

    Row-count impact:
    - `f_pa_event`: 877,363 → **5,132,283** (4 years).
    - `f_player_season_statcast_batting`: 3,305 → **20,800**.
    - `f_player_season_statcast_pitching`: 3,692 → **21,513**.
    - `f_record_player`: 1,840 → **4,550**.

    Verified: Devers situational now shows 2026 / 2027 / 2028 (incl.
    AAA rehab stint) / 2029. Mayer's full 4-year arc visible — 2026
    rookie struggle (.602 OPS) → 2027 breakout (.770, RISP 2-out
    .970) → 2028 peak (.764, Late & Close **1.034**) → 2029
    regression (.741). Smoke + typecheck + HTTP fetch all clean.

    UI footer + schema docstring + situational fetcher comment
    updated to reflect "every save year ingested" rather than
    "current season only."

21. ✅ **Pitcher situational splits** — done 2026-05-12. Mirror of
    item 19 keyed on `pitcher_id` instead of `batter_id`. Same row
    shape (`PlayerSituationalRow` reused — same All / RISP / RISP 2-out
    / Late & Close × per-(year, level) grain) but slash columns
    reflect what the pitcher ALLOWED. UI color logic flips: emerald
    when OPS-allowed in a split is ≥25 pts BELOW the All baseline
    (kept opp from scoring), rose when it's ≥25 pts ABOVE (gave
    up too much in clutch).

    Implementation:
    - Schema: added `situational_pitching: list[PlayerSituationalRow]`
      to `PlayerResponse` (same shape as batting).
    - Route: `_fetch_situational_batting` generalized to
      `_fetch_situational(con, player_id, side)` where `side ∈
      {"batter", "pitcher"}`. SQL is templated — only difference is
      the join column (`batter_id` vs `pitcher_id`). Both fetchers
      called from the route handler; empty arrays for the
      wrong-handed audience.
    - UI: `SituationalBattingTable` generalized to `SituationalTable`
      with a `side` prop. `opsCellClass` takes `side` and inverts
      the threshold direction for pitchers. Footer copy adapts —
      "clutch hitters reach for the ball" vs "clutch pitchers shrink
      the strike zone with runners on."

    Verified: Crochet 2027 RISP 2-out **.316 OPS allowed** (emerald —
    elite clutch starter); 2028 RISP 2-out .395 (emerald); 2029 RISP
    2-out .839 (rose — regression year). Position players → empty
    pitching block; pitchers → empty batting block.

22. ✅ **Bases / handedness splits** — done 2026-05-12. Extended the
    situational sections from 4 splits to **8**:
    - **Bases** — `bases_empty` (low-leverage anchor) and
      `bases_loaded` (max RBI chance, all three bags occupied).
      Read off the `base1`/`base2`/`base3` columns already on
      `f_pa_event`.
    - **Platoon** — `vs_left` / `vs_right`. Side-aware labels: the
      batter card reads "vs LHP / vs RHP" (filtered on opposing
      pitcher's `throws`); the pitcher card reads "vs LHB / vs
      RHB" (filtered on the *effective* batter hand). Switch-
      hitters (`bats=3`) bat opposite the pitcher's throwing hand;
      that resolution is in the SQL CASE expression.

    Implementation:
    - SQL: 4 new UNION ALL branches in `_SITUATIONAL_QUERY_TEMPLATE`,
      plus two LEFT JOINs to `players_current` (one for batter, one
      for pitcher) to derive `pitcher_throw_hand` and
      `effective_bat_hand`. The hand-derivation CASE handles
      switch-hitters cleanly: `bats=3` → opposite of pitcher's
      throwing hand.
    - Side-aware label resolution moved out of the simple dict
      lookup into `_split_label_for(split, side)` — shared labels
      for the leverage cluster, side-specific for the platoon split.
    - Display order updated: leverage (risp / 2-out / late&close) →
      bases (empty / loaded) → platoon (vs L / vs R).

    Verified end-to-end:
    - Sanity invariants hold: `bases_empty + (bases-with-runners)
      = all`; `vs_left + vs_right = all` when handedness fully
      populated. Devers 2029: 162 vs LHP + 474 vs RHP = 636 (=All).
    - Switch-hitter test: Leo De Vries 2029 (697 PA, `bats=3`) →
      184 vs LHP / 513 vs RHP, summing to 697. The hand-derivation
      routes switch hitters correctly.
    - Devers 2029: bases-loaded **1.418 OPS** in 15 PA (small but
      tasty); textbook platoon — LHB does better vs RHP (.788) than
      vs LHP (.746).
    - Crochet 2029: vs LHB **.561 OPS allowed** (LHP-vs-LHB
      dominance), vs RHB .697 (typical platoon disadvantage); bases
      loaded .429 (locked in with bases full).

23. ✅ **Counts + spray splits** — done 2026-05-12. Extended the
    situational sections from 8 splits to **14** per (year, level).
    Three new clusters added on top of the existing leverage / bases /
    platoon clusters:
    - **Counts** — `first_pitch` (0-0 result; PA resolved on pitch 1),
      `two_strike` (strikes=2 when resolved), `full_count` (3-2 when
      resolved). Read off `f_pa_event.balls`/`strikes` which carry the
      count BEFORE the resolving pitch.
    - **Spray** — `pull`, `center`, `oppo`. Filtered to BIP only;
      AVG within these splits = hits-per-BIP (BABIP-with-HR);
      OBP collapses to AVG (BB/HBP excluded). UI skips OPS-vs-baseline
      color coding for spray since the denominator semantics differ.

    **Empirical finding** along the way: `hit_xy` is **batter-relative**,
    not field-absolute. Verified by computing mean `hit_xy` on HRs by
    bat hand at MLB-2029: LHB mean ≈73, RHB mean ≈71 — same pull-side
    band for both hands. If hit_xy were field-absolute the means would
    diverge. Updated the spray rule to be hand-INDEPENDENT
    (`x ≤ 5` → pull, `6..9` → center, `x ≥ 10` → oppo, applied to both
    L and R uniformly) and corrected the DATA_NOTES "Low = LF-side"
    claim.

    Verified: Devers 2029 spray reads correctly — Pull 12 HR (1.183
    OPS), Center 15 HR (1.190 OPS), Oppo 0 HR (.566 OPS); 12+15+0=27
    total HRs. Counts: First pitch .725, Two strikes .585 (drops
    sharply), Full count .820 (recovers). Crochet 2029 allowed-spray
    shows pull-side damage (.715 SLG-allowed pull, 13 HR allowed pull;
    0 HR allowed oppo).

24. **`/history/records`** ✅ (2026-05-12) — first stub on the
    `/history` tab drained. `GET /api/records?scope=&discipline=
    &category=&era=` UNIONs save + Lahman 1871-2019 + BREF 2020-2025
    + merged career rollups + Statcast 2015-2025. Three flat picker
    rows (Scope / Discipline / Era) + a Category strip dynamically
    populated from `f_record_player`. Source chips color-coded per
    source (emerald=save, indigo=lahman, sky=bref, violet=merged,
    amber=statcast); names link to `/player/<id>` when the row carries
    a save player_id. Server re-ranks globally when era=all so save
    + lahman duplicates sit adjacent (Bonds 73 / 73, McGwire 70 / 70)
    — confirms OOTP imports Lahman exactly. Bad query strings fall
    back to defaults rather than 404'ing (deep-linked URLs stay alive).
25. **`/history/awards`** ✅ (2026-05-12) — second stub on the
    `/history` tab drained. `GET /api/awards?league_id=&award_id=&era=`
    returns career trophy-count holders for any (league × award)
    with optional era filter (all / save / real). Three flat picker
    rows: League grouped by tier (MLB / AAA / AA / etc.), Award
    flat strip ordered by prestige (MVP / Cy / RoY / GG / SS /
    Reliever / All-Star / WSC / Series MVP / monthly noise), Era
    filter shown only when multiple sources exist for the chosen
    award. Spot-check: Ohtani 7 / Bonds 7 MVPs at the top, Roger
    Clemens 7 Cy Young, Maddux 18 GG, Brooks Robinson 16 GG —
    canonical real-life values, surfaced because OOTP imports them
    as save data. Era=real cleanly isolates Yadier Molina 9 GG /
    R.A. Dickey 1 Cy / etc. (retired players whose bbref_ids didn't
    match save players).
26. **`/history/hof` + `/history/streaks`** ✅ (2026-05-12) — third
    and fourth stubs on the `/history` tab drained in one slice.
    HoF: `GET /api/hof?view=&limit=` returns either Inductees (285
    players flagged `hall_of_fame=1`, ordered by induction year) or
    Candidates (top-25 career WAR who aren't yet inducted). Both
    views share the same `HofPlayer` row shape; toggle is a simple
    pill with count hints. Marquee non-inducted: Bonds 146.6 /
    Clemens 142.6 / Pete Rose 123.0 / A-Rod 120.6 — canonical
    "should be in but aren't" list. Streaks: `GET /api/streaks?
    streak_id=&scope=` returns the L3-pre-cut top-50 holders for
    21 streak types × 2 scopes (active | all_time). Hitting streak
    all-time top: Charlie Szykowny 56 games (DiMaggio mark). Active
    streaks render a "Live" badge instead of an end date. Both
    pages reuse the records / awards picker pattern.
27. **`/history/draft`** ✅ (2026-05-12) — last stub on the History
    tab drained. `GET /api/draft?year=` returns the entire draft
    class (~600 picks) for one year, grouped by outcome bucket
    (MLB Regulars → Callups → Still Developing → Traded → Released
    → Retired). Year picker strip; default resolves to oldest
    year with material outcome variation (2026 in this save —
    fresh classes have ~570 in_draft_org rows which is a boring
    page). Class summary header shows total picks + reach-MLB% +
    color-coded outcome chips. 2026 spotlights: Cholowsky 1.1
    Cubs (2.8 WAR), Lackey 1.3 Twins→ATL (1.7 WAR), Skelton
    Sox 4.124 (3.6 WAR — sweet 4th-round find), Jackson Flora
    1.12 LAA (4.4 WAR — best of class).
28. **History tab fully drained** as of 2026-05-12 — all five
    sections (Records / Awards / HoF / Streaks / Draft) live.
    Tab graduated from stub to fully-content section.
29. **Visual upgrade — heat-scale + Sparkline + CareerArc + Cockpit
    v2** ✅ (2026-05-12). Three slices in one push:
    a. **Heat-scale utility** (`web/lib/heatscale.ts`) — central
       `plusMinusClass` + `warSeasonClass` color functions with
       five-tier gradients per side, bg fills at the extremes
       (≥160 / ≤40 OPS+, ≥8 / ≤-2 WAR). Applied uniformly to
       roster Advanced columns + player-page Advanced section +
       pressure board metric. The eye now jumps to MVP-tier rows
       and replacement-level red flags without hunting.
    b. **Sparkline + CareerArc components** — pure inline SVG, no
       chart lib added. Sparkline (~120 lines) is a tiny trend line
       with auto-trend coloring; reusable on cockpit cards + future
       leaderboard rows. CareerArc (~250 lines) is a season-by-year
       line chart with WAR-magnitude dot fills, peak-tier reference
       band, year-axis ticks; sits between bio header and tab strip
       on `/player/[id]`. Bonds 2001 spike, Trout's flat plateau,
       Skubal's ascending arc — all visible at a glance.
    c. **Cockpit v2** at `/` — replaces the old tools-grid landing.
       `GET /api/cockpit` composes Sox AL East standings + top-3
       MLB promotion / pressure pairs + 6 spotlight cards (each with
       inline career-WAR sparkline + auto-generated NLG insight
       like "Bounceback — 149 after 90 in 2028" for Suarez or
       "Off year — 127 down from 186 peak" for Crochet) + last 8
       movement-ledger rows. One round-trip; year is implicit
       (latest); historical views stay on dedicated tabs. The
       Sox 93-69 division-leader status is the page's first paint.
30. **Pressure board** ✅ (2026-05-12) — `/pressure` lives.
    `GET /api/pressure?year=&limit=` returns per-level promotion
    candidates + pressure cases for the org tree. For each level
    in the pipeline (MLB / AAA / AA / A+ / A / Rk / DSL), the
    strongest performers (by OPS+ for batters, ERA+ for pitchers)
    sit in the left column; the weakest in the right. Pattern-match
    across levels: 130 OPS+ at AAA next to 75 OPS+ at MLB =
    obvious roster decision. 2029 spotlights: Caleb Durbin 183
    OPS+ at AAA vs his own 97 at MLB ("stop yo-yo'ing him");
    Carlos Narvaez 75 / Roman Anthony 94 / Langeliers 94 as MLB
    pressure; Garcia 130 / Rodriguez 129 / White 127 as AAA
    promotion candidates. Sample bars: 50 PA / 20 IP. Org scope
    auto-derived from `audit_team_id` (no client filter needed).
31. **Salary stream** ✅ (2026-05-12) — Contract section on player
    page. `PlayerContract` Pydantic schema flows from the L1
    `contract_current` view; resolves option years (team / player /
    vesting), buyouts, opt-out clauses, no-trade flags. Renders as
    a CSS-bar chart with one column per year, current-year highlight,
    option badges (TO / PO / VO) below the year label. Total +
    remaining USD totals in the header. Crochet 7y/$185M (curr year
    4 of 7, opt-out 2030, $5M buyout on 2032 TO); Henderson 8y/$388.5M
    no-trade (just signed); Judge 9y/$360M (curr year 7).
32. **Compare under Explore** ✅ (2026-05-12) — `/explore/compare?ids=`
    renders up to 4 players side-by-side. `GET /api/compare?ids=`
    returns slim cards (career batting/pitching lines + WAR sparkline
    series + headline metric) — slim by design; ≤4 cap for legibility.
    Empty state surfaces three demo deep-links (Bonds·Aaron·Ruth,
    Trout·Ohtani·Judge, Pedro·Maddux·Clemens). Cross-era is fair
    game thanks to D20 baselines.
33. **Player headshots** ✅ (2026-05-12) — `PlayerAvatar` component
    streams `news/html/images/person_pictures/player_{id}.png` from
    the active save via `GET /api/photos/players/{id}.png`. Per-image
    onError fallback to a deterministic-color initials disc keeps
    layouts stable when OOTP didn't generate a face (most pre-1990
    real-history players). Sizes xs/sm/md/lg; wired into player page
    header (lg), cockpit spotlight cards (sm), roster name cells
    (xs), compare cards (md).
34. **Next slice candidates**:
    a. **Custom leaderboards** under Explore — Fangraphs-style
       sortable + filterable. TanStack Table integration; filter
       strip across year / level / age / min-PA / position; columns
       drawn from the data dictionary; save-to-URL.
    b. **Spray charts + EV-LA scatter** under Explore — forces the
       chart-stack decision (Vega-Lite vs Plotly). Once chosen,
       half a dozen viz slices unlock.
    c. **Historical park factors** (D20 follow-on) — fix pre-2026
       OPS+/ERA+ to use the team's actual contemporary park
       factor instead of the modern-stadium proxy.
    d. **AI overlay** (D14) — keyring-stored keys, four-tier use
       levels, daily-cap auto-degrade.
    e. **Setup wizard** (D3 v2 hard requirement) — first-launch
       save-setup picker.

**Open audit carry-forwards** (non-blocking, picked up opportunistically):
multi-level OPS+/ERA+ park weighting, hit_loc-based spray, LeaderCategory codes
44 + 49, trade_history `<entity:type#id>` summary parsing, personality
archetype "Type", All-Star teams 2020-2025 (Lahman caps at 2019, MLB API
doesn't expose annual rosters cleanly). All in BACKLOG.md.

**Smaller follow-ons in the analytical layer** — closed 2026-05-07:
- ✅ Pitching Statcast records — UNION'd via `direction='asc'` for rate stats.
- ✅ Save-side EV records — joined via `f_pa_event`, calibration documented.
- ✅ Awards UNION dedup — Lahman+mlbapi collapsed into `merged` via bbref_id.

All-Star teams 2020-2025 gap remains noted in BACKLOG.md (Lahman caps at
2019; MLB Stats API doesn't expose annual rosters cleanly — separate research
item if surfacing real-life All-Star streaks ever becomes important).
