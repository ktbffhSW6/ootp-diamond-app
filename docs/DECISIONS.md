# Decisions Log

> Architectural, scope, and design decisions with their rationale. Append-only
> history — when a decision is reversed, add a new entry rather than editing
> the old one. Each entry: **date**, **decision**, **why**, **alternatives
> considered**.

---

## D1 — Stack: Python 3.14 + DuckDB + Polars + Typer

**Date**: 2026-05-02
**Decision**: Build Diamond on Python 3 with DuckDB as the warehouse engine, Polars for ingest, Typer for the CLI, Rich for console output.
**Why**: DuckDB handles 100MB CSVs and 5M+ at-bats trivially, gives us SQL natively, runs as a single file portable across machines, and supports `ATTACH` for cross-save analysis later. Polars is fast on the ingest hot path. Typer + Rich give us an ergonomic CLI without web infrastructure overhead.
**Alternatives considered**: Postgres + SQLAlchemy (too much overhead for v1; can layer later if a multi-user web UI becomes needed). SQLite (DuckDB is purpose-built for OLAP/analytics workloads on this data shape).

## D2 — One DuckDB per OOTP save (not a shared multi-save DB)

**Date**: 2026-05-02
**Decision**: Each OOTP save gets its own DuckDB file in `<save>/diamond/diamond.duckdb`, alongside the `dump/` and `import_export/` folders OOTP itself writes.
**Why**: Clean isolation, no `save_id` FK pollution everywhere, each save is fully portable. Cross-save analysis still works via DuckDB's `ATTACH`.
**Alternatives considered**: Single shared DB with `save_id` on every table.

## D3 — Strict league scope for v1, with save-setup picker as a hard v2 requirement

**Date**: 2026-05-02
**Decision**: For "Building the Green Monster" (v1), hardcode scope to MLB + affiliated minors + DSL + AFL (15 league_ids). v2 must include a save-setup UI that scans the earliest dump's `leagues.csv` and lets the user pick.
**Why**: User's current focus is the Red Sox franchise — strict scope cuts ingest volume dramatically (10-20K relevant players vs 148K world). Future saves may include foreign leagues / KBO / indy / fictional leagues, so the scoping mechanism must be configurable, not hardcoded.
**Alternatives considered**: World-wide ingest with query-time filtering (more flexible but ~10× the storage and more I/O on every analysis).

## D4 — Strict player scope (configurable per save)

