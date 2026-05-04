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

**Thin v1 cohort (39 entries shipped)**:
- batting (15): AVG / OBP / SLG / OPS / ISO / BABIP / K%/BB% / PA / HR / RBI / R / BB / K / SB
- advanced (8): wOBA / wRAA / wRC / wRC+ / OPS+ / ERA+ / FIP / SIERA
- pitching (6): W / SV / IP / K / ERA / WHIP
- value (3): WAR (OOTP) / oWAR / pit_WAR
- statcast (5): MAX_EV / AVG_EV / HARD_HIT_PCT / BARREL_PCT / SWEET_SPOT_PCT
- fielding (2): RF/9 / Framing+

**Long-tail entries** (~110 more) land here as UI screens reach for them. Strict rule: any new UI label, chart axis, or AI prompt MUST come from the dictionary — no hand-coded labels in feature code. Dictionary fills in over time but never lags behind what's exposed.

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