**Date**: 2026-05-02
**Decision**: Only ingest players who appear in scoped leagues. Once in scope, stay in scope through retirement (so we don't lose franchise narrative if a Red Sox prospect later signs in KBO).
**Why**: Avoids ingesting stats for 148K world-wide players when most are irrelevant. Keeping in-scope-once players forever preserves storyline continuity.
**Alternatives considered**: World-bio-only mode (ingest all player bios, only stats for scoped players) — kept as a future option.

## D5 — Skip plate-discipline metrics (Z%, SW%, RV-*)

**Date**: 2026-05-02
**Decision**: Don't attempt to replicate Z%, SW%, ZC%, OC%, ZS%, OS%, CL%, WH%, CH%, CTC%, FF%, BR%, OFF%, RV-FB, RV-BR, RV-OFF, RV from the import_export files.
**Why**: These need per-pitch zone/type data that OOTP never exports. Only the per-PA terminal `balls`/`strikes` count is in the dump. Approximation would be lossy and misleading.
**Alternatives considered**: Pull from `import_export` when the user generates it for their own org (Red Sox-only at present), null elsewhere — rejected for simplicity in v1.

## D6 — Player ratings on the 20-80 scouting scale

**Date**: 2026-05-02
**Decision**: All player ratings and potentials surfaced in our app are on the 20-80 scale.
**Why**: User preference; matches Baseball America / Fangraphs convention.
**How to apply**: For skill ratings (CON, GAP, POW, EYE, etc.), the dump's `players_scouted_ratings` columns are already on 20-80 — pass through directly. For OVR/POT, use `overall_rating` / `talent_rating` (already 20-80) — NOT `overall` / `talent` (which are on a 0-200 internal scale).

## D7 — Granular at-bat data as primary source for stat derivations

**Date**: 2026-05-02
**Decision**: Where possible, derive stats from `players_at_bat_batting_stats.csv` (per-PA event log) rather than from career-stats season rollups.
**Why**: Enables custom time-frame queries ("last 12 games", "last 45 games", "RISP performance over the last month") and any situational split a user wants. Career-stats become a validation target, not the primary source.
**How to apply**: Capture at-bat data from the `dump_YYYY_11` end-of-season snapshot (the file rolls over at season start in Feb-Mar). For multi-year analysis, stitch together the November dumps from each year.

## D8 — Reconciliation harness as a permanent codebase fixture

**Date**: 2026-05-02
**Decision**: Keep `src/diamond/audit/reconcile.py` permanently — run it after every monthly ingest as a regression check.
**Why**: Without continuous reconciliation against the OOTP-generated `import_export` files, derivation drift would be silent. Every column we derive must have a corresponding view that ties back to OOTP's own numbers.
**Alternatives considered**: Throwaway audit script — rejected because we need ongoing regression coverage.

## D9 — Persistent docs/ logs replace session-scoped TodoWrite

**Date**: 2026-05-02
**Decision**: Project context lives in `docs/PROJECT_STATUS.md`, `docs/DECISIONS.md`, `docs/DATA_NOTES.md`, `docs/BACKLOG.md`. These are committed to the repo and updated as work progresses.
**Why**: TodoWrite is session-scoped and not visible to the user. Long-running engineering project across many sessions needs a persistent, version-controlled record of state, decisions, and discoveries.
**How to apply**: Read PROJECT_STATUS at session start. Append to DECISIONS / DATA_NOTES as new ones emerge. Keep BACKLOG current.

## D10 — Audit-first: complete reconciliation before any schema/ingest design

**Date**: 2026-05-02
**Decision**: Finish the full audit phase (all 21 import_export files reconciled, all integer codebooks decoded, all data quirks documented) BEFORE designing the warehouse schema or building the ingest pipeline. No schema/DDL work begins until reconciliation is comprehensive.
**Why**: User explicit instruction — "Let's make sure that the data scope is crystal clear and we have everything reconciled before we start building anything including schema." Schema decisions baked in before reconciliation can lock in the wrong assumptions; the cost of a redesign once tables exist (and contain data from 44 monthly dumps) is much higher than finishing the audit.
**How to apply**: Resist the temptation to start schema work even when "we have enough proof now that derivations work." Direct any schema design ideas to BACKLOG instead. Continue audit work in priority order: reconcile remaining 16 import_export files → DEF formula → rounding edges → AS gap → trade summary parsing.

## D11 — League constants: per-league per-level, no AL/NL split, separate per international league

**Date**: 2026-05-04
**Decision**: League constants for sabermetric stats (wRC+, wRAA, FIP, OPS+, ERA+, etc.) are keyed on `(league_id, year, level_id)`. Within US MLB, AL and NL are aggregated into a single MLB row (no split). International leagues at the same nominal level (NPB, KBO, KFL at MLB-equivalent level) live in their own constants universes and are never aggregated with US MLB. Cross-level aggregation for a single player is never done — a player who splits a season between MLB and AAA shows two stat lines (one per level), each with sabermetrics computed against that level's constants. Only pure counting stats (career HR, total IP) can be summed across levels for rollups.
**Why**: Mimics modern public-stats convention (Fangraphs, Baseball Reference for the modern era): one MLB-wide league baseline, level-specific context for non-MLB players, and per-league-line stats for cross-level players. Empirically verified the AL/NL choice is a no-op in this save (universal DH since 2022 → AL OBP=.3155 vs NL OBP=.3151, OPS+ comes out identical to the integer either way), so we take the simpler/cleaner unified-MLB convention. Treating international leagues as separate universes prevents nonsensical comparisons (a Hanshin Tigers player's wRC+ being compared to Aaron Judge's).
**How to apply**:
- The `league_constants` table is keyed `(league_id, year, level_id)`. For OOTP MLB (`league_id=203`), aggregate across the per-sub_league rows (the dump stores AL and NL as separate rows with `team_id=12` and `team_id=25` respectively in `league_history_*_stats`).
- For NPB / KBO / KFL etc., each `league_id` keeps its own constants — no cross-league aggregation.
- Sabermetric derivations join `players_career_*_stats` to `league_constants` on `(level_id, year)` per row (and league_id for international), so a player's MLB rows use MLB constants and his AAA rows use AAA constants automatically.
- Career rollups across levels are restricted to pure counts (HR, IP, games). Rate-context stats (wRC+, ERA+, etc.) are reported per-level only.
- MLB-equivalent translations (e.g., AAA→MLB conversion factors à la KATOH/Davenport) are explicitly **out of scope** for the constants module — they're a separate analysis-layer transformation that consumers can apply if desired.
**Alternatives considered**:
- AL/NL split per BBR convention — rejected because empirically no-op in this save and adds complexity without precision gain.
- Aggregate international leagues with US-MLB at the same level_id — rejected because the run environments are unrelated; would distort everyone.
- Compute one season-aggregate sabermetric across a player's mixed-level rows — rejected because the underlying scales differ between levels (AAA wOBA scale ≠ MLB wOBA scale), making the aggregate statistically meaningless.

## D12 — Scouted ratings only; never expose objective ratings

**Date**: 2026-05-05
**Decision**: Diamond surfaces only the **user's-org-scouted** view of player ratings (`players_scouted_ratings.csv` filtered to `scouting_team_id = <user's MLB team_id>`, which is `4` for the Red Sox in "Building the Green Monster"). The objective/true ratings — available in the dump as `scouting_team_id = 0` rows in the same file — are **explicitly not exposed** anywhere in the product: not in derived tables, not in views, not in CLI output, not in any future UI.
**Why**: OOTP's scouting-accuracy mechanic is a load-bearing piece of the GM experience. The whole reason the Sox might rate a prospect's contact tool at 30 while the truth is 35 is that scouting is imperfect — and acting on that imperfect view *is the game*. A tool that quietly reveals the true rating would let the user metagame their own save: trade away players the system says are overrated, draft players the system says are underrated, etc. That collapses the franchise simulation into a cheat sheet. Diamond is built to deepen the GM experience, not undercut it.
**How to apply**:
- Every rating-bearing query, view, or table joins `players_scouted_ratings` with the WHERE clause `scouting_team_id = <user_org_team_id>`. No exceptions.
- The user-org team_id lives in `SaveConfig` (currently hardcoded `BOSTON_MLB_TEAM = 4`; v2 save-setup picker per D3 must include selecting the user's MLB org).
- The L1 ingest pipeline must NOT load `scouting_team_id = 0` rows from `players_scouted_ratings.csv` — drop them at the L0→L1 boundary so they can't be reached by accident. (L0 keeps everything per provenance, but no L1+ table or view filters in team_id=0.)
- A linter / reconciliation check should grep the codebase for `scouting_team_id = 0` and `scouting_team_id=0` and fail if found outside the L0→L1 filter itself.
**Alternatives considered**:
- Expose both views with a "show truth" toggle — rejected. Trivially easy to leave on, defeats the purpose, and once the truth is in the UI it's hard to un-see even if hidden again.
- Default to scouted, expose objective behind a `--cheat` flag — rejected. Same problem at lower friction.
- Use `team_id = 0` as a fallback when the user's scouts haven't graded a player — rejected. The dump's `team_id = 4` rows already cover all 18,130 scoped players; there is no gap to fill, and "the scout doesn't have an opinion" is itself meaningful information that shouldn't be silently substituted.

## D13 — Two-tier player scope (org + reference)

**Date**: 2026-05-05 (implemented 2026-05-07; cohort definition refined)
**Decision**: Player scope splits into two distinct populations:
- **Org scope** (the existing D4 rule): players who have ever appeared on a team in `SaveConfig.league_ids`. Powers cockpit, demotion/promotion tool, day-to-day org views.
- **Reference scope** (new): any player with **≥1 career MLB appearance** — either a batting PA or pitching outs at level_id=1. Includes Hall of Famers, historical legends OOTP imports, current-era stars on other orgs. Empirical sizing on "Building the Green Monster" 2026-05-07: 15,992 org-tier players → 35,261 with reference scope on (+19,269 net new), matching D13's 30-50K-total estimate. Cohort definition was refined from the original "≥1 career MLB PA" to "PA OR pitching outs ≥1" because universal-DH-era pitchers may never bat (3,022 such pitchers in this save would have been wrongly excluded under a strict PA gate).

**Opt-in per save**: `SaveConfig.reference_scope_enabled: bool` defaults `False`. When `True`, the L1 `_scoped_players` builder UNIONs the org-scope set with the MLB-PA set. UI surfaces (cockpit, leaderboards) default to org-scope; chart builder / universes / glossary distribution histograms can opt into reference scope when meaningful (e.g., "compare Mike Trout to every batting Hall of Famer").

**No cross-save analysis**: DuckDB `ATTACH` remains technically possible for power users to run cross-save queries by hand, but Diamond does not expose this as a product feature. Each save is self-contained.

**Why**: Two real user needs:
1. *Day-to-day GM cockpit* (org scope) — fast, focused, free of clutter from players the user doesn't care about. The current scope works perfectly here.
2. *Cross-era / cross-org analytical comparisons* (reference scope) — "where does my prospect's age-22 wRC+ rank against every age-22 HoF batter?" / "is my closer's K/9 elite by historical standards?" — questions the public-stats sites answer trivially but our org-only warehouse couldn't.

The ≥1 MLB PA cutoff keeps the population manageable (~30K rather than ~150K worldwide-bio) while including everyone of analytical interest. Per-save opt-in keeps the cost zero for users who don't need it.

**How to apply** (implemented 2026-05-07):
- `_scoped_players` builder in `src/diamond/schema/l1_machinery.py` accepts `save.reference_scope_enabled`. When True, the CTAS `UNION`s the org-tier base set with two cohorts pulled directly from L0 (no L2 dependency):
  ```sql
  -- org-tier (always)
  SELECT DISTINCT player_id FROM l0_players
  WHERE team_id IN (SELECT team_id FROM _scoped_teams)
  UNION  -- reference-tier batting cohort
  SELECT DISTINCT player_id FROM l0_players_career_batting_stats
  WHERE level_id = 1 AND split_id = 1 AND pa >= 1
  UNION  -- reference-tier pitching cohort (covers DH-era relief pitchers)
  SELECT DISTINCT player_id FROM l0_players_career_pitching_stats
  WHERE level_id = 1 AND split_id = 1 AND outs >= 1
  ```
  Querying L0 directly (rather than L2 `f_player_season_batting`) avoids the L1→L2→L1 dependency flip the original design called out.
- CLI: `diamond ingest --reference-scope` / `--no-reference-scope` toggles + persists in the warehouse `_diamond_settings` table; absent flag uses the previously-persisted value (defaulting False on first run).
- New admin table `_diamond_settings (key, value, updated_at)` provides forward-compatible per-save flag storage. Helpers: `get_setting / set_setting / get_reference_scope_enabled / set_reference_scope_enabled` in `diamond.schema.build`.
- Smoke test exercises both modes: rebuilds machinery with reference scope on, verifies the expansion strictly grows the player set + every reference-only player has ≥1 MLB appearance, then resets to org-only baseline for downstream phases.
- Setup wizard step 4 (future Phase 3 work) will surface the toggle per save in UI form.
- Tracked-saves registry persistence (future Phase 3 work) will move per-save settings to a user-level registry alongside the warehouse-local `_diamond_settings` table.

**Alternatives considered**:
- *No reference scope, ever* — rejected once user surfaced the "Trout vs HoF" use case; the analytical value is real and the cost is small.
- *Always-on reference scope* — rejected as overhead for users who only want org analytics.
- *Whole-world scope (every player ever)* — rejected as too much disk/query cost for too little additional analytical value past the MLB-PA cutoff.

## D14 — AI overlay architecture (keyring, pluggable providers, four-tier use levels)

**Date**: 2026-05-05
**Decision**: Diamond's AI features run through a platform-agnostic adapter layer with the following commitments:

- **Keys live in the OS keyring** (Windows Credential Manager / macOS Keychain / Linux Secret Service via the `keyring` Python library). Never written to disk in plaintext. Never logged. Encrypted-file fallback only when no OS keyring is available, behind a master password.
- **Pluggable provider adapters**: a thin `AIClient` interface with concrete adapters per provider (`AnthropicClient`, `OpenAIClient`, `GeminiClient`, `OllamaClient`). Adding a provider = drop in one ~80-line file + register in the settings UI. No vendor lock-in.
- **Pricing data via OpenRouter** live fetch (their model catalog has ~200 models with current prices), with a hand-maintained `pricing.toml` fallback for offline operation.
- **Per-call cost estimation** before any AI invocation. Uses provider tokenizer (tiktoken / Anthropic SDK / etc.) on the prompt + per-feature typical-output-length estimates. Visible as inline "✨ Generate (~$0.04)" badges and "🪙 $0.42 today (8% of cap)" cockpit footer.
- **Four AI use levels** (global default with per-feature override):
  - **Off** — all AI hidden, no API calls
  - **On-demand** — user clicks each AI feature; cost preview before every call
  - **Smart** *(default for new users)* — auto-runs cheap inline features (chart annotations, percentile cards, anomaly flags); prompts before expensive features (monthly review, deep dossier)
  - **Always-on** — auto-runs everything, including expensive features
- **Daily-cap auto-degrade**: at 80% of cap, auto-features turn off; at 100%, all AI features pause until midnight reset. User-set cap, defaults to $5.

**Why**:
- Platform-agnostic from day one because OOTP users span Anthropic / OpenAI / Google / Ollama preferences, and locking to one provider creates an avoidable friction. The adapter pattern is cheap (~80 lines per provider).
- Keyring storage because API keys are credentials; they must be protected at rest. The `keyring` library handles this cross-platform with no additional code.
- OpenRouter pricing because hand-maintaining a pricing TOML with ~200 models that update monthly is a maintenance burden we shouldn't take on; OpenRouter does it for us as a free public service.
- Four use levels because the gap between "click every time" and "auto-everything" is wide and most users want a middle ground. Smart-tier explicitly classifies features into "inline auto-runs" vs "deep on-demand" so users know what to expect. The classification is per-feature, not per-call.
- Daily cap auto-degrade because surprise AI bills are the #1 reason users distrust AI features in tools like this.

**How to apply**:
- Module layout:
  ```
  diamond/ai/
    settings.py    (load/save settings.toml + keyring access)
    pricing.py     (token costing, openrouter refresh, pricing.toml fallback)
    usage.py       (~/.diamond/usage.duckdb writer/reader)
    client.py      (AIClient interface)
    adapters/anthropic.py / openai.py / gemini.py / ollama.py
  ```
- Settings live at `~/.diamond/settings.toml` (non-secret) + OS keyring (secrets) + `~/.diamond/usage.duckdb` (cost log).
- A "use level" classifier helper decides at runtime whether to invoke AI for a given feature based on the current global+per-feature settings.

**Alternatives considered**:
- *Hardcoded single provider (e.g., Anthropic-only)* — rejected; locks in vendor choice and fails users with provider preferences.
- *Plaintext keys in config file* — rejected; security-irresponsible.
- *Three use levels (Off / Manual / Auto)* — rejected; the gap between Manual and Auto is too wide for new users to navigate. Smart-tier is the unlock.
- *No daily cap* — rejected; surprise-bill risk is real, especially with Always-on tier.

## D15 — Stat dictionary as single source of truth

**Date**: 2026-05-05 (initial v1 implementation 2026-05-07; thin dictionary, ~35 entries)
**Decision**: Every stat reference in Diamond — column headers, chart axis labels, AI prompts, glossary pages, narrative reports — reads from a single canonical Python module: `diamond/dictionary/`. One `Stat` dataclass instance per metric, ~150 entries total covering every L0/L1/L2/L3 column we surface.

Each entry carries: `id`, `display_name`, `short_label`, `category`, `formula_tex` (KaTeX-renderable), `formula_plain` (text fallback), `description`, `units`, `typical_range`, `interpretation`, `caveats`, `source` (warehouse path), `formula_source` (provenance), `related` (list of related stat ids), `refs` (links to Fangraphs / BR / Savant external glossaries).

**Why**: Without a single source of truth, the same stat ends up labeled three different ways across the app (Fangraphs `wOBA`, our internal `WOBA`, the column header `Weighted On-Base Avg`), formulas drift between code comments and display tooltips, and AI prompts hallucinate definitions because they can't ground in the app's actual implementation. The dictionary makes definitions data, not literature, and makes them queryable, versionable, and AI-injectable.

**How to apply**:
- `diamond/dictionary/__init__.py` defines `Stat` dataclass and exports `STATS: dict[str, Stat]`.
- All UI surfaces (table column components, chart axis labels, glossary page) read `STATS[stat_id]` instead of hand-writing labels and formulas.
- AI prompt builders inject relevant stat definitions into the AI context window.
- Existing formulas in `reconcile.py` `ColSpec.notes`, `advanced/*.py` docstrings, `DATA_NOTES.md`, and `constants.py` get **consolidated** (not duplicated) into the dictionary; downstream code references dictionary IDs.
- The `/glossary` route renders one URL per stat (`/glossary/wOBA`); hover tooltips on column headers lazy-fetch the same data.
- Math rendering: KaTeX (lightweight, ~50KB, plays well with React).

**Alternatives considered**:
- *Per-module ad-hoc stat metadata (status quo)* — rejected; produces drift, inconsistent labels, AI grounding gaps.
- *Markdown glossary file as source of truth* — rejected; not queryable from runtime UI without a parser, harder to type-check, no programmatic access for AI prompts.
- *External SaaS like Fangraphs glossary as the source of truth* — rejected; their formulas may differ from ours (e.g., park-halving conventions), and we'd take a runtime dependency on someone else's site.

**Maintenance**: dictionary entries are append-only by default. Adding a new stat = add an entry. Changing a formula = update the entry AND the code that computes it (cross-reference enforced by `Stat.source` field pointing to the implementation).

**Implementation status (2026-05-07)**:
- `src/diamond/dictionary/__init__.py` — `Stat` frozen dataclass + `CATEGORIES` tuple + `STATS` dict aggregator. Category validated at instantiation via `__post_init__`.
- `src/diamond/dictionary/_stats.py` — entries grouped by category in source for readability; consumers index by `id`. Dataclass instantiation enforces unique ids.
- `src/diamond/glossary.py` + `diamond glossary` CLI — terminal + markdown rendering. Three modes: list-all (default), `glossary <id>` for full detail, `--category <cat>` for compact one-category table. Validates the dictionary works end-to-end before any frontend exists.
- Smoke test Phase G — required-fields-non-empty + categories valid + related ids resolve + ids unique.

**Thin v1 cohort (39 entries shipped 2026-05-07)**:
- batting (15): AVG / OBP / SLG / OPS / ISO / BABIP / K%/BB% / PA / HR / RBI / R / BB / K / SB
- advanced (8): wOBA / wRAA / wRC / wRC+ / OPS+ / ERA+ / FIP / SIERA
- pitching (6): W / SV / IP / K / ERA / WHIP
- value (3): WAR (OOTP) / oWAR / pit_WAR
- statcast (5): MAX_EV / AVG_EV / HARD_HIT_PCT / BARREL_PCT / SWEET_SPOT_PCT
- fielding (2): RF/9 / Framing+

**Player-page expansion (60 entries — landed alongside Stats tab 2026-05-07)**:
- batting +5: G_batter / AB / H / D (2B) / T (3B)
- pitching +8: L / G_pitcher / GS / ER / H_allowed / R_allowed / HR_allowed / BB_allowed
- fielding +8: G_fielder / GS_fielder / INN / PO / A / E / DP / FPCT

The expansion landed in lockstep with the player Stats tab so every column header rendered on `/player/[id]` had a backing entry from day one. Pitcher/batter homonyms (G, K, BB, HR) carry separate ids with `_pitcher` / `_batter` / `_allowed` suffixes — same `short_label`, different conceptual stat (e.g., `HR` is HRs hit, `HR_allowed` is HRs given up).

**Long-tail entries** (~90 more) land here as UI screens reach for them. Strict rule: any new UI label, chart axis, or AI prompt MUST come from the dictionary — no hand-coded labels in feature code. Dictionary fills in over time but never lags behind what's exposed.

## D16 — Tech stack: FastAPI + Next.js (App Router), Pydantic-derived TS types

**Date**: 2026-05-07
**Decision**: Diamond's UI ships as a two-process local-first app:
- **Backend**: FastAPI (Python) serving a typed HTTP API. Talks directly to the per-save DuckDB warehouse (D2), reuses every existing `src/diamond/` module (records / awards / hof / streaks / glossary / advanced / etc.) as the data layer.
- **Frontend**: Next.js (App Router) on TypeScript + React. Renders every UI surface in UI_DESIGN.md.
- **Bridge**: Pydantic models on the backend are the single source of truth for API shapes; TypeScript interfaces are auto-generated from them so the two layers can never drift on field names or types.

**Why** (full breakdown lives in the 2026-05-07 chat thread):
- The 8-area design in UI_DESIGN.md (Bref-shaped player page with sticky tabs + dual rail, Fangraphs-style sortable filter strips with URL state, universes with set-ops, chart builder with template gallery, AI overlay with inline cost previews, KaTeX-rendered glossary) needs full HTML/CSS layout control + the React component model. Streamlit and Dash hit hard layout/composition ceilings on at least 3 of the 8 areas; Tauri+Vue/Svelte gets to the same ceiling as Next.js but adds a Rust+JS+Python three-layer build for desktop integration Diamond doesn't need.
- Every chart/math primitive Diamond requires (Vega-Lite, Plotly WebGL fallback at >50K points, KaTeX) is React-native — no bridging.
- Pydantic→TS types eliminates the most common "two codebases drift" pain point. The dictionary's `Stat` dataclass becomes a `Stat` TS interface for free.
- Future paths stay open: web-share via Vercel deploy, mobile read view from same codebase, hypothetical hosted multi-tenant version is just adding auth. Streamlit/Dash close those doors; Tauri closes the web/mobile door.
- Setup cost is real (~1-2 days yak-shaving before the first page renders) but it's a one-time tax that pays back across every subsequent UI page. By week 2 Streamlit's "fast to start" advantage evaporates anyway, since custom React components are required to escape its layout primitives.

**Alternatives considered**:
- *Streamlit* — rejected. Single-Python-codebase fast-iteration wins evaporate on the bespoke pages (player, chart builder, AI overlay). Re-runs-the-script-on-every-interaction model fights the dense interactive layouts.
- *Tauri + Vue/Svelte* — rejected. Same browser-tech ceiling as Next.js but adds Rust IPC + sidecar Python without an analytical benefit. Would also lose web-share path.
- *Dash (Plotly)* — rejected. Dashboard-shaped framework. Cockpit would ship fast, every other page would crawl.
- *Single-process Python served via Jinja templates* — rejected silently as unfit for the design ambition; not formally on the candidate list.

**How to apply** (will materialize over Phase 3 build order; lock the structure when scaffolding lands):
- **Repo layout** (proposed; finalize during scaffolding):
  ```
  ootp-diamond-app/
    src/diamond/             # existing Python package (warehouse + analytics)
      api/                   # NEW: FastAPI app, route modules, Pydantic schemas
    web/                     # NEW: Next.js (App Router) frontend
      app/                   # routes
      components/            # shared React components
      lib/types/             # auto-generated TS from Pydantic
    pyproject.toml           # Python deps (FastAPI, uvicorn, pydantic-to-typescript or similar)
    web/package.json         # Node deps (Next, React, Tailwind, shadcn/ui, KaTeX, Vega-Embed, Plotly)
  ```
- **Type generation**: Pydantic models live in `src/diamond/api/schemas/`; a build step (likely `pydantic-to-typescript` or `datamodel-code-generator`) emits `web/lib/types/api.ts`. Run on save during dev; CI gate on production builds. Final tool choice TBD when scaffolding.
- **Dev workflow** (target): `uvicorn diamond.api:app --reload` on `:8000` + `pnpm dev` on `:3000` with Next dev proxy to API. Single `make dev` (or task runner) starts both.
- **Component primitives** (lean, finalize during scaffolding):
  - Tailwind + shadcn/ui for layout/atoms/forms
  - Vega-Embed for chart rendering (≤50K points), Plotly WebGL for the size-blower scenarios (>50K, e.g., universes containing every batter ever)
  - KaTeX for math rendering (~50KB; matches D15 formula format)
  - TanStack Table for sortable/filterable leaderboards
- **Data flow pattern**: every API endpoint returns Pydantic → JSON; the frontend imports the generated TS interface; no hand-typing in the UI. The dictionary (D15) is the source of stat metadata; the warehouse is the source of values; the API stitches them.
- **Auth + multi-tenancy**: explicitly out of scope per UI_DESIGN.md "audience" section. The API binds to localhost only by default. Web-share path (Phase 4+) would add auth as a separate decision.
- **Tech-stack open questions absorbed into D16**:
  - *Settings file format*: TOML (Python-native, comment-friendly) — locks D14's `~/.diamond/settings.toml`.
  - *Theming*: defer until UI matures (not in MVP scope).
  - *Anomaly thresholds, AI prompt library, onboarding analytics*: stay open in UI_DESIGN.md.
- **Universe export format** (per UI_DESIGN.md's community-share aspiration): JSON, schema versioned. Lock when chart builder lands.

**Implementation status (2026-05-07)** — scaffold landed and verified end-to-end:

- **Backend** (`src/diamond/api/`):
  - `app.py` — FastAPI app factory with CORS allowlist for `localhost:3000`. Includes `/api/health` and `/api/glossary` route modules with `/api` prefix.
  - `schemas/` — `GlossaryEntry`, `GlossaryListResponse`, `HealthResponse` Pydantic v2 models. The schemas package is the canonical source of truth for the API contract; `pydantic-to-typescript` only scans this package.
  - `routes/glossary.py` — `GET /api/glossary` (list) + `GET /api/glossary/{id}` (single, 404 on miss). Reads from `diamond.dictionary.STATS`.
  - `routes/health.py` — liveness probe.
- **Frontend** (`web/`):
  - Next.js 15.5 App Router + React 19 + TypeScript strict.
  - Tailwind 3.4 + autoprefixer (shadcn/ui deferred until needed).
  - KaTeX 0.16 + react-katex 3.x (with `@types/react-katex` since upstream ships none).
  - `app/glossary/page.tsx` (list, grouped by category) + `app/glossary/[id]/page.tsx` (detail with KaTeX block formula + related-id chips + external glossary links).
  - `components/FormulaBlock.tsx` — KaTeX wrapper with parse-fail fallback.
  - `lib/api.ts` — typed fetch helpers reading `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
  - **Force-dynamic pattern**: every page that fetches the API gets `export const dynamic = "force-dynamic"`. Diamond is local-first; static prerender at `next build` time would call the API while uvicorn isn't running. Worth noting in the "Adding a new API route" recipe in DEV.md.
- **Type-gen** (`scripts/generate_types.py`):
  - Wraps `pydantic-to-typescript`; locates `json2ts` CLI on PATH or in `web/node_modules/.bin/`.
  - UTF-8 stdout reconfigure on Windows (matches the CLI / smoke pattern).
  - Emits `web/lib/types/api.ts` with a Diamond-specific "do not edit" header pointing back at this decision.
  - Auto-gen carries Pydantic docstrings as JSDoc on the TS interfaces — bonus side-effect.
- **Dev workflow** (`Makefile` + `docs/DEV.md`): `make api`, `make web`, `make types`, `make smoke`. Two-terminal flow documented; no `make dev` parallel target on Windows since separate logs are easier to read.
- **Verified live** (2026-05-07):
  - `make types` regenerates clean.
  - `pnpm typecheck` passes.
  - `pnpm build` succeeds with 1 static + 2 dynamic routes.
  - End-to-end browser flow: home → /glossary → /glossary/wOBA renders KaTeX-rendered MathML formula, related-stat chips, Fangraphs external link.
- **Open follow-ups for the next route**:
  - shadcn/ui not initialized yet — drop in via `pnpm dlx shadcn@latest init` when the player page needs Card / Tabs / etc.
  - Vega-Embed and Plotly not installed yet — add when chart builder lands.
  - TanStack Table not installed yet — add when leaderboards land.

## D17 — Information architecture: five-tab scope+purpose nav

**Date**: 2026-05-08
**Decision**: Top-level navigation is **Club / League / World / History / Explore** with **Glossary** as cross-cutting reference and a search box (planned) as a cross-cutting Player lookup. Settings + (future) Reviews live in a corner menu rather than as peer tabs.

The first three (Club / League / World) are **scope** lenses — concentric: your org → the leagues you scope to → every league in the save. The fourth (History) is a **time** lens orthogonal to scope. The fifth (Explore) is the **interaction-mode** lens — the open-ended sandbox where you bring the question and the view brings the primitives. Each tab is its own URL prefix (`/`, `/league`, `/world`, `/history`, `/explore`). Player pages, the glossary, and (future) cohort pages are reachable from any tab and don't get peer status.

**Why**: UI_DESIGN.md §1 originally put a "Front-Office Cockpit" as the home with the build order putting it at item 8 — "emerges naturally from previous components." In practice that meant we shipped four standalone tools (glossary, player, demotion-promotion ledger, save-aware landing) without any of the screens that organize them. Pulse-check 2026-05-08: build features as orphan routes long enough and the IA never forms. So we committed the IA *now*, with stubbed routes for the four tabs that don't have content yet, and from this point every new feature lands in the right slot rather than as another `/some-tool` orphan.

**How to apply**:
- New top-level routes go under one of the five tab prefixes. Roster lives at `/club/roster` (or as a Club section once the cockpit grows). Leaderboards live at `/league/leaderboards` (curated) and `/explore/leaderboards` (build-your-own); same component, different defaults. Records / awards / HoF / streaks (already in the CLI) port to `/history/...` web views.
- Player pages stay at `/player/[id]` — they're a target, not a peer view; reachable from Club roster, League leaderboards, History HoF list, etc.
- World View is **kept as a peer** even though this save's scope already covers MLB + DSL + AFL — UI_DESIGN.md §1 audience covers users who follow international ball / KBO / NPB; promoting World back later if scope expands is harder than leaving the slot in place now.
- Each tab's stub renders a `TabStub` component with a header + section grid showing planned content with `Live` / `Soon` pills. Future sections light up by flipping their status and adding an `href`.

**Alternatives considered**:
- *Cockpit-first as the home, no peer scope tabs* — what UI_DESIGN.md originally implied. Rejected because the cockpit's full content (anomaly flags, decisions queue, standings) depends on data sources we haven't built; in the meantime a cockpit page is just the landing-with-extra-cards shape, and we still need the peer tabs to host other content.
- *Drop World View, only ship Club + League + History + Explore* — explicitly rejected per user request: "some people follow all leagues."
- *Make Player a peer tab* — rejected; player is a target reachable from many places, not a destination you "go to" without a specific player in mind. Search box (cross-cutting) covers the entry case.
- *Flat-URL preserve (keep `/movements`, `/glossary` at top level instead of nesting under `/club/...`)* — chose flat for now. The nesting can land alongside the roster page if we decide URL-as-IA is worth the migration cost.

## D18 — UI theme system: CSS-variable semantic tokens, four themes, dark default

**Date**: 2026-05-08
**Decision**: Diamond ships with **four themes** — `light` / `dark` / `neutral` (warm cream) / `cb` (Wong-palette color-blind safe) — switched via a `data-theme` attribute on `<html>` and persisted to `localStorage["diamond.theme"]`. **Dark is the default.** Themes are defined as CSS custom properties under `:root` and `[data-theme="..."]` selectors in `web/app/globals.css`; the Tailwind config exposes them as semantic tokens (`bg-surface-page`, `text-content-primary`, `border-border`, `text-link`, etc.) so components write theme-agnostic class names.

**Why**: UI_DESIGN.md "Open questions" originally listed theming as "skip until UI matures." In practice the user worked the app on monthly-dump cadence and white was eye-burning. Shipping a theme system before more pages get built makes every subsequent page automatically theme-correct rather than requiring a per-page retrofit. The CSS-variable approach was picked over Tailwind's `dark:` utility prefix because we want more than two themes (Tailwind's `dark:` only supports one alternate).

The `neutral` warm-cream theme exists specifically because "the app is too bright for me" — pure white induces eye strain in long sessions. The `cb` theme is Wong (2011) palette + IBM CB-safe — chrome only in v1 (accent + link colors swap to safe blue/orange), with the verdict glyph + move-type badge palettes still using the green/amber/rose convention; full CB-safe accent migration is a backlog item.

**How to apply**:
- Surface colors: `bg-surface-page` (body), `bg-surface-card` (raised), `bg-surface-elevated` (hover / table head).
- Text colors: `text-content-primary` (body / data), `text-content-secondary` (descriptions), `text-content-muted` (labels / captions).
- Borders: `border-border` (default), `border-border-strong` (career-totals separator).
- Accent / links: `text-link` / `hover:text-link-hover` / `text-accent`.
- For the move-type badges in the movement ledger and the Free Agent / HoF chips on the player page, we kept the named-Tailwind palette (emerald / amber / indigo / sky / rose) but added `dark:` overrides per badge — `dark:bg-emerald-900/40 dark:text-emerald-300` etc. Tailwind config has `darkMode: ["class", '[data-theme="dark"]']` so the `dark:` prefix fires when the dark theme is active.
- **No-flash init**: an inline `<script>` in `<head>` reads `localStorage["diamond.theme"]` synchronously before body paints and stamps the attribute. Without it, every reload flashes the default theme for ~50ms before settling.
- New pages: write semantic-token class names from the start. If a stat color is verdict-specific (working / struggling / etc.), use the existing badge convention with `dark:` overrides rather than introducing new tokens — adding tokens is a global decision, badges are local accents.

**Alternatives considered**:
- *Tailwind's built-in `dark:` strategy alone* — rejected. Only supports one alternate; we wanted four.
- *CSS-in-JS / styled-components* — rejected. Tailwind is already the project's styling language; swapping it out for a multi-theme system would be a huge migration for a small benefit.
- *Light as default* — rejected per user preference (2026-05-08 chat: "Dark mode should be default I think").
- *Defer color-blind support to v2* — rejected as a complete miss. Even a chrome-only CB theme is meaningfully better than no CB support, and the architecture supports lighting up the verdicts/badges later without a migration.

## D19 — `f_pa_event` is multi-year, sourced from L0 with cross-dump dedup; L1 event tables stay single-dump

**Date**: 2026-05-12
**Decision**: The L2 PA-grain fact `f_pa_event` is **multi-year**, built directly from the L0 layer (`l0_players_at_bat_batting_stats` + `l0_games`) with cross-dump deduplication keyed on `(game_id, season_year)`. The L1 event tables `at_bats_event` and `games_event` stay **single-dump (latest)** as they have been. Two layers, two audiences.

**PK changed**: `f_pa_event` PK was `(game_id, batter_id, pa_in_game_seq)`; it is now `(year, game_id, batter_id, pa_in_game_seq)`. `year` is in the key because **OOTP recycles `game_id` across seasons** — the integer 10001 is one game in dumps 2026-08 → 2027-02 (67 PAs) and a different game in dumps 2027-09 → 2028-02 (73 PAs). Within a single season `game_id` is unique; `year` (extracted from `games.date`) disambiguates seasons.

**Why**: The original `f_pa_event` build read from `at_bats_event` (L1, single-dump) joined to `games_event` (L1, single-dump). That meant the L2 fact was constrained to the latest dump's at-bat log only, even though L0 has retained every previously ingested dump's rows by `dump_date`. Player-page situational splits (clutch / RISP / platoon / counts / spray) wanted multi-year coverage and the storage was already there — we'd been throwing it away at the L1 boundary. Per the user's framing, "Can't we use storage to bridge the gap?" — yes; just stop discarding it.

L1 needed to stay single-dump because `audit/reconcile.py` registers `at_bats_event` and `games_event` as direct passthrough views and compares them against IE roster CSVs (which are per-dump). Promoting L1 to multi-year would break the audit harness's per-dump comparison semantics. The fix: leave L1 alone; have L2 reach back to L0 directly.

**Cross-dump dedup rule**: For each `(game_id, season_year)` pair, pick the latest `dump_date` that observed at-bats for that game. Post-November dumps are stable (no new data accrues); early-spring dumps (March of year Y+1 etc.) trim the prior year's data progressively before resetting. `MAX(dump_date)` always selects the fullest snapshot. `pa_in_game_seq` is then synthesized within that scope by `file_seq` order (per OPEN-4 resolution from SCHEMA.md).

**Layer-pattern note**: This is a deliberate exception to "L2 reads from L1." The general rule still holds for the seven other L2 facts (`f_player_season_*`, `f_player_career`, `f_team_season`, `f_league_season`, `f_award_event`). The PA-grain fact is the one place where multi-dump retention at L0 is the load-bearing semantic, so reaching down is the right call. Documented in the L2 build's docstring + DATA_NOTES "File rollover behavior" so future maintainers understand the pattern.

**Side benefit**: `game_type` is now carried directly on `f_pa_event` (was on `games_event` only), so consumers don't need a JOIN to filter regular season — the situational fetcher now reads `pa.game_type = 0` directly.

**Row-count impact** (verified live with `diamond ingest --rebuild-only`):
- `f_pa_event`: 877,363 → **5,132,283** (4 years).
- `f_player_season_statcast_batting`: 3,305 → **20,800**.
- `f_player_season_statcast_pitching`: 3,692 → **21,513**.
- `f_record_player`: 1,840 → **4,550** (save-side EV records cover all 4 years now).

**Alternatives considered**:
- *Build a sibling `f_pa_event_history` and leave `f_pa_event` single-year* — rejected. Two tables with overlapping shape doubles maintenance and forces every consumer to choose. Single multi-year fact is cleaner and existing consumers (l3 records, statcast cohort, situational fetcher) all GROUP BY year already, so they get richer output for free.
- *Promote L1 `at_bats_event` to multi-year and update reconcile* — rejected. The reconcile harness compares against per-dump IE CSVs; per-dump semantics at L1 are load-bearing for that audit path. Splitting L1 (single-dump) and L2 (multi-year) lets each layer serve its audience.
- *Persist Nov dumps separately and union with the latest dump* — rejected as redundant. L0 already retains every dump; we just had to query it correctly.

## D20 — Pre-save MLB league baselines come from Lahman (1871-2019) + BREF (2020-2025), UNION'd into `_lg_constants_advanced`

**Date**: 2026-05-12
**Decision**: The `_lg_constants_advanced` view, which the L3 advanced-stats builders JOIN against, is now a UNION of two component views: `_lg_constants_advanced_native` (sourced from OOTP's `league_history_*_event` — save years only) and `_lg_constants_advanced_imported` (sourced from `history_lahman_batting/_pitching` for 1871-2019 + `history_bref_batting/_pitching` for 2020-2025, summed across AL/NL/AA/FL/NA/PL/UA into the OOTP MLB league_id=203, level_id=1). Pre-save player-seasons that previously rendered `—` for wOBA / wRC+ / OPS+ / FIP / ERA+ / SIERA on the player page now resolve real values.

**Why**: OOTP imports pre-save player counting stats (Bonds 2001, Mantle 1956, Trout 2018, etc.) — 410,909 batting rows from 1871-2025 in `f_player_season_batting`, 234,677 of them at split_id=1 — but does NOT emit corresponding `league_history_*` rows for those years. The L3 advanced builders LEFT JOIN by `(league_id, year, level_id)`, so without a baseline they emit nulls for every advanced stat. The historical sources we already loaded for `f_record_player` and `f_award_career_player` (Lahman + BREF) carry every column needed to derive league constants — AB, H, 2B, 3B, HR, BB, IBB, HBP, SF, SH, SO, R for batting; IPouts, ER, HR, BB, SO, HBP for pitching. Empirically verified: Lahman 2001 NL+AL aggregates match OOTP's imported player-row aggregates within 0.5% (Lahman AB 166,234 = OOTP AB 166,234 exact; H 43,879 = 43,879 exact; minor IBB/HBP edge cases drift ~1 PA). OOTP imports Lahman directly, so the baselines are guaranteed self-consistent with the player rows that JOIN them.

**Coverage delivered** (verified post-rebuild on `Building the Green Monster` warehouse):
- `_lg_constants_advanced` view: **1871-2029 continuous, 215 (league, year, level) rows** (60 native + 155 imported).
- `f_player_season_advanced_batting`: 30,440 → **244,183 rows** (8× expansion). MLB level alone: 97,298 player-seasons gain wOBA / wRC+ / OPS+ / b_WAR.
- `f_player_season_advanced_pitching`: similar fill.
- Headline spot-checks: Bonds 2001 wOBA .550 / OPS+ 257 / b_WAR 12.5 (BBR 259 / 12.5 — exact); Pujols 2003 OPS+ 189 (BBR 189 — exact); Trout 2018 OPS+ 198 (BBR/Fangraphs 198 — exact); Pedro 2000 ERA+ 285 (BBR 291 — within 6 pts); Mantle 1956 OPS+ 220 (BBR 210 — Fenway PF gap, see below).

**Lahman historical sparsity** is the main known limitation. Tracking thresholds:
- IBB column populated 1955+ (zero before).
- SF populated 1954+ (zero before).
- HBP populated 1887+.
- SH populated 1894+.
- SO populated ~1913+.

For aggregation purposes nulls are coalesced to 0 (Fangraphs convention; OOTP imports zeros for pre-tracking columns too, so player-rows + league-rows stay self-consistent). Pre-1955 wOBA scale calibrates against the partial-data sums; absolute values won't match modern Fangraphs historical wRC+ exactly but are consistent across the era. Documented in DATA_NOTES.

**Park factor handling** is the second known limitation: pre-2026 OOTP player rows often join successfully to a *current-day* team and pick up that stadium's `parks.avg` (a 2001 SF Giants row resolves to Oracle Park's 1.003, not 2001's Pacific Bell). Park enters OPS+ at half-leverage and ERA+ at 80%-leverage; wOBA / wRC+ / wRAA don't use park at all. The miss is small in practice (most parks haven't shifted dramatically) but documented; a real fix would require loading BREF historical park factors and a team-history crosswalk, deferred as a follow-on.

**Save-start invariant**: the `_imported` view filters `yearID <= 2019` (Lahman) and `year BETWEEN 2020 AND 2025` (BREF), and `_lg_constants_advanced` UNIONs with NOT EXISTS guard on the native view to prevent duplicate keys. If a future save's start year ever migrates back into ≤2025, the guard fires and the native row wins (correct precedence — OOTP's in-save constants are authoritative for save years). The `fetch-history` loader already enforces `MAX_HISTORY_YEAR = save_start - 1`, so this is doubly safe.

**Soft-skip on missing history tables**: the L3 builder checks for the four `history_*` tables before registering `_imported`, and falls back to `native`-only if any are missing. Smoke-test runs in fresh in-memory DBs (no `fetch-history` data) hit this fallback cleanly with a yellow `!` indicator — no hard failure on warehouses that haven't run the one-time backfill.

**Alternatives considered**:
- *Use Fangraphs Guts table directly* for woba_scale + linear weights instead of recomputing from Lahman aggregates — rejected. Fangraphs Guts requires an additional data source / scrape with no clear long-term URL stability, and our self-consistent Lahman-derived constants pass spot-checks (Bonds OPS+ 257 vs BBR 259, Pujols 189 vs 189) within 1-3 pts on park-aware metrics. The wRC+ gap (~10-15% high vs Fangraphs canonical) is from our park-blind wRC+ formula, NOT the constants — same bias hits save-side data. Fixing wRC+ to be park-adjusted is a separate refactor.
- *Materialize a real L3 table for historical constants* instead of a view — rejected. The view is cheap (one aggregation per year × 155 years = trivial), and view-only means the constants always reflect the latest history backfill without a rebuild step. The rebuild dependency was already implicit (advanced tables rebuild on every L3 build).
- *Defer to the user setting up minor-league historical baselines manually* — rejected for v1. Lahman's minor-league coverage is spotty and the OOTP→Lahman league_id crosswalk for IL/PCL/etc. isn't bijective. MLB-only is the user-visible win; minor-league pre-save advanced stats stay null (same as today).

## D21 — Hand-rolled inline SVG for v1 visual primitives; defer chart-stack lib until cohort viz needs it

**Date**: 2026-05-12
**Decision**: For v1, all data viz on the site (Sparkline trend lines, CareerArc career-WAR chart, salary-stream bar viz, pressure-board metric coloring) is hand-rolled — pure inline SVG + Tailwind classes via the heat-scale module. No chart library (Vega-Lite, Plotly, Recharts, etc.) is added to the bundle. The chart-stack decision is deferred until a slice genuinely needs WebGL-scale cohorts or a JSON-spec authoring layer (most likely: spray charts on the player page, EV-LA scatter, league-wide distribution viz under Explore).

**Why**:

The visual upgrade slice (heat-scale + Sparkline + CareerArc + Cockpit v2, 2026-05-12) needed to land fast and feel substantial without committing the bundle to a charting framework whose API surface we'd carry forever. The shapes we needed — single-series trend lines, dot-per-year line charts with reference bands, salary bars — are all 50-200 LOC of straightforward SVG. Rolling them by hand:

- Keeps the bundle small (Sparkline + CareerArc + PlayerContractCard add ≤2 KB total to the relevant routes after gzip).
- Composes cleanly with the rest of the Tailwind / theme-token stack (CareerArc uses `fill-emerald-*` etc. directly; no chart-lib theme bridge).
- Lets each viz match the exact shape of the data we have, without library-imposed conventions (e.g., CareerArc's WAR-magnitude dot fills + peak-tier reference band would be awkward to express in Vega-Lite's grammar).
- Avoids the SSR / hydration / bundle-split complexity of a chart lib in a server-component-heavy app.

The cost: a handful of bespoke SVG modules to maintain. Acceptable when each is small and the visual vocabulary is shared (heat-scale colors flow into both bar viz + sparkline dots).

**When to revisit**:

The decision flips when a slice needs *any* of:
- **WebGL-scale point sets** — Statcast EV-LA scatter at full-league cohort scale (≥50K points) is well past hand-rolled SVG's comfort zone. Plotly with WebGL fallback handles this.
- **Interactive grammar-of-graphics authoring** — the `chart builder` slice on Explore (UI_DESIGN.md §6) needs JSON-spec authoring with X/Y/color/facet pickers. Vega-Lite is purpose-built for this; no point reinventing.
- **Coordinated multi-view linking** — e.g., a spray chart that filters when you brush an EV-LA scatter. Vega-Lite's signal-and-data API is the right primitive.

For everything *between* "hand-rolled" and those triggers — sortable leaderboards, distribution histograms, simple scatters — TanStack Table + plain SVG is plenty. The first slice that genuinely hits one of the triggers above picks the lib (lean: **Vega-Lite** for JSON-spec serializability, smaller bundle, easier AI-prompt authoring; reserve Plotly for the WebGL-scale cohorts case).

**Alternatives considered**:

- *Pick Vega-Lite (or Plotly) now and use it everywhere from day one* — rejected. Adds 100-200 KB to the bundle, pulls in a theme-bridge layer we'd have to maintain alongside the existing token system, and forces every viz to fit the lib's grammar (some shapes — CareerArc's peak-tier band, salary-stream's option-year badges — are awkward to express). Premature commit.
- *Use Recharts (React-native, smaller than Plotly)* — rejected. Still ~50 KB; still imposes its own theme conventions; doesn't carry through to the JSON-spec authoring vision (UI_DESIGN.md §6) which is a v2 selling point.
- *Skip charts entirely until the chart-stack decision lands* — rejected. The "fun" upgrade slice (2026-05-12) was specifically about making the app feel less like spreadsheets; deferring viz entirely until the chart lib lands would have meant another 1-2 weeks before the app got any visual richness. Hand-rolling unblocked the win without committing the architecture.

**Side benefit — visual vocabulary coherence**: because every primitive is built in-tree, the heat-scale color ramp (defined once in `web/lib/heatscale.ts`) shows up identically on roster-row text, pressure-board cells, player-page stat cells, cockpit spotlight headlines, and CareerArc dot fills. A chart lib would have introduced its own scale-color system that we'd have to mirror, drift from, and maintain in parallel. By the time we adopt Vega-Lite, the heat-scale vocabulary will be load-bearing enough that we'll thread it *into* the chart lib rather than the other way around.

**Catalog of v1 hand-rolled visual primitives** (all in `web/`):

- `lib/heatscale.ts` — color functions for 100-relative metrics + WAR magnitude.
- `components/Sparkline.tsx` — generic inline-SVG trend chart with auto-trend coloring.
- `components/CareerArc.tsx` — career-WAR-by-year line chart with WAR-magnitude dots + reference bands.
- `components/PlayerContractCard.tsx` — CSS-bar salary timeline with option badges.
- `components/PlayerAvatar.tsx` — circular headshot with deterministic-color initials fallback.

Each is a self-contained file ≤300 LOC. When the chart lib lands, evaluate each on a "rewrite or keep" axis — Sparkline + CareerArc are likely keepers (stable shape, perfect token integration); PlayerContractCard could go either way; PlayerAvatar isn't a chart and stays regardless.

## D22 — Historical park factors backfill (Lahman BPF/PPF for ≤2019 MLB seasons)

**Date**: 2026-05-13
**Decision**: Pre-2020 MLB OPS+ / ERA+ now use the Lahman team-season park factor (BPF / PPF, 100-relative, divided by 100 to match OOTP's 1.0-relative convention). A new view `_park_factor_resolved (team_id, year, bat_park_avg, pit_park_avg, src)` is the single source of truth for `(team_id, year) → park_avg`, joined into both advanced builders. For 2020-2025 (BREF era — Lahman doesn't extend that far, BREF doesn't ship per-team park factors in our scrape) and 2026+ (save-native), the view falls back to the OOTP team's current-day `parks.avg` (modern-stadium proxy, same as before D22).

OOTP↔Lahman crosswalk is hardcoded for the 30 modern MLB clubs by (`team_id`, `franchID`). franchID is stable through historical team renames (e.g., 'BAL' covers St Louis Browns 1902-1953 + Baltimore Orioles 1954-present), which is the right granularity for a franchise-as-stadium proxy. Defunct historical franchises (Brooklyn Robins, Boston Beaneaters) won't have OOTP team_id rows in pre-save player data — those player-rows fall through to `park_avg=1.0`, same as before D22.

**Why**:

Pre-D22, a 2001 SF Giants player-row joined Oracle Park's modern 1.003, when the actual 2001 NL pitcher's park factor at Pac Bell / 3Com / Candlestick was 0.93. That biased pre-2020 OPS+ / ERA+ on the order of ±5 percentage points across teams. The fix unblocks accurate cross-era comparisons (Bonds 2001 vs Trout 2018 vs Devers 2029) which is a big share of what `/explore/compare` is for.

- Lahman publishes per-team BPF/PPF as part of `Teams.csv` going back to 1871; this is ~150K rows, trivially small to UNION into a view.
- BPF and PPF differ for the same team-year (offense-park vs pitcher-park aren't symmetric — different ballpark dimensions affect HR rate vs BABIP differently); we plumb separate fields through `_park_factor_resolved` so batting builders use BPF and pitching uses PPF.
- The view is conditional: if `history_lahman_teams` doesn't exist (fresh save without `fetch-history` run), L3 builds register a fallback view with the same shape that just exposes modern `teams.parks.avg`. No hard-fail path.

Verification (pre→post): Bonds 2001 OPS+ 257→267 (BBR 259), Pujols 2003 189→193 (BBR 189), Trout 2018 198→201 (BBR 198), Pedro 2000 ERA+ 280 (BBR 291), Maddux 1995 ERA+ 277 (BBR 260), Coors 1995 BPF 1.29.

**Alternatives considered**:

- *Compute park factors from Lahman home/road run differential* — rejected. Lahman has team-level home games + total games, but home-only run scoring isn't broken out. Computing PF from runs requires play-by-play (Retrosheet) which we don't ingest.
- *Maintain a hand-curated `pf_history.csv`* — rejected. Lahman already does this work and ships it; no reason to duplicate.
- *Backfill 2020-2025 with FanGraphs / BREF scraper* — deferred. Pre-2020 fixes the bigger and more variable historical range; 2020-2025 are five years of relatively stable modern parks where the modern-proxy is reasonable. Backlog item.
- *Apply BPF/PPF retroactively to wOBA / wRC+ / wRAA* — out of scope. Those formulas are park-neutral by definition (they use league-relative weighting, not park-relative); only OPS+ and ERA+ have the `(1 + (park_avg - 1) / k)` correction term.

## D23 — Chart stack: Observable Plot for cohort viz; defer Vega-Lite + WebGL until JSON-spec authoring lands

**Date**: 2026-05-13
**Decision**: First chart-lib commitment for the project picks **Observable Plot** (`@observablehq/plot`). Used for the EV-LA scatter (`/explore/ev-la`) and the secondary stacked-bar view in the spray chart (`/explore/spray`). The polar-fan in the spray chart stays hand-rolled SVG (not a Plot-friendly shape).

Plot adds ~150 KB gzipped to the chart routes and provides a declarative API ergonomic for both `Plot.dot` scatters and `Plot.barX` stacks. Reuses the project's existing color/discipline conventions (out muted / hit saturated / HR loud) without a custom theme bridge.

**Why**:

The viz triggers from D21 (WebGL cohorts, JSON-spec authoring, multi-view linking) haven't all fired — the v1 cohort scatter is per-player (≤700 BIP), not full-league (≥50K points), and we don't yet need spec-authoring or brushed views. But within "modest cohort size + multiple chart types share a styling vocabulary," Plot is the lowest-friction choice:

- Smaller bundle than Plotly (~150 KB vs ~1 MB+).
- Smaller and more ergonomic than Vega-Lite for the simple shapes we have today (dot scatter, stacked bar). Plot is closer to D3 with sensible defaults.
- Pure SVG output integrates with the theme-token system without a custom mark renderer.
- When WebGL or spec-authoring triggers fire, we can bring in Plotly (for the WebGL-scale path) or Vega-Lite (for the chart-builder path) alongside Plot rather than rewriting the simple shapes.

**Catalog of v1 chart-lib usage**:

- `web/components/EvLaScatter.tsx` — `Plot.dot` scatter with `Plot.rect` zone overlays (sweet-spot + barrel zone).
- `web/components/SprayChart.tsx` — `Plot.barX` stacked bar (secondary view); the primary polar fan stays hand-rolled SVG.

**When to revisit**:

- **Plotly** when a single chart needs >10K points or true 3D / map-based views.
- **Vega-Lite** when the `chart builder` slice (UI_DESIGN.md §6) lands — JSON-spec authoring is its native idiom and Plot doesn't expose a comparable serialization path.

**Alternatives considered**:

- *Vega-Lite from day one* — rejected. Heavier for the simple shapes we have now, and the chart-builder slice that justifies it isn't on the immediate roadmap.
- *Plotly* — rejected. ~7× the bundle of Plot for capabilities we don't yet need.
- *Recharts* — rejected. React-native is appealing but it's slower than Plot on >5K points and doesn't compose cleanly with custom SVG annotations.
- *uPlot* — rejected. Tiny and fast but limited to time-series shapes; we need scatter + stacked bar.
- *Continue hand-rolling* — rejected for scatter. EV-LA scatter with proper axis ticks + zone overlays + tooltips would be ~400 LOC of custom SVG; Plot ships it in ~95.

## D24 — Photo cache: revalidation-based, no artificial TTL

**Date**: 2026-05-13
**Decision**: `/api/photos/players/{id}.png` carries `ETag` (mtime-size pair) + `Last-Modified` headers and explicit `Cache-Control: no-cache` (RFC 7234 "always revalidate"). Browsers cache photo bodies indefinitely AND auto-refresh the moment OOTP rewrites a file — revalidation is a tiny ~500-byte 304 when unchanged, full 200 with new bytes when the file's mtime changes. 404s carry no cache header (local stat is microseconds; the regen we just ran shouldn't be invisible for an hour).

**Why**:

The previous `max-age=86400, immutable` was a defensive guard against "what if photos change," but the trade was wrong: after a user runs OOTP's bulk regenerate-pictures, the browser kept serving stale cached bytes (or blank-initials for newly-cached photos) for 24 hours despite Diamond's API instantly seeing the new files on disk. Revalidation via ETag/IMS gives "cache forever AND auto-refresh on file change" — the right pattern for a local-first single-user app where the disk is right there to ask. RFC 7232 §6 has ETag winning over If-Modified-Since when both arrive.

**Cost**: per-photo conditional GET on every page load. On localhost ~1ms each × 40 photos on a roster page = ~40ms total — invisible. If we ever ship a hosted variant, revisit (might use `max-age=300` with the same handlers so the network cost is amortized).

**Implementation note**: FastAPI's `FileResponse` doesn't auto-handle If-Modified-Since; the route reads `request.headers.get("if-none-match")` + `if-modified-since`, returns `Response(status_code=304, headers={...})` on match.

## D25 — LSEG-Workspace density refactor (full-width, responsive charts, terminal aesthetic)

**Date**: 2026-05-13
**Decision**: Diamond's UI shifts from a centered-blog-post aesthetic (max-w-6xl, text-3xl headers, generous py-8 padding) to a Bloomberg-terminal aesthetic (full-width, compact 36px sticky header, text-xl font-semibold page headers in a category·title·context line, text-sm body default, responsive Plot charts via `useElementWidth`). Reference: LSEG Workspace screenshots in `docs/ui_examples/`.

**Why**:

User feedback: "doesn't feel sleek or professional," "charts are smooshed," "lots of scrolling." The audit found three concrete causes:

1. `<main className="max-w-6xl">` wasted ~770px on a 1920+ monitor. Bloomberg/FanGraphs/Savant/LSEG all use generous horizontal real estate.
2. Plot charts had hardcoded `width: 720` / `width: 800` — sat in the middle of wide containers, didn't fill panels.
3. `text-3xl font-bold` page headers + `space-y-8` outer spacing gave a "marketing site" feel instead of "terminal".

The shift addresses each in one pass: layout opens to viewport-wide with `px-3 sm:px-4 lg:px-6` gutters; Plot charts ride a ResizeObserver-backed hook (`web/lib/useElementWidth.ts`) that re-renders on container resize; page headers across 9 main pages collapse to LSEG-uniform `[10px UPPERCASE CATEGORY] [Title · context]` plus a single text-xs metadata line.

**What stayed**:

- Existing CSS-variable theme system (D18) — the wide-layout shift is orthogonal to color tokens
- Existing component-level rounded-md + border tokens — sharp-corner pass deferred to a follow-up
- Settings pages keep `max-w-3xl` inner containers (form readability)
- StadiumSprayChart caps at 720px max-width (a 500×480 viewBox at full container width on a 1920 panel would balloon to 1500+px tall)

**Side benefits**:

- Default `text-sm` body raised global density without per-component changes
- Sticky header (`sticky top-0 backdrop-blur`) keeps nav visible while scrolling long pages
- Cockpit spotlight grid bumps to `2xl:grid-cols-6` so the 6 cards fit in one row on ultrawide

**Wave 2 candidates** (not shipped in D25 itself; tracked as follow-ons):
- Sharp-corner pass (drop most `rounded-lg` to `rounded-sm` / `rounded-none`)
- Cockpit multi-pane: standings + pressure + recent-moves into a 3-col grid at 2xl
- Player page two-column at xl+ (bio sidebar left, tab content right) — saves ~400px of vertical scroll
- Table density: rows ~32px → ~24-26px

## D26 — L_REF reference layer from OOTP parent-folder data

**Date**: 2026-05-13
**Decision**: Diamond gains a new ingest layer **`L_REF`** (reference / read-only canon) sitting alongside L0-L3. L_REF reads from the OOTP parent folder `<docs>/Out of the Park Developments/OOTP Baseball 27/` — ~500MB of static reference data shared across saves — into `lref_*` tables in each save's warehouse. Re-ingested only when OOTP version bumps; treated as read-only canon (Diamond never writes back to the parent folder).

**Why**:

We spent the early phases reverse-engineering OOTP from its CSV dumps + Lahman/BREF backfills, missing that the engine ships with comprehensive reference data right alongside the executable. Inventory of the parent folder (run 2026-05-13 evening):

- **`database/pt_ballparks.txt`** (240 rows) — current MLB+minors park dimensions (7-segment outfield: LL/LF/LCF/CF/RCF/RF/RL distances + heights), plus LH/RH split park factors per stat (BA/2B/3B/HR). Authoritative replacement for our hand-coded `web/lib/stadiums.ts`.
- **`database/era_ballparks.txt`** (3,105 rows × 155 years 1871-2025) — historical park dimensions + park factors per (year, team), with full LH/RH splits. Replaces D22's Lahman BPF/PPF (single-number 100-relative) with full-fidelity dataset including pre-1920 dead-ball-era parks.
- **`database/era_stats.txt`** (82 cols) — historical league-average stats per season (BA/OBP/SLG/OPS/ERA/K%/BB%/fielding splits/GB/FB ratios). More OOTP-environment-accurate than Lahman aggregates.
- **`stats/Master.csv`** (24,747 rows × 68 cols) — `playerid` (OOTP) ↔ `lahmanID` ↔ `BBrefMiLBid` ↔ `retroID` ↔ `holtzID` crosswalk + draft pitch arsenal + position experience + scouting ratings. Replaces our Chadwick Register lookup.
- **`stats/MiLBMaster.csv`** (29MB) — minor-league master, vastly richer than Lahman MiLB. Solves the v2.2 backlog item "minor-league pre-save baselines stay null".
- **`stats/Teams.csv`** + **`historical_database.odb`** (122MB) + **`historical_minor_database.odb`** (274MB) — additional historical data we may unpack.
- **`logos/`** (1,829 files) — every team logo with per-era variants. **`.oi` files are PNGs** — magic bytes `89 50 4E 47` confirmed. Per-era Sox logos: 1908-1923, 1924-1960, 1961-1969, 1970-1975, 1976-2008, current.
- **`ballcaps/`** (343), **`jerseys/`**, **`pants/`**, **`socks/`** — full uniform asset set.
- **`database/db_structure_complete_ootp21_*.txt`** (csv / mysql / access variants) — canonical OOTP schema docs. **We've been reverse-engineering CSV columns; this is the official source of truth.**
- **`database/team_nick_names.xml`** + **`names.xml`** + **`schools.xml`** + **`world_default.xml`** — name/nickname/school/geography generators.

**How L_REF works**:

```
L_REF (D26)  ←  read once from <ootp_root>/database/ + <ootp_root>/stats/
  lref_pt_ballparks      240 rows
  lref_era_ballparks     3,105 rows × 155 years
  lref_era_stats         82-col league avgs per year
  lref_era_stats_minors  separate; minors by era
  lref_master            24,747 OOTP↔Lahman crosswalk
  lref_milb_master       large MiLB master
  lref_teams_history     from Teams.csv
```

L_REF is per-save (lives in each save's `diamond.duckdb`) but the underlying data is global — so it's the same content in every save, just locally available for JOINs. Re-ingest when OOTP version bumps (rare); skip when unchanged via mtime check. CTAS pattern stays the same as L0; CSV format means `read_csv_auto` works directly.

**Replacements / upgrades enabled**:

1. **Ballpark geometry** — drop `web/lib/stadiums.ts` hand-coded entries; pull from `lref_pt_ballparks` via API. Adds wall heights for ALL 7 segments (we had 3) and per-park type / surface (open / retractable / fixed dome).
2. **D22 v2 era-aware park factors** — `_park_factor_resolved` view reads from `lref_era_ballparks` instead of `history_lahman_teams`. Per-(year, team) authoritative dimensions + LH/RH split factors → handedness-aware OPS+/ERA+ matching OOTP's engine.
3. **OOTP↔Lahman crosswalk** — replace the Chadwick-based `history_player_id_map` with `lref_master`. Simpler, authoritative, with more ID columns (BBrefMiLBid for minors).
4. **MiLB pre-save baselines** — `lref_milb_master` + `lref_era_stats_minors` replaces "Lahman has spotty MiLB coverage" with comprehensive OOTP-shaped data.
5. **Real team logos rendering** — `/api/logos/{abbr}` route serves `.oi` files (PNGs internally; just set `Content-Type: image/png`). Per-era variants enable historical pages (a 1922 Babe Ruth page can show the era-correct Yankees logo).
6. **Schema docs** — fold `db_structure_complete_ootp21_*.txt` content into `DATA_NOTES.md` so we stop reverse-engineering column meanings.

**Why now**:

Two motivations: (1) the hand-coded approximations are starting to show — the user noticed unrealistic park-effect outliers, photos visible-but-stale, stadium overlays use rounded-up Wikipedia numbers. L_REF replaces every approximation with OOTP's source-of-truth. (2) The L0-L3 architecture has been "warehouse from one save's dumps" — correct for save-state data. L_REF is the missing layer for cross-save canonical reference data. Adding it now (before more features pile on top of the approximations) keeps the refactor scope bounded.

**Architectural commitments**:

- L_REF tables prefixed `lref_*` (alongside `l0_`, `l1_`, etc.) so the layer is visible in `SHOW TABLES`.
- L_REF is read-only from Diamond's perspective. The OOTP parent folder is canonical user data; we never write into it.
- L_REF ingest is idempotent + skipped-when-unchanged (mtime check on the source files).
- Joins from L1+/L2+/L3 to L_REF go through views, never inlined into builders. Easier to swap data sources later.
- L_REF docs the OOTP parent-folder layout in `docs/DATA_NOTES.md` so we don't re-discover this in future OOTP versions.

**Alternatives considered**:

- *Just statically embed the data in TypeScript / Python files* — rejected. We did this for `web/lib/stadiums.ts` (30 parks, hand-coded from Wikipedia) and it's already drifting from OOTP truth. L_REF's database-table approach scales to 240 + 3,105 + 24,747 + ... rows without hand-curation.
- *Re-ingest L_REF every L0 build* — rejected. Source files only change on OOTP version bumps; mtime check is sufficient.
- *Single shared L_REF DuckDB at `~/.diamond/lref.duckdb`* — rejected for v1. Cross-database JOINs from per-save L0/L1/L2/L3 to a separate file complicate every query. Pay the small storage cost (likely <100MB after ingest) for the simpler in-warehouse JOIN model.
- *Skip L_REF entirely and keep approximations* — rejected. The user's reaction to seeing the parent folder ("there's a goldmine") + the alignment opportunities (era-aware park factors, real logos, official schema docs) make this clearly worth doing.

**Out-of-scope for L_REF v1**:

- Parsing the binary `.odb` files (`historical_database.odb`, `historical_lineups.odb`). Format is OOTP-internal; if we ever need the data, it's also in the CSV exports.
- Writing to OOTP — Diamond stays read-only relative to the parent folder.
- Watching for live updates while OOTP is running — L_REF is per-launch, not continuous.

## D27 — L_REF is per-save, frozen at first ingest, opt-in refresh

**Date**: 2026-05-13 (evening, paired with D26)

**Decision**: L_REF tables (canonical OOTP reference data ingested from the install folder per D26) are **snapshotted into each save's warehouse at first ingest** and **frozen for the lifetime of that save**. Refresh is opt-in via `diamond ingest --refresh-lref` (with a CLI diff preview before commit). OOTP install upgrades (e.g., OOTP 28+) trigger a natural prompt because the source path changes.

This means the misc/ analytical lookup tables (xwOBA / xBA / xSLG / RE288 / WPA / LI / xiso) and the database/era_* baselines are **part of the save's reproducibility contract** — once ingested, the same save always computes the same numbers, regardless of subsequent OOTP patches.

**Why**:

OOTP itself captures install-folder reference data into the save at save-creation time, then ignores subsequent edits to install-folder copies. That's why mid-version patches don't break running saves — the engine treats reference data as **write-once for save lifecycle**. If we ingest L_REF naively from the live install folder on every `diamond ingest`, we lose that protection: numbers we computed yesterday could shift today purely because OOTP shipped a patch, even though the user's save itself didn't change.

Concrete dispersion examples if we DIDN'T freeze:

- A patched `era_stats.txt` 2001 NL OBP-baseline → Bonds 2001 OPS+ moves silently between yesterday's report and today's.
- A patched `xwoba_table.txt` (LA, EV) cell → xwOBA values for past at-bats shift retroactively.
- A patched `xiso_table.txt` zone classifier → barrel% on a past Crochet line jumps because a borderline BIP got reclassified.

The fix mirrors the engine: snapshot L_REF into the save's own warehouse at first ingest, freeze it there, treat install-folder refresh as an explicit user opt-in.

**Risk by L_REF category** (which actually drift on patch):

| Category | Source files | Drift on install patch? |
|---|---|---|
| Calculation tables | `misc/{xwoba,xba,xslg,re288,li,wpa,xiso}_table.txt`, `pi_table.txt` | **Yes** — re-classifying historical BIPs / re-deriving WPA against new tables |
| League baselines | `era_stats.txt`, `era_stats_minors.txt`, `era_modifiers.txt`, `era_fielding.txt`, `total_modifiers.txt` | **Yes** — pre-2026 OPS+ / ERA+ / wRC+ all move |
| Park factors | `era_ballparks.txt`, `pt_ballparks.txt` | **Yes** — handedness-split factors and 7-segment dimensions could revise |
| Engine config | `major_league_baseball.json`, `financials.txt`, `*.json` league templates | **Yes** — save's actual rules captured at save creation; live edits would mislead |
| Crosswalks | `Master.csv`, `MiLBMaster.csv`, `players.csv` | None — pure ID lookups; additions/typo-fixes are upgrades |
| Schema docs | `db_structure_*.txt` | None — documentation |
| Cosmetic | logos, colors, ballpark textures, hof plaques + index.json | None — visual assets |

The "None" rows could in principle be refreshed live without dispersion, but for simplicity we freeze the entire L_REF together at first ingest and refresh together via `--refresh-lref`. One coherent snapshot is easier to reason about than per-category staleness.

**Implementation**:

1. **First `diamond ingest` for a save** — ingest L_REF into per-save DuckDB (`<save>/diamond/diamond.duckdb`) as `lref_*` tables.
2. **Persist provenance** in `_diamond_settings`:
   ```toml
   [lref]
   ingested_at = "2026-05-13T20:14:33Z"
   source_path = "C:/Users/chris/Documents/Out of the Park Developments/OOTP Baseball 27"
   ootp_version = "27"
   [lref.files]
   "database/era_ballparks.txt"  = { mtime = "2026-03-25T...", sha1 = "..." }
   "database/era_stats.txt"      = { mtime = "2026-03-06T...", sha1 = "..." }
   "misc/xwoba_table.txt"        = { mtime = "2025-12-02T...", sha1 = "..." }
   ...
   ```
3. **All analytical queries** read from the per-save snapshot via `lref_*` table names — never from the live install folder. No `read_csv_auto('<ootp>/...')` calls outside the L_REF ingest module.
4. **Subsequent `diamond ingest` runs** detect L_REF already populated and **skip** L_REF re-ingest by default (silent — this is the steady state).
5. **Explicit refresh**: `diamond ingest --refresh-lref` re-reads from the install folder, computes a diff preview ("3 files changed: era_ballparks.txt, era_stats.txt, Master.csv — proceed?"), confirms before overwriting. Settings page exposes the same toggle as a button.
6. **OOTP version bump**: when the source path changes (`OOTP Baseball 27` → `OOTP Baseball 28`), settings page surfaces "new OOTP version detected — refresh L_REF?" rather than silent re-ingest. Old `lref.source_path` stays in `_diamond_settings` for reproducibility audit.

**Storage cost**: ~30-50MB per save once L_REF tables are populated (240 + 3,105 + 24,747 + ... rows across ~10 tables, plus the misc/ lookup tables which are tiny). Negligible vs typical save size of GB+.

**Alternatives considered**:

- *Single global `~/.diamond/lref.duckdb`* — already rejected in D26 for cross-database JOIN complexity. Per-save snapshot adds the freeze property "for free" given we're already storing per save.
- *Symlink L_REF tables across saves* — DuckDB doesn't support cross-database symlinks; would defeat the freeze property anyway.
- *Track install-folder mtimes per save and warn-on-mismatch but still read live* — half-measure that doesn't actually freeze the values; first-time-after-mismatch reads still drift.
- *No `--refresh-lref` flag, freeze forever* — rejected. Without an opt-in surface, users can never pick up legitimate corrections (e.g., a Master.csv typo fix that adds a missing real-history ID).
- *Per-category freeze (freeze baselines but live-read crosswalks)* — rejected. Adds complexity without material upside; one coherent snapshot is easier to reason about.

**Cross-references**: D2 (per-save warehouse path), D8 (per-save reconciliation), D26 (the L_REF layer itself).

**Out of scope for v1**:

- Per-stat "computed from L_REF version X" tag in the UI. Audit-trail is overkill; users who care can read `_diamond_settings`.
- Mid-save automatic refresh detection. If the user never opts in, L_REF stays pinned forever — fine.
- Multi-OOTP-version L_REF coexistence within a single save. If the user installs OOTP 28 and refreshes, the old OOTP-27-vintage L_REF is overwritten (with the prior `source_path` retained in settings as audit trail).

**Implementation pin** (Slice 1 shipped 2026-05-14):

The freeze convention is implemented in `src/diamond/schema/l_ref.py`. Provenance lives in `_diamond_settings` under the keys `lref.frozen_at` (ISO timestamp), `lref.source_root` (install-folder path string), `lref.ootp_version` (e.g. `"27"`), `lref.table_count`, and `lref.files_json` (JSON map of `source_rel → {mtime, sha1, size_bytes, rows}`). The freeze gate is `is_lref_frozen(con)` which checks `lref.frozen_at` only — a user who manually drops a `lref_*` table can re-trigger ingest by clearing that setting, but normal ingest is purely additive. Refresh path (`diamond ingest --refresh-lref`) computes a SHA1 diff via `compute_lref_diff()`, prints a kind-grouped summary (added/changed/removed/missing_source), then re-ingests only changed files via `_do_ingest(con, install_root, only=<set of source_rels>)` and updates `lref.files_json` + `lref.last_refresh_at`. Empirically: first ingest of "Building the Green Monster" on 2026-05-14 loaded 27 tables / 575,587 rows and stamped `frozen_at=2026-05-09T16:55:28`; second invocation skipped silently; `compute_lref_diff()` returns `[]` against the install folder unchanged.

## D28 — Save-folder data: stay on dump CSVs as primary; defer L_NEWS

**Date**: 2026-05-13 (evening, paired with the save-folder deep-dive)

**Decision**: After a meticulous deep-dive of `<save>/<save_name>.lg/`, Diamond commits to keeping the **monthly dump CSVs as the primary data source** for all stat / ratings / state data. The save-folder offers richer alternatives in three specific domains, but they're **deferred until a UX need pulls them in** rather than swapped in proactively.

This decision pins:

1. **Box scores HTML and replays are EPHEMERAL — never depend on them.** Empirically verified: `news/html/box_scores/*.html` and `replays/*.rpl` use `game_id` numbering that resets at season start. The entire folder gets rewritten annually as new game_ids land on the same numbers. Mtime histogram of 18,982 box scores in this save shows 18,935 touched in a single recent batch; sampled box scores at game_id positions 1, 100, 1000, ..., 18982 are ALL dated 2029 regardless of position. **All structured data displayed in box scores is already in our dumps** (`games.csv` + `games_score.csv` + `players_game_*.csv` + `players_at_bat_batting_stats.csv` → `f_pa_event` multi-year via D19). HTML box scores are OOTP's pre-rendered VIEW; we render our own from dump data.
2. **`messages/` folder is dropped.** Per user preference — its content overlaps SQLite `league_news` with a different tag format; not worth maintaining two parsers.
3. **`temp/text_data.sqlite3` is acknowledged as a future augmentation source** — empirically stable across 4 seasons in this save, but lives under `temp/` which is a yellow flag for long-term dependence. Three specific uplift areas catalogued in DATA_NOTES.md "Side-by-side" table:
   - **Movements augmentation** — SQLite `league_transactions.transaction_type` is OOTP's authoritative classification (sign / release / trade / call-up / send-down / DFA / Rule 5). Our `f_l3_player_movements` currently INFERS this from snapshot diffs. Joining SQLite would replace the heuristic.
   - **Player career bio timeline** — `player_history` (314,678 dated rows) gives per-player narrative event timelines (drafted from school X, signed bonus Y, traded to Z). No dump equivalent. New capability for the player page.
   - **League / team news headlines** — `league_news` (16,718) + `team_news` (43,206) give a real news feed. No dump equivalent. Cockpit ticker / per-team feeds.
4. **OOTP-internal binary `.dat` files are ignored.** `players.dat`, `retired.dat`, `faces.dat`, `teams.dat`, etc. are working state that OOTP projects to dump CSVs already; we get the projection.
5. **`settings/db_monthly_dump_csv.cfg` is documented but not auto-modified.** This file controls what tables OOTP exports per dump cycle. Toggles `73-75` (ratings modes), `79-80` (messages), `81` (game_logs) are OFF by default. We don't auto-flip them on the user's behalf — too invasive. Future option: a setup-wizard checkbox that offers to enable specific toggles.
6. **Dump cadence is left at user's chosen value.** OOTP supports Manual / Daily / Weekly / Monthly / End-of-season. The `RefreshButton.tsx` + `/api/admin/dump-status` polling auto-detects whatever cadence the user picks. Diamond doesn't push for daily dumps unless a UX need drives it.

**Why defer L_NEWS rather than ship it now**:

- L_REF (D26 + D27) is committed and ready to implement; layering L_NEWS on top of an unimplemented L_REF risks scope creep.
- The three uplift areas are augmentations (better movements classification, new bio timeline, new news ticker) — none are blockers for current functionality.
- The SQLite's stability is empirically encouraging but the `temp/` path leaves room for future surprise; we'd want to mirror into our own DuckDB tables before depending on it. That mirror layer is itself ~half the work of L_NEWS.
- User explicitly chose to keep monthly dump cadence (vs flipping to weekly/daily) — strong signal that "intramonth freshness" isn't the priority right now.

**What we WILL do** (the current decision):

- Document the findings exhaustively in DATA_NOTES.md (the full save-folder catalog, the SQLite content table, the empirical stability evidence, the side-by-side comparison) so the option is fully spelled out for future-Claude.
- Add L_NEWS as a deferred slice in BACKLOG.md with the same per-save mirror pattern (append-only by source `*_id`, not freeze-at-first like L_REF).
- Keep the architecture decision-pinned via this D28 entry so future-Claude doesn't re-litigate or accidentally depend on ephemeral box scores.

**Architectural commitments** (binding):

- **Dumps remain the single source of truth for structured data.** Anything CSV-shaped that exists in dumps gets read from dumps.
- **Never ingest box score HTMLs as a stable archive.** If a per-game detail page is ever needed, render from `games + games_score + players_game_* + f_pa_event` JOIN.
- **Never depend on `replays/*.rpl`.** Pitch sequences (if ever needed) are derivable from `players_at_bat_batting_stats.csv`.
- **L_NEWS, when implemented, is per-save append-only mirror** — copy SQLite rows into per-save DuckDB tables keyed by source `*_id`, never re-read old rows. Independent of OOTP's `temp/` retention. Different from L_REF which is per-save freeze (D27).

**Cross-references**: D2 (per-save warehouse path), D8 (per-save reconciliation), D19 (multi-year `f_pa_event` PK with year disambiguation — same `game_id` recycling story), D24 (photo cache revalidation — file-rewrite-aware pattern), D26 (L_REF reference layer), D27 (L_REF per-save freeze).

**Out of scope for v1**:

- Auto-flipping `db_monthly_dump_csv.cfg` toggles. User-respect — they configured it.
- Suggesting users flip OOTP's dump cadence away from monthly. If needed, we can recommend in `docs/DEV.md` later.
- Reverse-engineering the binary `.dat` files. The CSV projections cover everything we need.
- Reverse-engineering the binary `.rpl` replay format.

## D29 — L_REF rollout: analytical slices shipped, cosmetic deferred (2026-05-14)

**Date**: 2026-05-14 (EOD, paired with the L_REF Slice 2-6 marathon)

**Decision**: After shipping L_REF Slices 1 (ingest+freeze), 2 (xwOBA/xBA/xSLG calc-parity), 3 (era park factors w/ LH/RH splits), 4 (era_stats source swap), 5 (MiLB pre-save baselines), and 6 data-layer (/api/parks), we close the L_REF rollout's analytical phase. Remaining slices (7 OOTP↔Lahman crosswalk, 6 frontend refactor, 8 logos, 9 HoF plaques, 10 brand colors) are either skipped, deferred, or partially blocked.

**What's now end-to-end OOTP-canonical**:

- League constants for advanced stats — `lref_era_stats` (MLB, 1870-2025) + `lref_era_stats_minors` (MiLB AAA/AA/A+/A, 1901-2024)
- Park factors with handedness splits — `lref_era_ballparks` (3,105 historical park-seasons, 1871-2025)
- Per-BIP expected stats — `lref_xwoba_table` + `lref_xba_table` + `lref_xslg_table` ((LA, EV) → x-stat grids)

Pre-save advanced stats (wOBA / wRC+ / OPS+ / FIP / ERA+) for any player-season — MLB or MiLB, real-history or save-era — now read every reference value from L_REF, frozen with the save per D27. There is **no remaining external-fetch dependency for advanced-stat calculation**. Lahman/BREF/Statcast fetches via `diamond fetch-history` are still used by per-player record / award / HoF leaderboards (different consumers, not the analytical surface).

**Why some slices were skipped**:

- **Slice 7** (Master.csv replaces Chadwick): blocked by data shape. `lref_master` carries `playerid` ↔ `lahmanID` ↔ `retroID` ↔ `BBrefMiLBid` (minor-league) but no `mlb_id` and no `BBrefMLBid`. Current Chadwick consumers (HoF MLB-API integration, awards leaderboard) all go from `mlb_id` → `bbref_id`, which lref_master can't satisfy. Master.csv complements but doesn't replace Chadwick. Closing Slice 7 as skipped; if a future slice needs the bio enrichment (birth/college/draft-value etc.), revisit then.
- **Slice 10** (per-team brand colors): blocked by misframed source. `colors/*.xml` files turn out to be uniform-asset metadata pointing to `.oi` PNG files (caps/jerseys/pants/socks), NOT hex/RGB color palettes as D26 suggested. No parseable color data available in the install folder. Either source from the team logo PNGs via image-processing (substantial work) or leave brand colors out of v1.

**Why the cosmetic remainder is deferred**:

- **Slice 6 frontend refactor** (delete `web/lib/stadiums.ts`, switch `StadiumSprayChart` to API + 7-segment renderer): touches the renderer's geometry model deeply. Data layer (`/api/parks`) shipped; frontend stays on hand-coded 5-point geometry until viz polish pass.
- **Slice 8** (team logos): real cosmetic win — replaces `font-mono BOS` chips across 5+ pages with `<TeamLogo>` rendering OOTP's `.oi` PNG files. Requires manual team_abbr → filename catalog plus `/api/logos/{abbr}` route plus React component. ~45 min of focused frontend work.
- **Slice 9** (HoF plaques): cosmetic win on `/history/hof`. Needs `lref_master.hofID` → bbref crosswalk + `/api/hof/plaque/{bbref}.png` route + UI rewiring.

These are tracked in BACKLOG.md as deferred items. They don't unblock new analytical capabilities; they elevate the IA visually.

**Implementation pin**: post-Slice-5 row counts (verified on Building the Green Monster):
- f_player_season_advanced_batting still 244,183 rows total
- Of those, ~172k now have non-null wOBA (was ~88k pre-Slice-5; +84k newly resolved in pre-2026 MiLB)
- Imported view (`_lg_constants_advanced_imported`) row count: 1,069 (was 155 MLB-only — now includes 11 MiLB leagues × 60-124 yrs each)

**Cross-references**: D26 (L_REF layer), D27 (per-save freeze), D20 (MLB pre-save baselines — now superseded by Slice 4), D22 (park factors — now superseded by Slice 3).

**Out of scope**:

- Reverse-engineering OOTP's `(LA, EV) → LSA` classifier so we can use `lref_xiso_table` for OOTP-empirical barrel/SS/HH definitions. Defer until UX needs xISO specifically.
- RE24 / WPA / LI columns on `f_pa_event` from `lref_re288_table` + `lref_wpa_table` + `lref_li_table`. Pure additive work, ~half-day, would unblock high-leverage / clutch leaderboards. **NOTE: shipped as D30 Slice A on 2026-05-15.**
- Pitcher-side handedness park factor application (currently uses Overall — needs (pitcher_throws, league-year) opposing-batter mix model).


## D30 — Capability wave: leverage stack + real assets + canonical geometry

*2026-05-15*

**Decision**: Following D29's L_REF rollout (data trust + completeness), ship a focused **capability + polish** wave: leverage stack (WPA / LI / RE24 / Clutch), real OOTP team logos, OOTP-canonical spray-chart geometry, real HoF plaques. Four slices, one session.

**Why now**: Post-D29 the platform was *trustworthy* (every reference value OOTP-canonical, frozen with the save) but not visibly more capable than the day before. Users browsing 1972 PCL leaderboards or comparing in-game UI to ours noticed the trust improvement; users browsing the modern save did not. The next high-leverage move is therefore visible new capability — surfaces that wouldn't exist without OOTP's per-PA + per-game leverage values, the install-folder image assets, and the L_REF park geometry.

**Slice A — leverage stack** (`l3_leverage.py`, ~370 LOC):

- Two new fact tables `f_player_season_leverage_batting` (32,767 rows) + `_pitching` (32,338) at the same (player, year, league, level) grain as `f_player_season_advanced_*`.
- **WPA** sourced from L0 game-event tables (`players_game_batting_event.wpa`, `players_game_pitching_event.wpa`) — OOTP supplies per-game-per-player and we sum to season. Coverage caveat: L0 game-events are **current-year-only** in the dump (OOTP overwrites on rollover); so WPA fills only 2029 rows in this save. Multi-year WPA would require persisting per-PA win-probability computation against `lref_wpa_table` — additive future slice.
- **LI** for pitchers from L0; empirically decoded that OOTP's per-game `li` is the SUM of leverage across PAs faced, not the per-PA average. Season Tango LI = SUM(li) / SUM(bf), verified against league avg ≈1.05 (Tango spec 1.0), top closers Martinez 2.41 / Edwin Díaz 2.35 (real-MLB 1.7-2.0+), starters Gilbert 0.88 / Skubal 0.97 (real-MLB 0.85-1.10). Batter LI deferred — the L0 batter event has no LI column; would need to derive from `lref_li_table` (variable-width score-diff columns to decode).
- **RE24** computed per-PA from `f_pa_event` joined to `lref_re288_table` (24-row × 12-count grid UNPIVOTed to long form). Per-PA contribution = `RE_after - RE_before + rbi` (where RE_after comes from a `LEAD()` over game_id+inning+batter_team_id ordered by pa_in_game_seq, NULL → 0 for inning-end). Multi-year — fills 2026-2029 across both batter and pitcher sides (~7,200-7,800 player-seasons per year). Pitcher RE24-against = `-SUM(RE24 keyed on pitcher_id)`.
- **Clutch** = WPA / LI per Tango. Pitcher-only for v1 (depends on LI); guards against LI < 0.10 (mop-up only).

Wire-up: `PlayerAdvancedBattingRow` / `PlayerAdvancedPitchingRow` schemas gain leverage fields; `/api/players/{id}` LEFT JOINs the leverage tables; leaderboards catalog gains 6 entries (WPA, RE24 batter side; WPA_pit, LI, Clutch, RE24_pit pitcher side); 4 dictionary entries with KaTeX formulas. PlayerStatsTab shows signed display for WPA / RE24 / Clutch (`+5.81 WPA`).

Verified: Eldridge 2029 WPA +5.81 / RE24 +49.4 (top in MLB); Crochet RE24-against trajectory 21.8 → 28.8 → 17.3 → 8.3 across 2026-2029 (declining quality, matches FIP trajectory); Yesavage 2029 Clutch +3.61 (Cy-tier).

**Slice B — real OOTP team logos** (5 surfaces):

- `GET /api/photos/teams/{team_id}.png?size=N` reads `teams.logo_file_name` from the warehouse, snaps the size param to OOTP's nearest pre-rendered variant (16/25/40/50/110/full), streams from `<save>/news/html/images/team_logos/`. Same revalidation pattern as the player headshot route (D24). Strict filename allowlist + integer team_id validation = no traversal vector. Falls back to full-size if requested variant doesn't exist.
- New `<TeamLogo teamId={...} abbr={...} size={...} />` component with abbr-pill fallback on 404 / network failure. Sizes xs/sm/md/lg/xl forwarding the px to the `?size=N` query param so we hit the closest pre-rendered variant on disk (smaller payload, no client-side downscale).
- Wired into: cockpit standings strip, cockpit spotlight cards (`CockpitSpotlightCard` schema gains `team_id`), league standings rows, movements ledger (`<MoveArrow>` puts logos on either side of the from→to arrow, handling all 4 direction shapes), leaderboards team column, player page bio header.

**Slice C — spray chart sources OOTP-canonical 7-segment geometry**:

- `StadiumSprayChart` accepts a `parksApi` prop carrying `/api/parks` (240 parks from `lref_pt_ballparks`). Adapter `stadiumFromApi` converts 7-segment OOTP geometry to the renderer's 5-point spline (LL→lf_line, LCF→lcf, CF→cf, RCF→rcf, RL→rf_line) + matching wall heights.
- Hand-coded `web/lib/stadiums.ts` remains as fallback for missing parks + cosmetic feature flair (Green Monster / ivy / splash hits / etc. — those stay hand-coded since they're cosmetic). Picker dropdown populates from the merged catalog.
- `getParks()` exported in `lib/api.ts`; player page fetches in parallel with player + glossary + batted-balls + save. Tolerant of failure.
- Verified Fenway: API returns LL=310 / LCF=379 / CF=390 / RCF=383 / RL=302 + walls 37/9/3 — matches the existing hand-coded distances within 1-3 ft and corrects the dead-CF wall (9 OOTP-canonical vs 17 hand-coded — 17 was the LCF triangle, not dead-CF).

**Slice D — real HoF plaques on /history/hof**:

OOTP ships ~8 marquee Cooperstown plaque PNGs in `<install>/hof/` (Bagwell, Carter, Ford, Gibson, Griffey Jr, Kaline, Sandberg, Ozzie Smith), each 5-8 MB at full resolution. Three pieces:

1. `GET /api/photos/hof/{bbref_id}.png` streams from the install folder (NOT the save) with the same revalidation pattern. Strict bbref_id allowlist (`[a-z0-9.]{1,12}` — covers Lahman's `.` placeholder for double-initial pads like `sabatc.01`).
2. `GET /api/photos/hof` manifest enumerates the bbref_ids that actually have a PNG on disk, joined to OOTP's `index.json` metadata (name + induction line). The frontend uses this to render only the gallery slots that will load — skips 192 of 200 inductees that would 404-spam.
3. `HofPlayer` schema gains `bbref_id` field, populated via name + birth-year-disambiguated JOIN against `history_lahman_people`. Resolves for hundreds of real-life HoFers (Cabrera, Pujols, Cano, ...) even though only 8 plaques ship — sets up future plaque additions to Just Work without schema changes.

Frontend: `/history/hof` (inductees view) gets a horizontal-scroll plaque gallery above the table. Each thumbnail (140×180 px, lazy-loaded) shows player name + induction line; clicking deep-links to `/player/{id}` when resolvable, else opens the PNG in a new tab. 7 of 8 plaques deep-link in our save (Griffey Jr is the outlier — only Sr is in this save's data).

**Bbref id format note**: Lahman's bbref convention uses `.` as a placeholder for double-initial pads (`sabatc.01` for CC Sabathia). Our regex allows it. Path traversal still blocked because `/` and `\` are excluded — the worst input that matches the regex is something like `..somefile`, which becomes `..somefile.png` after string concat — a literal filename in the `hof/` directory, not a parent traversal.

**What this wave doesn't change**:
- Modern save advanced stats — no calculation path was modified, only surfaces added. Existing wOBA / wRC+ / OPS+ / FIP / WAR values invariant.
- Pre-D29 trust improvements — those landed in Slices 1-5 of D29.
- Cosmetic CB-mode coverage — verdict glyphs still use green/amber/rose.

**Cross-references**: D24 (revalidation-based image cache pattern, applied to team logos + plaques), D26 (L_REF layer source), D27 (per-save freeze — plaques and logos read from install folder so they're not "frozen" but they're also not save-data; OOTP doesn't patch logo files mid-save), D29 (parks API and `lref_re288_table` are L_REF assets this wave consumes).

**Out of scope** (deferred to BACKLOG.md):
- Multi-year batter LI from `lref_li_table` (5-column variable-width score-diff format needs decoding pass).
- Multi-year WPA from `lref_wpa_table` (would require persisting a per-PA win-probability calc independent of L0 game-event aggregation).
- Pitcher-side handedness in park-factor application (still uses Overall; needs (pitcher_throws, league-year) opposing-batter mix model).
- xISO classifier via `lref_xiso_table` 6-zone LSA mapping.
- Inline plaque thumbnails per inductee row (each plaque is 5-8 MB; the gallery approach keeps initial-render bandwidth manageable).


## D31 — Metabase as Diamond's chart-building / BI surface (Pattern A)

*2026-05-15*

**Decision**: Embed Metabase (self-hosted, free, OSS) inside Diamond as the modern chart-building / BI workshop. Metabase runs as a local Java process at `localhost:3000` (or `:3001` to avoid the Next.js port collision); Diamond's `/explore` page has a new **Workshop** tab that iframes it. Metabase reads the same DuckDB warehouse Diamond does via the community DuckDB driver (MotherDuck-maintained).

**Architecture: Pattern A — single Database connection follows the active save**.

Metabase has exactly one Database registered (id=1). Its `details.database_file` always points at the **active save's** DuckDB. When the user switches saves in Diamond's UI (`POST /api/saves/active`), the handler also calls `repoint_active_save()` in `src/diamond/api/metabase.py` which:

1. PUTs the new path to Metabase's Database 1
2. POSTs to `/sync_schema` to refresh field fingerprints

Schema stability is the load-bearing assumption — every Diamond save has the same warehouse schema (L0 → L_REF identical), so Metabase's field IDs (which cards reference) stay valid across save swaps. Cards continue to work; only the underlying data changes.

**Why Pattern A over Pattern B (per-save Databases)**:
- Solo workflow: one save active at a time, never side-by-side comparison
- Cards / dashboards built once, work for every save
- Pattern B is the escape hatch for genuine multi-save analysis — manually register a second Database in Metabase admin; the two patterns coexist

**Why Metabase over alternatives** (full thread in conversation log):

- **Power BI** would need either Azure Embedded ($) or "publish to web" (cloud upload). Both violate D16 ("local-first; your save data never leaves your machine"). Metabase self-hosts.
- **SQL Server warehouse** would lose D2 (per-save portability) and D27 (freeze-at-first ingest). The clean per-save DuckDB file is non-negotiable. Pure cost; no benefit since DuckDB ODBC works for Power BI / Tableau / Excel anyway.
- **Custom Vega-Lite chart builder** is ~6 days of work and doesn't beat Metabase for general BI. Metabase has 30+ chart types, drag-and-drop encoding shelves, calculated fields (DAX-equivalent), drill-through, dashboards, parameters, etc., all built. Metabase's API also lets Claude build dashboards programmatically — versionable, reproducible.
- **Metabase**: free (OSS), self-hosted, embeds via iframe (with proper sandbox attrs), connects to DuckDB via community driver, full BI surface.

**Implementation summary**:

1. **`~/.diamond/metabase/`** install location (alongside `active_save.toml`, AI keys, etc.)
   - `metabase.jar` (Metabase OSS 0.59.10, ~520 MB)
   - `plugins/duckdb.metabase-driver.jar` (driver 1.5.2.0, ~84 MB)
   - `data/` (H2 metadata DB — cards, dashboards, user accounts; save-agnostic)
   - `logs/`
   - `metabase.bat` launcher with safety env vars (localhost-bind, telemetry-off, update-check-off, sample-content-off, 2GB heap)

2. **`src/diamond/api/metabase.py`** — coordination module
   - `_get_session()` reuses cached session token at `~/.diamond/metabase_session.txt`, refreshes on 401
   - `_load_credentials()` reads email/password from `~/.diamond/metabase_credentials.toml`
   - `repoint_active_save(save)` — PUTs the new database_file + triggers sync; **best-effort**, never raises, returns a status dict for logging

3. **`src/diamond/api/routes/saves.py`** — extended `POST /api/saves/active`:
   - After `set_active_save()`, calls `repoint_active_save()` and logs the result
   - If Metabase isn't running or credentials are missing, save switch still succeeds; Metabase coordination is opt-in

4. **`web/app/explore/page.tsx`** — refactored to two modes:
   - `?mode=quick` (default) — Diamond's existing curated `ChartBuilderClient` (scatter / histogram, ~38 stat catalog)
   - `?mode=workshop` — `MetabaseWorkshop` component iframes Metabase
   - `ExploreModeTabs` pill component for switching

5. **`web/components/MetabaseWorkshop.tsx`** — client component:
   - Liveness probe via `fetch('/api/health', mode: 'no-cors')`
   - On Metabase down: renders cold-start guide with `metabase.bat /b` instructions
   - On up: renders iframe with proper sandbox attrs (`allow-forms allow-scripts allow-same-origin allow-popups allow-downloads`), 85vh height, "Open full-screen" link

6. **`docs/METABASE.md`** — install, config, ops, troubleshooting, threat model, AI-assisted dashboard workflow

**Coverage notes**:

- **Save-aware queries**: cards filtered by year / level / league_id / position / age work across saves (these are save-stable concepts).
- **Player-specific cards**: hardcoded `player_id` references break across saves (player IDs aren't stable). Build save-specific drill-downs in Diamond's existing player page; build save-agnostic cards in Metabase.
- **Don't ingest while Metabase has the DB open**: read lock can collide with `diamond ingest`'s write lock. Documented in METABASE.md ops section.
- **Port collision**: Diamond's Next.js dev server uses `:3000` by default; Metabase also defaults to `:3000`. Override `MB_JETTY_PORT=3001` in `metabase.bat` and set `NEXT_PUBLIC_METABASE_URL=http://localhost:3001` in `web/.env.local` to resolve.

**Threat model** (single-user local):

- Bound to `127.0.0.1` only — no remote attack surface
- Telemetry off, update-check off — zero outbound calls
- DB connection in read-only mode
- OOTP video game stats, no PII / financial data
- Realistic worst case: "Metabase has a bug and crashes" (annoying, not dangerous)

**Future v2 deferrals**:
- `diamond metabase deploy` CLI subcommand reading YAML dashboard specs and POSTing to Metabase API. Source-controlled dashboards. Currently dashboards live only in Metabase's H2 metadata DB (which survives save switches but isn't repo-tracked).
- Pre-built starter dashboards (leaderboards, distributions, career arcs, team summary, pressure cohort, rookie tracker) shipped as YAML in the repo + auto-deployed on first run.
- AI-assisted "build me a chart" workflow — Claude POSTs to Metabase API directly, returning question/dashboard URLs. Already proven in spike (5 cards + 1 dashboard built in ~8 min).

**Cross-references**: D2 (per-save warehouse), D3 v2 (save switcher), D16 (local-first), D24 (revalidation pattern reused), D27 (per-save freeze model — Metabase's metadata is parallel: per-user, never frozen).


### D31 addendum — same-day corrections (iframe → launcher, port flip)

*2026-05-15 evening, three corrections to the morning's D31 implementation.*

**1. Port collision: Metabase moved 3000 → 3001.**

D31's morning launcher script bound Metabase to `:3000`, same as Diamond's Next.js dev server. The collision caused the Workshop iframe to recursively load Diamond's own cockpit when Metabase couldn't bind. Resolved by moving Metabase to `:3001` everywhere:

- `~/.diamond/metabase/metabase.bat` — `MB_JETTY_PORT=3001`
- `src/diamond/api/metabase.py` — `METABASE_URL = "http://127.0.0.1:3001"`
- `web/components/MetabaseWorkshop.tsx` — default `http://localhost:3001`, with `NEXT_PUBLIC_METABASE_URL` override

Commit `0f3d4ff`.

**2. Inline-async-child SSR exception in `/explore`.**

The morning's `/explore` page had an inline `async function QuickChart` rendered conditionally:

```tsx
{mode === "workshop" ? <MetabaseWorkshop /> : <QuickChart sp={sp} />}
```

Next.js App Router can be flaky composing inline async server components conditionally — the symptom is a "server-side exception" toast at runtime even when TypeScript passes. Fixed by hoisting the data fetch into the top-level page component and returning early for workshop mode (which doesn't need the chart-builder API call at all).

Commit `68ae5ce`. Side benefit: workshop mode no longer wastes a round-trip on each entry.

**3. Iframe → launcher pivot (the architectural correction).**

D31's morning shape had `MetabaseWorkshop` rendering an iframe to Metabase. **This doesn't work on Metabase OSS.**

Metabase ships these headers by default:
- `X-Frame-Options: DENY`
- `Content-Security-Policy: ...; frame-ancestors 'none';`

Allowing iframe embedding from a different origin requires Metabase's "interactive embedding" feature, which is **paid Pro only**. Confirmed via API:

```
PUT /api/setting/embedding-app-origins-interactive
→ "Setting embedding-app-origins-interactive is not enabled because
   feature :embedding is not available"
```

Three paths considered:
- (A) Upgrade to Metabase Pro — paid; doesn't fit Diamond's local-first single-user model
- (B) Reverse-proxy through FastAPI to strip the headers — fragile (websocket support, complex routing); also possibly violates Metabase's TOS
- (C) **Launcher pattern** — Workshop tab opens Metabase in a new browser tab instead of iframing it. Same shape as Tableau Desktop / Power BI Desktop integrations against any web app

**Picked (C).** This is the same end state every BI-sidecar integration ships in practice. Functional equivalence:

| Property | iframe (would-be) | launcher (shipped) |
|---|---|---|
| Same DuckDB warehouse | ✓ | ✓ |
| Pattern A save-switching | ✓ | ✓ |
| AI-assisted dashboard build via API | ✓ | ✓ |
| Visual integration in Diamond | inside iframe | one-click new-tab |
| Full Metabase UI | ✓ (if Pro) | ✓ (full-screen, more space) |
| Cookie / CORS / sandbox edge cases | many | none |

Implementation:

- **`web/components/MetabaseWorkshop.tsx`** — launcher card with three deep-link sub-cards:
  - "New question" → `/question/new`
  - "Sample dashboard" → `/dashboard/1`
  - "Browse warehouse" → `/browse/databases/1`
  - Plus a status footnote showing which save's DB is active in Metabase right now
- **`GET /api/admin/metabase-status`** (new endpoint) — same-origin liveness probe replacing the cross-origin no-cors fetch. Returns `{running, configured, active_save_db, message}`. The frontend probes Diamond's API (no CORS dance) which probes Metabase server-side.
- **Cold-start guide** — when Metabase is down, the launcher flips to install/restart instructions (`metabase.bat /b`).

Commit `2b3f03f`.

**Lesson**: should have checked X-Frame-Options on Metabase OSS *before* writing the iframe component. The pivot itself was 30 minutes of code; the iframe scaffolding was wasted work. For future "embed product X" decisions, validate the embedding headers / licensing first, design the integration second.

**No revision to D31's main thesis** (Pattern A, Metabase as BI workshop, save-aware sync) — those all hold. The corrections are tactical: which port, how the page component composes, iframe vs launcher.

---

## D32 — Native desktop shell: PySide6 + PyInstaller (no browser, no consoles)

**Date**: 2026-05-15 (evening)
**Decision**: Wrap Diamond in a native Windows desktop shell. One double-click on `Diamond.exe` opens a single titled window (PySide6 QMainWindow + QWebEngineView) pointing at the local Next.js URL; FastAPI runs in an in-process uvicorn thread; Next.js runs as a hidden `node server.js` subprocess. Closing the window kills both backends cleanly via a Windows Job Object. No browser tab, no flapping cmd windows, no zombie processes. Single-instance enforcement via named mutex.

**Why**: The dev workflow (two visible cmd windows + a browser tab) is fine for engineers but wrong for the actual use case. Diamond is a single-user local-first analytics tool; the user wants it to feel like Tableau Desktop / Power BI Desktop / a native app — not a service-stack you have to manually orchestrate. The browser-tab + flapping consoles were an artifact of the dev path leaking into production.

**Stack picked**: PySide6 (Qt6) + QtWebEngine (bundled Chromium) + PyInstaller for the bundle.

**Alternatives considered**:

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Tauri 2 (Rust)** | Tiny bundle (~15MB), modern toolchain, first-class Mac/Linux | Adds Rust to the build chain; tooling tax for a Python-heavy team | Defer until cross-platform matters |
| **Electron** | Mature, battle-tested | ~150MB bundle (Chromium), heavyweight for a single-user local app | No |
| **pywebview (WebView2)** | Smaller bundle (~30MB; uses OS WebView2), well-established | **Hard `pythonnet` dep on Windows; no Python 3.14 wheel; build-from-source needs .NET toolchain.** Also imposes "user must install WebView2 runtime" on Win10 boxes. | No (blocked by 3.14) |
| **PySide6 + QtWebEngine + PyInstaller** | `cp310-abi3` wheel works across Python 3.10+ (3.14 included). Bundled Chromium = no end-user WebView2 install. Direct Qt API gives native menus / tray / signals without an indirection layer. | ~80MB Qt bundle. Heavier than Tauri/pywebview. | **Picked** |
| **Static-export Next.js** | Simpler — one fewer subprocess | Massive refactor: every page is `force-dynamic` + uses server components; would need full migration to client-side fetch | No |

**Note on the pywebview rejection**: the original 2026-05-15 evening implementation tried `pywebview` and hit `ModuleNotFoundError: pythonnet` immediately (Python 3.14 has no wheel; source build needs nuget + .NET). `pywebview[qt]` extras still pulls pythonnet at base on Windows, so we couldn't even get to the Qt backend through pywebview. Direct PySide6 sidesteps the entire chain — and is actually a cleaner architecture (no "what backend is pywebview picking?" mystery, full Qt API access).

**Architecture (single-window-morph pattern)**:

1. **Single-instance lock** — `CreateMutexW("Local\\Diamond.OOTP.Desktop.SingleInstance")`. Second double-click sees `ERROR_ALREADY_EXISTS`, calls `FindWindowW` + `SetForegroundWindow` on the existing window, exits.
2. **Job Object** — `CreateJobObjectW` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Every spawned child PID gets `AssignProcessToJobObject`. A hard-killed launcher (Task Manager / power loss / PyInstaller crash) takes its kids down with it. **Eliminates the "stale process on :3000" failure mode entirely** — no more `kill-stale.bat` needed.
3. **Single window with morph** — one `QApplication` + `QMainWindow` + `QWebEngineView`, initialized with splash HTML at the final size (1600×1000). A background daemon thread runs sidecar boot (`start_sidecars`); when both ports are reachable, it emits a Qt signal (`signals.urlReady`) carrying the URL. The slot runs on the GUI thread (Qt auto-marshals via the meta-object system) and calls `view.load(QUrl(...))`. The user sees a polished loading screen for the 3-5s cold-start window, then the app appears atomically.
4. **uvicorn in-thread** — FastAPI runs as a daemon thread inside the launcher process via `uvicorn.Server.run()`. No subprocess. Works inside PyInstaller bundles (no need for `python.exe` on PATH).
5. **Next.js as hidden subprocess** — `node server.js` against the standalone build (`output: 'standalone'`). Spawned with `creationflags=CREATE_NO_WINDOW` so no console pops up. Requires `node` on PATH (acceptable for v1; a later slice could bundle Node).
6. **Tray icon** (pystray) — runs in a daemon thread. Menu: Show / Open Metabase / API docs / Quit. Optional and fail-soft (`--no-tray` disables; missing pystray skips silently).
7. **No WebView2 dependency** — QtWebEngine ships its own Chromium runtime. End-users on Win10 don't need to install the Microsoft WebView2 runtime separately.

**Build pipeline**:

```
make install-desktop    # pip install -e ".[desktop]"  (PySide6, pystray, PIL, pyinstaller, psutil)
make desktop            # next build (standalone) + copy static + copy public + python -m diamond.desktop
make desktop-package    # ↑ + PyInstaller → dist/Diamond/Diamond.exe
```

`scripts/build_desktop.py` orchestrates; `src/diamond/desktop/diamond.spec` is the PyInstaller spec.

**One-folder, not one-file**. PyInstaller can produce a single .exe but it unpacks to TEMP on every launch — the Next.js standalone tree is ~thousands of small files, adding 2-3s to cold-start. One-folder bundle ships a `dist/Diamond/` directory with `Diamond.exe` at the root; an installer (Inno Setup / MSIX) wraps it for distribution.

**Files**:

```
src/diamond/desktop/
  __init__.py            module docstring
  __main__.py            python -m diamond.desktop entry
  launcher.py            argv parse + lifecycle orchestration
  paths.py               source-vs-frozen path resolution
  sidecar.py             uvicorn-thread + Next.js subprocess + port probes
  single_instance.py     Win32 named mutex + FindWindow/SetForeground
  win_jobobject.py       ctypes Job Object wrapper
  splash.py              loads assets/splash.html (load_url morph)
  tray.py                pystray icon + menu
  diamond.spec           PyInstaller one-folder spec
  assets/
    splash.html          dark-themed loading screen
    tray_icon.png        (optional; runtime PIL fallback if absent)
    diamond.ico          (optional; spec picks up if present)

scripts/build_desktop.py    next build + asset copy + (optional) PyInstaller
```

**What this changes for the user**:

- Double-click `Diamond.exe` → splash window in ~200ms → main window in ~3-5s. No browser, no terminals.
- Close the window → process tree empty. No leftover uvicorn / node / DuckDB locks.
- Tray icon (taskbar notification area) → Show / Metabase / Quit.
- Second double-click while running → focuses the existing window (no duplicate).
- Hard-kill via Task Manager → Job Object kills the children too. **`kill-stale.bat` is deprecated** for the desktop path (still useful if the user runs `dev.bat` and crashes the dev terminals).

**What stays unchanged**:

- `dev.bat` and the two-terminal hot-reload workflow — kept for engineering. Desktop shell is the **production user surface**, not a replacement for the dev path.
- Metabase Workshop launcher (D31) still opens in default browser. Acceptable: Metabase is the explicit "BI escape hatch", and rendering it in a separate QtWebEngine instance buys nothing.
- All API routes, schemas, theme system, dictionary, warehouse — zero touch.

**Tradeoffs**:

- **Bundle size** ~150-200MB. Most of that is the Python runtime (~25MB) + Next.js standalone tree (~30MB) + PySide6 + bundled Chromium (~80MB) + pystray + PIL. Heavier than a pywebview/WebView2 setup would have been, but the Chromium-bundled-in-Qt model is actually a feature for end-users (no separate WebView2 runtime install). Not optimizing further until distribution becomes a real concern.
- **Node still required** — we don't bundle Node.js v1. The user already has it for dev; an installer can pin a Node version later. This is the lowest-risk path; bundling Node would add ~50MB and require `nodemon`-style wrapping.
- **Mac/Linux story** — PySide6 works on both with the same API. Diamond is currently Windows-pinned (saves path is a hardcoded constant); when we cross-platform, this stack still applies. Tauri becomes attractive again only if bundle-size reduction is worth the Rust toolchain.
- **Dev iteration on the launcher itself** — `python -m diamond.desktop --dev` skips the build step and connects to the running `dev.bat` servers. Saves the ~30s rebuild cycle while iterating on launcher / tray / splash code.

**Failure modes and recovery**:

| Failure | Symptom | Recovery |
|---|---|---|
| Standalone tree missing | Splash → error HTML in window | `python scripts/build_desktop.py` |
| Node not on PATH | Splash → error HTML | Install Node 20+ |
| Port collision (rare) | `_free_port` finds an alternate | Auto-recovers |
| Hard-kill of launcher | (none) Job Object kills the kids | Relaunch |
| Sidecar boot timeout | Splash → error HTML after 45s | Check launcher logs |

**Pinned**: PySide6 + QtWebEngine (not pywebview/Tauri/Electron), one-folder PyInstaller bundle (not one-file), single-window-morph (not splash-then-main, not multi-window), Job Object + named mutex for lifecycle.

**Deferred to v2**: code signing (Windows SmartScreen friendliness), Inno Setup MSI installer for Start Menu integration + uninstall, auto-update via Tauri-style updater, Mac/Linux ports.

---

## D33 — AI sidebar with tool use, page context, GM-copilot modes, and Metabase card creation

**Date**: 2026-05-15 (late-evening + 2026-05-16)
**Decision**: Replace D14's single-button "Summarize career" with a full AI sidebar reachable from every page. Four-tier capability stack: (T1) page-aware chat with the current pathname/payload baked into the system prompt, (T2) read-only tool-using analyst with six tools wired into Diamond's warehouse + dictionary, (T3) GM-copilot quick-modes for call-up / trade / draft decisions, (T4) prompt-to-dashboard via Metabase REST API.

**Why**: D14 shipped as a v0.1 — one button, one player payload, no DB access, no follow-ups. The user pushed back ("seems quite limited and not really easy to find") and asked for the right architecture. Diamond is the perfect substrate for a real AI layer: stable warehouse schema, OOTP-canonical stat dictionary, Metabase wired in for visualizations. Skipping straight to T2-T4 instead of incrementally extending T1 lets us ship the actual valuable surface in one cohesive change.

**Architecture**:

1. **Sidebar** (`web/components/AISidebar.tsx`) — floating launcher button (`✦ Ask Diamond`, bottom-right) opens a 440px slide-out panel. Header shows current pathname as `ctx:`. Body is a scrollable thread with rich content blocks (text + tool_use + tool_result) rendered inline. Footer has four mode pills (Chat / Call-up / Trade / Draft) + a textarea + Send.

2. **Page context** (T1) — the sidebar reads `usePathname()` and posts `page_context.pathname` with every request. The route's system prompt prepends "the user is currently on /player/123" so a generic question like "is he struggling?" is grounded. Optional `page_context.payload` is reserved for richer per-page context (player profile, team summary) but not required v1 — the model can fetch via tools.

3. **Tools** (T2) — six tools, all in `src/diamond/ai/tools.py`:
   - `query_warehouse(sql)` — read-only DuckDB cursor, single-statement guard, forbidden-keyword regex (DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/...), default LIMIT 1000, 5s statement timeout.
   - `get_player(player_id)` — bio + career bWAR/pWAR.
   - `compare_players(player_ids)` — 2-5 players side-by-side.
   - `get_glossary(stat_id)` — definition + KaTeX formula + interpretation from `diamond.dictionary.STATS`.
   - `list_leaderboard_stats()` — discovery aid.
   - `create_metabase_card(name, sql, viz_type)` — POSTs to Metabase's REST API; returns `card_url`.
   Tools return `{"ok": False, "error": "..."}` on failure rather than raising — the model recovers gracefully.

4. **Tool loop** in `routes/ai.py:chat()` — translates frontend `ChatTurn` ↔ provider-native messages, drives the loop until `stop_reason != "tool_use"`. `_MAX_ITERATIONS = 6` cap. Returns every appended turn (assistant text + tool_use blocks + user tool_result blocks) so the UI can render the full reasoning chain.

5. **GM-copilot modes** (T3) — four `mode` values in `ChatRequest`: `chat` (default, generic), `callup`, `trade`, `draft`. Non-default modes prepend a structured prompt to the system prompt. The frontend's mode pills + the empty-state suggestions both wire into this.

6. **Prompt-to-dashboard** (T4) — `create_metabase_card` calls `diamond.api.metabase._get_session()` for the cached Metabase auth token, POSTs `{name, description, display, dataset_query: {type: "native", native: {query: sql}, database: 1}}` to `/api/card`. Returns `card_url`; the sidebar renders a green "✓ Created Metabase card" link the user can click to open it in their browser. Database id 1 is hardcoded per D31's Pattern A.

**Provider abstraction**: `AIClient.chat()` is a new abstract method on the existing D14 client. Anthropic adapter passes the Anthropic-shaped tool/messages format directly (already matches our internal shape). OpenAI adapter translates in both directions: tool_use blocks ↔ `tool_calls`, tool_result blocks ↔ `role: "tool"` messages. Both adapters emit our internal `{stop_reason, content[]}` shape so the route never has to branch.

**Safety**:

- **SQL is read-only**: regex-blocked DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/ATTACH/DETACH/COPY/EXPORT/LOAD/INSTALL/PRAGMA/VACUUM. Single-statement only. LIMIT 1000 default. 5s timeout. The DuckDB cursor itself is the same one the read-only routes use; not a new privilege escalation.
- **Tool errors don't crash the loop**: `{"ok": False, "error": ...}` flows back to the model which can recover.
- **Iteration cap**: 6 round-trips per request prevents runaway tool spirals.
- **No streaming yet**: synchronous request/response. Streaming is a v2 follow-up.
- **API keys stay in keyring**: existing D14 infra unchanged. The sidebar uses whatever provider/model the user configured at `/settings/ai`.

**Files**:

```
src/diamond/ai/
  client.py             AIClient gains chat() abstract method
  tools.py              new — 6 tool implementations + Tool dataclass + ToolContext
  adapters/anthropic.py adds chat() — Anthropic-native pass-through
  adapters/openai.py    adds chat() — translates messages + tool_calls in both directions

src/diamond/api/
  schemas/chat.py       new — ChatTurn / ChatContentBlock / ChatRequest / ChatResponse / PageContext
  routes/ai.py          adds /api/ai/chat endpoint + system-prompt builder + tool loop

web/
  lib/ai-chat.ts        new — sendChat() helper
  components/AISidebar.tsx new — full sidebar (~470 LOC)
  app/layout.tsx        wires <AISidebar /> into the root layout
```

**Tradeoffs**:

- **Latency**: tool-using turns can take 5-15s for complex questions (model thinks → tool runs → model summarizes). Non-streaming v1 means the user sees "Thinking…" until the whole loop finishes. Streaming would let us show intermediate reasoning live; deferred.
- **Cost**: full warehouse schema (~220 tables) isn't in the system prompt — model has to discover via `list_leaderboard_stats` + `query_warehouse(SHOW TABLES)`. Cheaper input tokens, slightly more round-trips. Acceptable for single-user; would refactor for multi-user.
- **No memory across sessions**: each new sidebar open starts a fresh thread. The "New" button explicitly resets. Conversation history is in component state only.
- **`create_metabase_card` requires Metabase to be running**: tool checks port 3001 + Metabase auth; returns `{"ok": False, "error": ...}` with a friendly message if not. The user sees the error inline and can click the Workshop tab (which now auto-launches Metabase per D32).

**Pinned**: tool-loop on the server (not client-driven), Anthropic-shaped internal message format (OpenAI translated in adapter), six-iteration cap, no streaming.

**Same-day follow-ups** (2026-05-16, all small, none in their own D-entry):

1. **Anthropic snapshot auto-migration** — D14's pinned default `claude-3-5-haiku-20241022` was retired by Anthropic, so `_get_session()` started 404'ing. `RETIRED_MODELS` map in `settings.py` rewrites stale model strings to `claude-haiku-4-5` on load; default flipped to the rolling alias to avoid future bit-rot. (Commit `061e2f6`.)
2. **`SET statement_timeout` removed from `query_warehouse`** — DuckDB 1.5.x has no such config param (it's Postgres syntax). Every tool call was hitting `Catalog Error: unrecognized configuration parameter`. Dropped the call; LIMIT 1000 + read-only + single-statement is the runtime bound. (Commit `03943aa`.)
3. **LIMIT injection skips non-SELECT queries + new `describe_table` tool** — `DESCRIBE players_current LIMIT 1000` was being constructed because LIMIT was appended to ANY query. Now gated to SELECT/WITH only. New `describe_table` tool gives the model a clean schema-discovery path (PRAGMA table_info wrapper with strict alphanumeric validation). (Commit `3de5bbd`.)
4. **Persona field + tool-plumbing hide** — new `persona: str` setting (free-form, appended to chat system prompt verbatim) with 5 presets in `/settings/ai`; tool_use/tool_result blocks hidden by default in the sidebar with a "Tools" toggle in the header (persisted to localStorage); Metabase card creations + tool errors stay visible regardless of toggle. (Commit `fe74739`.)
5. **Page-payload wiring** — earlier-deferred field is now populated. `<PagePayloadProvider>` Context in `app/layout.tsx`, `<PagePayloadBridge data={...}>` server-component-friendly bridge with 16KB cap + truncation hint. Cockpit (`/`) publishes `{save, cockpit}`; player page (`/player/[id]`) publishes the full PlayerResponse. AISidebar reads via `usePagePayload()` and includes in `page_context.payload`. (Commit `2381f0b`.)
6. **`get_career_arc` tool + cite-your-sources prompt** — user caught a Crochet-vs-Ryan comparison where the model hallucinated career pWAR (1,650.6 vs actual 117.9) and got year-to-age mapping wrong. New deterministic tool returns season-by-season + age (year - dob.year, minus 1 if birthday > July 1, OOTP convention) + warehouse-aggregated career WAR — eliminates two error classes in one tool. System prompt strengthened: "cite tool sources for every specific number; do NOT cite from training-data memory." (Commit `5711f98`.)

**Tool count: 7 → 8** (query_warehouse, describe_table, get_career_arc, get_player, compare_players, get_glossary, list_leaderboard_stats, create_metabase_card).

**Still deferred to v2**: streaming responses (SSE), conversation persistence (save threads to disk per save), token usage tracking + daily cap (the D14 `use_level` field), more tools (`get_team`, `get_standings`, `get_movements`), inline embedded Metabase static-embed previews.

---

## D34 — Cleanup pass: launcher consolidation + remove pre-D32 vestigial paths

**Date**: 2026-05-16
**Decision**: Delete three obsolete .bat files at the repo root, remove the redundant header Quit button + its backend endpoint, and fix the tray "Show Diamond" action to focus the existing window instead of opening a browser tab.

**Why**: Post-D32 desktop shell, several files and processes from earlier eras of the project had become redundant or misleading. Keeping them around added cognitive load with no upside. User asked "do we need all the files at the root?" — the answer was no.

**Three sub-changes**:

1. **Launchers** (commit `d3d2bcc`):

   - `api.bat` (24 lines) → deleted. Was a Windows-friendly equivalent of `make api`; only added value was setting `PYTHONIOENCODING=utf-8`. Now exported once at the top of the Makefile via `export PYTHONIOENCODING := utf-8`.
   - `web.bat` (18 lines) → deleted. Was an exact equivalent of `make web` with no env tweaks.
   - `kill-stale.bat` (65 lines, 8 lines of real logic) → deleted. Pre-D32 recovery for stale uvicorn / next dev processes; obsolete now that the desktop shell's Job Object handles cleanup atomically. The 8-line netstat/taskkill loop is now inline at the top of `dev.bat` for the dev path (where there's no Job Object).
   - `dev.bat` rewritten to call `make api` / `make web` directly instead of the deleted .bat files.

   **Launcher count: 5 → 2** (`Diamond.vbs` for production, `dev.bat` for engineering hot-reload). Plus Makefile targets for individual servers.

2. **Header Quit button** (commit `b682fbb`):

   - `web/components/QuitButton.tsx` → deleted (file).
   - `shutdownApp()` helper in `web/lib/api.ts` → removed.
   - `<QuitButton />` import + render in `web/app/layout.tsx` → removed.
   - `POST /api/admin/shutdown` route → removed.
   - 100-line `_KILL_SCRIPT` constant + 5 imports it required (`os`, `platform`, `subprocess`, `sys`, `tempfile`) → removed.

   The header Quit was important when Diamond was a browser tab and the user had no obvious way to stop the dev servers. Once the native window shipped (D32), it became vestigial. Plus the endpoint specifically targeted processes named `api.bat` / `web.bat` — files that no longer exist post-step-1.

   **Quit paths now**: window X (triggers Qt `aboutToQuit` → Job Object reaps children) or tray "Quit Diamond" (`app.quit()` → same path). Two paths, both clean.

3. **Tray "Show Diamond" focuses native window** (commit `f791080`):

   - Pre-D34, the tray's Show menu item ran `webbrowser.open(main_url)` — opened the cockpit in the user's default browser even though the native Qt window was right there.
   - Now: tray Show calls back to the launcher via a Qt Signal (`showRequested`), which marshals to the GUI thread and runs the canonical Win32 un-minimize/raise/activate sequence:
     ```python
     win.setWindowState(state & ~WindowMinimized)
     win.show()
     win.raise_()
     win.activateWindow()
     ```
   - Tray's `start()` accepts an optional `on_show: Callable | None` (None falls back to the old browser path as a safety net).

**Net delta**: 4 files deleted at repo root + ~325 LOC removed across backend + frontend. No functional regressions; one functional improvement (tray Show actually focuses the window).

**Files audited and intentionally kept**:

- `Diamond.vbs` (production launcher), `dev.bat` (engineering launcher), `Makefile` — all needed.
- `scripts/xstats_eda.py` + `scripts/xstats_3d.py` — EDA probes referenced in DATA_NOTES.md / BACKLOG.md / PROJECT_STATUS.md as the **empirical evidence behind D-tier xstats verdict**. Not actively run, but cheap to keep.
- All `docs/*.md` files — well-partitioned by audience (DESKTOP for end-users, DEV for engineers, METABASE for BI workshop).
- All `src/diamond/` modules — every one is imported somewhere (an earlier "unused module" scan was a false alarm caused by multi-line `from X import (a, b, c)` patterns).

**Pinned**: window X + tray Quit are the only quit paths; tray Show focuses the window via Qt signal; no separate per-server .bat files (Makefile is the source of truth).

## D35 — AI sidebar Claude.ai-style polish: markdown rendering + SSE streaming

**Date**: 2026-05-16 (later)
**Context**: Post-D33 the AI sidebar was functionally complete (page context + 8 tools + 4 modes + Metabase card creation) but visually unfinished. A user screenshot of a "compare Greg Maddux to Garrett Crochet at the same age" response showed the model producing an A-tier markdown answer — header, side-by-side comparison table, bold verdict — and the sidebar dumping it all as raw `| Stat | Greg Maddux ... |` text with literal `**asterisks**`. Plus per-text-block card chrome stacked four "DIAMOND" labels down the panel for one tool-using response. Plus no streaming — the user stares at "Thinking…" for 4-8 seconds while the model writes a long answer that arrives all at once.

**Decision**: Ship a four-tier polish pass that closes the visual gap to Claude.ai while preserving every D33 capability.

### Tier A: markdown rendering

Add `react-markdown` + `remark-gfm` + `rehype-katex` + `remark-math` as pnpm deps. New `MarkdownMessage` component renders assistant text through these with a custom `Components` map applying theme-aware Tailwind classes per element (h2/h3 hierarchy, GFM tables with borders + zebra stripes, lists with proper marker color, inline + block code with monospace + subtle bg, blockquotes, links opening in new tab — which the launcher's `ExternalLinkPage` routes to the system browser).

**Why not `@tailwindcss/typography`?** The prose plugin pulls a lot of CSS we don't need and would have to be re-themed across our four themes (light/dark/neutral/cb). Inline className overrides per element gives us less CSS, full theme integration, and explicit control over density (the panel is only 520px wide; `prose` defaults are sized for full-page documents).

**Per-text-block card chrome dropped.** The pre-D35 sidebar wrapped each text block in `border + bg-surface-card`. Combined with the per-turn role label, a tool-using response stacked four "DIAMOND ➜ pill ➜ DIAMOND ➜ pill" units. Now: assistant prose flat against the panel bg, one Diamond label per response group.

### Tier B: visual polish

Three structural changes:

1. **Coalesce consecutive assistant turns** into one rendered "response group" (user perceives a multi-iteration tool loop as one answer, so we render one Diamond header). `groupTurns()` walks the thread, starting a new group when a user-text turn arrives, otherwise appending to the trailing assistant group.
2. **User vs assistant asymmetry** — user messages: subtle right-aligned `bg-surface-card` pill (max 85% width, rounded-2xl with sharp top-right corner). Assistant: full-width flat prose with a small ✦ glyph next to the accent-colored "Diamond" label.
3. **Hover-revealed copy button** at the bottom of each completed assistant response. Uses `navigator.clipboard.writeText` with a 1.5s "✓ Copied" confirmation.

Panel default width 440 → 520. The 440px width was cramping tables.

### Tier C: SSE streaming

The biggest piece. Three layers:

1. **`AIClient.chat_stream`** — new method on the abstract base; signature mirrors `chat()` but returns `Iterator[dict]`. Default implementation calls `chat()` and re-emits the result as a sequence of `text_delta` + `tool_use` + `done` events (so any future adapter that doesn't support native streaming still works through the pipeline).

2. **Native streaming in both adapters**:
   - **Anthropic**: `httpx.Client.stream("POST", ..., json={..., "stream": True})`. Consumes SSE frames per the [Messages streaming spec](https://docs.anthropic.com/en/api/messages-streaming) — `content_block_start` (text or tool_use), `content_block_delta` (text_delta or input_json_delta accumulating partial JSON), `content_block_stop`, `message_delta` (final stop_reason), `message_stop`. Re-emits as our provider-agnostic event vocabulary.
   - **OpenAI**: same shape, different events. `delta.content` for text chunks, `delta.tool_calls[]` with per-`index` arguments accumulating piece by piece. After stream closes, the tool_call accumulator emits `tool_use` events. `finish_reason` maps to `stop_reason` per the same vocabulary as the sync `chat()` method.

3. **Route `_stream_chat`** — new `POST /api/ai/chat/stream` endpoint wraps a `StreamingResponse(text/event-stream)`. Generator drives the same tool loop as the sync endpoint (6-iteration cap), but yields SSE frames per event:

   ```
   event: iteration\ndata: {"n": 1}\n\n
   event: text_delta\ndata: {"text": "..."}\n\n
   event: tool_use\ndata: {"id", "name", "input"}\n\n
   event: tool_result\ndata: {"tool_use_id", "content", "is_error"}\n\n
   event: done\ndata: {"stop_reason": "end_turn", "iterations": N}\n\n
   ```

   Errors emit `event: error\ndata: {"detail": "..."}\n\n` followed by a terminating `done`. Headers include `X-Accel-Buffering: no` so QtWebEngine surfaces deltas promptly.

4. **Frontend `streamChat()`** — uses `fetch().body.getReader()` + `TextDecoder` to parse SSE incrementally. Frame parser splits on `\n\n`, picks `event:` + `data:` lines, dispatches to a handler. Supports `AbortController.signal` for the user's "Stop" button.

5. **`StreamingState`** machine in `AISidebar.tsx` — mutates an in-flight turn array per event (text_delta appends to the trailing text block on the trailing assistant turn; tool_use pushes a new tool_use block; tool_result starts a user turn carrying the result; iteration boundary starts a fresh assistant turn). On `done`, drains into the committed thread.

6. **Animated cursor** — `BlinkingCursor` component (a `h-3.5 w-1.5 animate-pulse bg-accent` block) appears at the end of the streaming text block + as a "Thinking…" indicator before any text arrives. Send button swaps to a Stop button while streaming.

**Why both endpoints, not just the streaming one?** The synchronous `/api/ai/chat` endpoint stays for tests, non-streaming integrations, and as a fallback. Both share the system prompt builder, tool loop, and 6-iteration cap; the only difference is delivery.

### Tier D: chrome polish

- **Mode pills moved into the header** (Tier 3 quick-actions). Pre-D35 they sat above the input area, splitting attention between two control bands. In the header they're closer to the other meta-controls (Tools toggle, New, Close).
- **Drag-to-resize** — 2px-wide invisible handle on the panel's left edge. PointerEvents drive width; persisted to `localStorage["diamond.ai.width"]` (clamped 380-900px).
- **Jump-to-latest button** — sticky pill that appears when the user scrolls 60+px above the bottom mid-stream. Click smooth-scrolls back down.

### Failure modes and recovery

- **Provider rejects streaming** (e.g. older Anthropic snapshot pre-stream-API): adapter raises `AIClientError`, route emits an `error` SSE event + `done`, frontend displays the error inline and offers retry.
- **Network drop mid-stream**: `httpx.HTTPError` caught; same error/done path. Frontend's `AbortController` also handles this client-side.
- **User clicks Stop**: `ctrl.abort()` → frontend drains any partial assistant turn into the committed thread (so the user keeps what was already streamed) + clears the streaming state. The route's generator yields control to FastAPI's response cleanup; no zombie tool calls (tools run server-side between iterations, not during a stream).
- **Markdown parse fail in `MarkdownMessage`**: react-markdown is forgiving; malformed input renders as plain text rather than throwing. KaTeX's rehype plugin is also fail-soft (renders `\notarealmacro` as the source string).

### What this does NOT do

- **Conversation persistence to disk** — still in-memory only per browser session. Backlog item.
- **Token usage tracking + daily cap** — not yet. Backlog item.
- **More tools** (`get_team`, `get_standings`, `get_movements`) — not yet. Backlog.
- **Inline embedded Metabase static-embed previews** — `create_metabase_card` still renders as a launcher link, not an inline iframe. Backlog.
- **Streaming tool inputs** — Anthropic streams the tool's input JSON character by character; we accumulate and only emit `tool_use` once the block stops. Showing the partial JSON would be visual noise; deferred.

### Wiring

- New file: `web/components/ai/MarkdownMessage.tsx`.
- Modified: `src/diamond/ai/client.py` (added `chat_stream` default), `src/diamond/ai/adapters/anthropic.py` + `openai.py` (native streaming overrides), `src/diamond/api/routes/ai.py` (new `/api/ai/chat/stream` endpoint + `_stream_chat` generator + `_sse` frame helper), `web/lib/ai-chat.ts` (new `streamChat` + `StreamEvent` type), `web/components/AISidebar.tsx` (full rewrite combining tiers B+C+D atop the markdown renderer from A).
- pnpm deps: `react-markdown@^10`, `remark-gfm@^4`, `rehype-katex@^7`, `remark-math@^6`. Bundle weight ~80KB gzipped — acceptable for a desktop-shell app where the bundle ships once at install time.

**Pinned**: AI prose renders as markdown; assistant text is flat full-width with one Diamond label per response group; user messages are right-aligned pills; streaming via SSE with a Stop button + animated cursor; mode pills + drag-to-resize live in the header.
