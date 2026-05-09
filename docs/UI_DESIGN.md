# UI / Product Design

> **Status: design draft, 2026-05-05.** Captures the working product
> vision discussed during Phase 2. Architectural decisions extracted to
> [DECISIONS.md](DECISIONS.md) (D13–D15); this doc holds the synthesis,
> mockups, and open questions. SCHEMA.md style: revisable, append-only
> for changes. Implementation has not started — the warehouse (Phase 2)
> ships first.

---

## TL;DR

Diamond becomes a Bloomberg-terminal-meets-Fangraphs-style desktop analytics
app for OOTP saves, with AI-augmented analysis, a chart builder, named
universes (cohorts), and a stat dictionary as the connective tissue. Built
local-first (single-user) with optional community-shareable export later.

---

## Audience & use modes

### Audience

- **Primary**: solo user, the user's own OOTP saves.
- **Secondary (later)**: shareable artifacts (charts, reports, universes)
  exported as JSON for community swap. **Not** multi-tenant or hosted.
- **Out of scope**: SaaS, auth, multi-user collaboration. Diamond is a
  desktop tool that may sometimes export things to share.

### Use modes (in priority order)

1. **Monthly review** — new dump landed; what changed, what's interesting
2. **Annual review** — post-season recap, breakouts, busts, season grade
3. **Open-ended exploration** — Bloomberg-style: question in mind, pivot
   through data until answered
4. **Deep player analysis** — drill in to one player, with AI assistance
5. **Decision support** — promotion / demotion / who to call up / who to release
6. **At-a-glance check-ins** — between OOTP sessions, what's my org doing

---

## Reference site distillation

Diamond pulls the best ideas from each public stats site and combines them.

### Baseball Reference — "the encyclopedia"

**Steal**: player page layout (one scrollable page with tabbed sections —
stats → fielding splits → game logs → similarity scores → awards →
transactions); year-by-year navigation; splits table treatment (vs L/R,
home/away, by month, RISP, late-and-close, by count); URL pattern that
maps cleanly to a season.

**Skip**: ad-heavy density; absent visualization; dated visual style.

### Baseball Savant — "the visual layer"

**Steal**: percentile-bar player profile cards (read in 3 seconds); spray
charts (hit_xy + hit_loc on field overlay); EV × LA scatter with barrel-
zone overlay; sortable leaderboards with percentile column shading.

**Skip**: video integration (no analog in OOTP); cluttered mega-tables;
heat maps over the strike zone (per D5 we don't have per-pitch zone data).

### Fangraphs — "the analytical kitchen"

**Steal**: custom leaderboards with filter strip (year/level/age/min-PA/
qualifying, sortable on any column, save-to-URL); splits tool; "The Board"-
style prospect rankings linked to scouting context; player game logs
filterable by date range; **stat-name hover tooltips with formulas**.

**Skip**: visual density (intimidating), insider paywalls, web-1.0 navigation.

---

## Information architecture (committed 2026-05-08, [D17](DECISIONS.md#d17-information-architecture-five-tab-scopepurpose-nav))

Top-level navigation is **five tabs** in the layout header:

- **Club** (`/`) — your org. Default landing. Roster, recent moves, decisions queue, standings, anomaly flags.
- **League** (`/league`) — your scoped leagues (MLB tree + DSL + AFL). Standings, curated leaderboards, awards races, free agents.
- **World** (`/world`) — every league in the save, scoped or not. For users who follow international ball / KBO / NPB / indy.
- **History** (`/history`) — past seasons across any scope. Records, awards, HoF, streaks, past draft classes.
- **Explore** (`/explore`) — sandbox for max-the-data analysis. Compare, custom leaderboards, distributions, spray charts, EV/LA scatter, chart builder, cohorts.

Plus three cross-cutting surfaces:

- **Glossary** (`/glossary`) — stat dictionary, reachable from any tab via header link.
- **Player** (`/player/[id]`) — a *target*, not a peer view. Reached from Club roster, League leaderboards, History HoF list, etc. Search box (planned) is the cross-cutting entry point.
- **Settings + Quit + ThemeSwitcher** — corner controls, not peer tabs.

The first three tabs (Club / League / World) are concentric **scope** lenses. History is a **time** lens. Explore is the **interaction-mode** lens. This carving was committed mid-Phase-3 — the original build order put a Cockpit at item 8 with the rationale that it would "emerge naturally," but in practice that meant features were shipping as orphan top-level routes (`/movements`, `/glossary`) without any IA. From 2026-05-08 onward every new feature lands in the right tab from day one.

The 8 product areas below describe **what content goes in each tab**, not a peer-tab list.

## Major areas of the app

Diamond has **8 areas** that combine into a cohesive product. Each is its
own page/section with shared infrastructure (glossary, AI overlay, charts).

### 1. Front-Office Cockpit *(home)*

Your org, today. Dashboard-style, fast-loading.

- **Roster grid** (active 25 / 40 / DL / minors) with role + service time +
  contract years left + recent rating delta + WAR-this-season
- **Recent moves feed** — pulled from `player_movements` (item 7)
- **Standings + Pythag** — your level + parent league
- **Decisions queue** — "5 demotion candidates" / "3 promotion candidates"
  (links to the dedicated tool, but surfaces top-of-list here)
- **Anomaly flags** (Smart-tier AI) — "3 players regressed sharply in
  last 14 days," "Mayer wRC+ split improved to 142 vs RHP"
- **Last-sync indicator** (footer): warehouse status, dump count, latest dump

Shape inspired by: Bref team page + Fangraphs depth charts + a touch of
Bloomberg ticker for anomalies.

### 2. Player Pages

Bref-shaped layout, Savant-styled visuals, AI-augmented context.

**Top section**: bio header + percentile bars (Savant-style) + "career so far"
line chart. The percentile bars are *cohort-aware* — bar colors compute
against the player's level/league/position cohort, not MLB-wide.

**Tabbed sections** (sticky tabs):
- **Stats** — career table + season splits (vs L/R, home/away, by month,
  RISP, late-close)
- **Charts** — embedded chart instances (powered by the chart builder):
  spray, EV/LA scatter, career trajectory
- **Game log** — filterable date range, expandable game detail
- **Comparisons** — Bref-style similarity scores + side-by-side picker
- **Scouting** — current ratings + ratings evolution over time + scouting
  notes
- **Contract / status** — current contract + extension + roster status

**Right rail**:
- Quick links: contract / option years / roster status / draft team
- AI assistant pinned: "Ask anything about this player"

URL pattern: `/player/<player_id>` and `/player/<player_id>/<season>` for
season-scoped views.

### 3. Custom Leaderboards

Fangraphs-style sortable tables with a sticky filter strip.

- Filters: year range, level, league, age range, min-PA/IP, position,
  handedness (where applicable), team, scope (org / reference)
- Columns: pick from any L2/L3 stat, percentile-shaded backgrounds
- Sort/filter every column; save-to-URL; export-to-CSV
- Multi-select rows → "Add selected to a universe"
- Four leaderboard variants: batting, pitching, fielding, combined value

URL pattern: `/leaderboard/batting?year=2029&level=1&min_pa=300&sort=woba`

### 4. Reviews

Long-form, AI-augmented narrative pages.

- **Monthly review**: "Diamond, summarize October" — pulls latest dump diff,
  generates "what changed," top performers, anomalies, your decisions
- **Annual review**: post-season recap — player breakouts/busts, your
  org's grade, biggest moves, prospect rankings shift
- Both rendered as scrollable narrative with embedded charts. AI fills
  prose, warehouse provides numbers, charts render via spec.

This is the most AI-dependent feature and the most "Smart"-tier-friendly:
auto-runs a draft when a new month lands; user reads / edits / shares.

### 5. Promotion/Demotion Decision Tool

The feature that goes beyond Bref/Savant/Fangraphs — they're public-stats
sites; Diamond is a GM's sidekick.

For each level:
- **Demotion candidates** — current performance percentile vs level + per-
  position depth chart pressure + recent slump signals + scouting-rating
  context + at-bats-since-arrival sample size
- **Promotion candidates** — projected percentile at next level (level-
  multiplier projection), age-adjusted, scouting-rating ceiling, service
  time / option years awareness

Ranked list in each direction, click-through to player page, AI assistant
explains the recommendation: *"Why is X recommended for promotion?"* with
specific stat citations.

### 6. Universes + Chart Builder + Scatter (bundled)

The Bloomberg-terminal layer. Bundled because they're symbiotic — a chart
without a cohort to plot is mute; a cohort without charts to render it
isn't useful.

**Universes** — first-class primitive:
- Members: manual / saved-query / set-op (A ∪ B, A ∩ B, A − B)
- Storage: per-save (default) and per-user (persistent across saves)
- No size limit (architectural support up to 50K+ via WebGL backend)
- Versioning: optionally snapshot membership at any time for audit trail
- Export as JSON for community swap

**Chart builder** — Vega-Lite spec as the artifact:
- Data dictionary subset of glossary (~50 measures, ~10 dimensions)
- 6 chart types: line, bar, scatter, area, distribution, heatmap
- ~12 templates as starters: career trajectory, spray, distribution-vs-
  league, side-by-side comparison, rating evolution, etc.
- Auto-renderer selection: Vega-Lite SVG (≤2K points), Vega-Lite Canvas
  (≤50K), Plotly WebGL (>50K)
- Saved gallery with thumbnails

**Cross-era support**: when comparing players across decades, axes can be
career-year or age (not calendar-year); metrics auto-suggest era-adjusted
versions (wRC+, OPS+, ERA+) to keep comparisons fair.

**Set ops on universes** unlock real GM moves: *"farm system MINUS guys
I'd never trade INTERSECT age ≤ 24"* = trade-bait shortlist.

### 7. Glossary

Stat dictionary. Every column header in the app, every chart axis, every
AI narrative speaks the same language about what stats mean.

- **Hover tooltip** on every column header: stat name + formula (KaTeX-
  rendered) + 1-2 line description + typical range + interpretation +
  link to glossary detail page
- **Dedicated `/glossary` page** with search + category filters, each
  stat URL-addressable (`/glossary/wOBA`)
- Per-stat detail page: full formula, derivation walkthrough, source-
  code link, distribution histogram over your save's data, "where it
  appears in the app"
- Lazy-loaded tooltips — definitions fetched on first hover, not preloaded
- KaTeX for math rendering

See [D15](DECISIONS.md#d15) for architecture: single Python source of
truth at `diamond/dictionary/`, all UI consumes it.

### 8. AI Overlay

Platform-agnostic AI sidebar woven into every page. See [D14](DECISIONS.md#d14)
for the architecture.

**Settings menu** for AI:
- Provider section: Anthropic / OpenAI / Google / Local Ollama, with API
  key input (stored in OS keyring, never disk), test-key button, links to
  each provider's "get a key" page
- Default model dropdown: model list with cost-per-Mtok, "frontier" /
  "default" / "fastest" badges
- Per-feature model overrides: cockpit summaries / deep player analysis /
  chart annotations / monthly reviews
- Daily budget cap: amount + on/off toggle + 80%/100% auto-degrade behavior
- Usage log: per-call costs, daily/monthly running total

**Use levels** (global default, per-feature override):
- **Off** — all AI hidden
- **On-demand** — AI buttons visible, cost-preview before each click
- **Smart** *(default)* — auto-runs cheap inline features (chart annotations,
  percentile cards, anomaly flags); prompts before expensive ones (monthly
  review, deep dossier)
- **Always-on** — auto-runs everything

**Cost transparency**: every AI button shows estimate (`✨ Generate (~$0.04)`);
auto-features show cost AFTER (`🪙 $0.01`); cockpit footer shows daily total.

**Pricing source**: OpenRouter live fetch (their model catalog has
~200 models with current pricing), with hardcoded TOML fallback if offline.

---

## Cross-cutting infrastructure

### Setup wizard

First-launch onboarding. Optimized for the common case (one user, one save,
three clicks).

**Steps**:
1. Welcome (skippable on subsequent launches)
2. OOTP installation detection — auto-walks standard paths for OOTP 27/26/25;
   "Browse…" fallback; multi-version support
3. Pick saves to track — list of `.lg` folders with metadata sniff (last
   played, dump count, leagues, owner team)
4. Per-save scope (Quick = auto-detect org / Custom = manual)
5. AI setup (skippable; configures keys + use level + budget cap)
6. Initial ingest (background option; "Continue to cockpit" while it runs)

**Wizard close behavior** (tutorial-style):
- Closing mid-wizard prompts: "Resume next time" (default) vs "Don't show
  again — I'll add saves from Settings"
- Persists as `settings.wizard.disabled = bool`
- Always re-enableable from `Settings › Misc`

**Resume policy**: closed mid-wizard restarts from step 1 with answers
pre-filled — safer than blindly resuming when paths might have shifted.

**Wizard exit-state truth table**:

| Has tracked saves? | wizard.completed | wizard.disabled | Show on launch? |
|---|---|---|---|
| no | false | false | **yes** (first run) |
| no | false | true | no (opted out) |
| yes | * | * | **no** (assume completion) |
| no | true | * | no (rare; completed without tracking — fine) |

### Sync / ingestion triggers

Layered, no daemon required.

1. **App-launch scan** — walks `<save>/dump/`, compares to `_diamond_ingests`,
   shows non-modal banner: *"3 new dumps detected — Sync now / Later /
   Settings"*.
2. **Manual refresh button** — persistent in the cockpit top-right.
3. **Auto-sync on launch** — user-toggled setting (no opinionated default;
   exposed clearly in wizard step 4 and Settings).
4. **Suppress sync mid-task** — confirmed: never disrupt active reading
   (e.g., user mid-monthly-review). Sync proceeds; UI doesn't refresh
   until next navigation.

**Partial-write detection**: a candidate dump folder is "ready" only when
the most-recently-modified file inside it is >60 seconds old. Mid-write
folders are skipped with "still being written" indicator until next refresh.

**Status indicator** in cockpit footer:
```
Warehouse: 47 dumps · last sync: 12 min ago · latest dump: 2030-01
```
Click → opens sync log with per-dump timestamps and any failures.

### Tracked saves management

`Settings › Tracked saves` lists every save in the registry with two
distinct destructive actions:

- **Untrack** — removes from registry; warehouse DB stays on disk; re-track
  later is instant. Cheap to recover from.
- **Delete warehouse** — permanently removes `<save>/diamond/diamond.duckdb`;
  re-tracking later requires full re-ingest. Red button, big confirmation
  dialog: *"⚠ This cannot be undone."*

Two distinct buttons because the failure modes are different.

`[+ Add save]` button re-runs wizard steps 2-4 inline as a modal.

### Theme system (committed 2026-05-08, [D18](DECISIONS.md#d18-ui-theme-system-css-variable-semantic-tokens-four-themes-dark-default))

Four themes selectable from a `<ThemeSwitcher />` in the layout header:

- **Light** — default white-paper look.
- **Dark** *(default)* — slate-based, easy on eyes for long sessions.
- **Neutral** — warm cream / off-white for users who find pure white too bright but want a light theme.
- **Color-blind** — Wong (2011) palette + IBM CB-safe accents. v1 swaps page chrome + accent + link only; verdict glyphs and move-type badges still use green/amber/rose. Full CB-safe accent migration is a backlog item.

**Implementation**: CSS custom properties under `:root` and `[data-theme="..."]` selectors in `web/app/globals.css`. The Tailwind config exposes them as semantic tokens (`bg-surface-page`, `text-content-primary`, `border-border`, `text-link`, etc.) so components write theme-agnostic class names. Tailwind's `dark:` prefix is configured against `[data-theme="dark"]` — used sparingly for accent-heavy badges that need a dark-mode-specific tint (e.g., `bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300`).

**No-flash on first paint**: an inline `<script>` in `<head>` reads `localStorage["diamond.theme"]` synchronously before body paints and stamps the `data-theme` attribute. Without it, every reload flashes the default theme for ~50ms.

**Convention for new pages**: write semantic tokens from the start. Don't introduce raw `slate-*` / `white` / etc. unless the use case is genuinely theme-agnostic (verdict-color badges that already encode meaning via color).

### Stat dictionary architecture

See [D15](DECISIONS.md#d15). Implementation:

```python
# diamond/dictionary/__init__.py
@dataclass(frozen=True)
class Stat:
    id: str               # "wOBA", "ERA_plus"
    display_name: str     # "Weighted On-Base Average"
    short_label: str      # "wOBA"
    category: str         # "batting" | "pitching" | "fielding" | "advanced" | "ratings" | "value"
    formula_tex: str      # KaTeX-renderable
    formula_plain: str    # text fallback
    description: str
    units: str            # "rate (0-1)" | "index (100=lg avg)" | "count" | etc.
    typical_range: str
    interpretation: str
    caveats: str | None
    source: str           # "f_player_season_advanced_batting.woba"
    formula_source: str   # "Fangraphs standard linear weights, park-halved"
    related: list[str]
    refs: dict[str, str]  # {"Fangraphs": "https://...", ...}
```

Existing material consolidates from:
- `reconcile.py` `ColSpec.notes` (~270 stat-formula notes)
- `advanced/*.py` module docstrings
- `DATA_NOTES.md` empirical findings + caveats
- `constants.py` IntEnum docstrings

---

## Tech stack (locked 2026-05-07 per [D16](DECISIONS.md#d16))

**FastAPI + Next.js (App Router), TypeScript types auto-generated from
Pydantic models.**

- **Backend**: FastAPI (Python). Reuses every existing `src/diamond/`
  module (records / awards / hof / streaks / glossary / advanced /
  schema) as the data layer. Talks directly to the per-save DuckDB
  warehouse.
- **Frontend**: Next.js (App Router) on TypeScript + React.
- **Bridge**: Pydantic models on the backend are the single source of
  truth for API shapes; TS interfaces auto-generate from them so the
  two layers can never drift on field names or types.

**Component primitives** (lean; finalize during scaffolding):
- Tailwind + shadcn/ui — layout / atoms / forms
- Vega-Embed (≤50K points) + Plotly WebGL (>50K) — charts
- KaTeX — formula rendering (matches D15 dictionary `formula_tex` field)
- TanStack Table — sortable/filterable leaderboards

Alternatives ruled out: Streamlit (layout ceiling on bespoke pages),
Tauri + Vue/Svelte (Rust+JS+Python three-layer build with no
analytical benefit), Dash (dashboard-shaped — fights the 8-area design).
Full reasoning in D16.

---

## Build order

Phase 3 build order — revised 2026-05-08 to reflect the IA-first pivot.
Original ordering put cockpit at item 8 with the assumption it would
"emerge naturally"; in practice we shipped features as orphan routes
without any IA, so we committed the IA mid-phase and now every new
feature lands in the right tab from day one.

1. ✅ **Reference scope expansion** *(small)* — D13 implementation. Done 2026-05-07.
2. ✅ **Stat dictionary + glossary** — infrastructure for everything else. Done 2026-05-07; 60 entries today.
3. ✅ **Player page Stats tab** — Bref-shaped batting / pitching / fielding / advanced; disclosure rows for multi-stint years. Done 2026-05-07.
4. ✅ **Movement ledger** *(v1 of the GM-sidekick promotion/demotion tool)* — call-ups / send-downs / acquisitions / departures with level-aware verdicts. Done 2026-05-08.
5. ✅ **IA backbone (D17)** — five-tab nav, four stub routes, Glossary + ThemeSwitcher + Quit in the header. Done 2026-05-08.
6. ✅ **Theme system (D18)** — four themes, dark default. Done 2026-05-08.
7. ✅ **Real landing page (Club v0)** — save header + warehouse-health grid + tools card list. Done 2026-05-08.
8. ✅ **In-app Quit + dev.bat one-shot launcher** — done 2026-05-08.
9. ✅ **Roster page** — done 2026-05-09. `/roster` lists every active org-tree player grouped by current level. Three filter pills (Level / Role / Hand) + **three-mode stat toggle (Basic / Advanced / Contact)**. Server returns full payload in one round-trip; client-side filtering + mode switching. Names link to player page — closes the navigation loop. Backend: `routes/roster.py` + `schemas/roster.py`. Frontend: server page + `RosterClient.tsx`.
10. ✅ **Statcast cohort + SIERA** — done 2026-05-09. Two new L3 tables (`f_player_season_statcast_batting` + `_pitching`, BIP ≥ 30, materialized from `f_pa_event`). SIERA added to `f_player_season_advanced_pitching` via Fangraphs canonical regression. Surfaced via the new Contact mode on the roster.
11. ✅ **Combined bWAR / pWAR** — done 2026-05-10. Reframed mid-slice once we noticed OOTP supplies WAR directly: `players_career_*.war` / `.ra9war` is already aggregated into `f_player_season_*.war` and reconciled to IE WAR as A-tier (audit since 2026-05-04). Slice was plumbing — added `b_war` / `p_war` / `p_ra9_war` to `f_player_season_advanced_*` (SUM across stints), surfaced on roster Advanced view (replacing offense-only oWAR / custom pit_war) and on player page Advanced sections (alongside the custom variants — gap reveals defensive component / leverage scaling). Verified Mayer 3.2 = IE 3.2, Anthony 0.9 = IE 0.9, Crochet 5.5 = IE 5.5, Whitlock 0.4 = IE 0.4 (all exact). Dictionary: added `bWAR` + `pWAR` + `RA9_WAR`, deprecated ambiguous `WAR` entry.
12. ✅ **Per-position fielding view** — done 2026-05-10. New "Defensive Profile" section on the player page surfaces the 9-position scouted-rating cube (current × ceiling × experience). Backed by a new `players_fielding_current` view + `PlayerPositionFielding` Pydantic schema; UI sorts by experience desc so the spots the player has actually logged innings at come first. Cells color-coded by 20-80 rating. Verified Justin Gonzales reads as a corner-OF guy (LF 65 / RF 60 / 1B 50 with 197/184/200 plays of experience) despite his POS=1B listing.
13. ✅ **Service-time / arbitration clock** — done 2026-05-10. New "Service & Status" card on the player page (between bio header and tab strip). MLB service formatted Bref-style ("4y 128d"; 172 days = 1 year), computed service class (Pre-arb / Arb Y1-Y3 / FA-eligible) with color-coded chip, days-to-FA estimate, options-used block, and a status-flag row (Active / 40-man / 10-day IL / 60-day IL / DFA / Waivers — only renders truthy ones).
14. **Salary stream** — render `contract_current.salary0..14` + option types + no-trade clause on the player page.
15. ✅ **Standings page** (League tab) — done 2026-05-11. New `GET /api/standings?league_id=&year=` endpoint returns sub-league × division × team rows from `team_record_snapshot` at MAX(dump_date) within the chosen year. Defaults to MLB / latest year. League picker grouped by level (MLB / AAA / AA / A+ A / Rk DSL); year picker as a strip. User's org row gets a left-border accent + "You" pill. Magic-number sentinels (`-1` clinched, `1000` N/A) collapse into `magic_number: int | None` + `clinched: bool`; streak signed int → "W9"/"L4"/—. Below the standings: slim "Coming to League" stub strip preserves IA visibility for leaderboards / awards / FA pool. Pythagorean / RS / RA columns deferred (snapshot carries W-L-Pct only). AFL absent from picker (no `leagues` reference row).
16. ✅ **Clutch / RISP splits** on player page — done 2026-05-12. Situational batting + pitching sections, multi-year coverage. Four splits per (year, level): All / RISP / RISP 2-out / Late & Close. Slash + counting per row. OPS color-coded vs the All baseline — emerald when ≥25 pts in the player's favor, rose when ≥25 pts against. Color logic inverts for pitchers (lower OPS allowed in clutch = good). Backed by `_fetch_situational(con, player_id, side)` reading from the now-multi-year `f_pa_event`. Verified: Devers 2029 RISP .881 emerald; Crochet 2027 RISP 2-out .316 OPS allowed (emerald — elite clutch starter); 2029 RISP 2-out .839 (rose — regression). Mayer's full 4-year career arc visible.
17. **Pressure board** — companion to the movement ledger. "Who *should* move." Backed by the existing `f_player_season_advanced_*` tables.
18. **Compare under Explore** — pick N players, side-by-side tables + overlaid trajectories. Cross-era via career-year axis. Trout-vs-Cobb is the canonical demo; forces the chart-stack decision.
19. **Charts tab on the player page** — radial career arc visualization.
20. **Custom leaderboards** — TanStack Table integration; curated default version in League, build-your-own in Explore.
21. **Cockpit v2** — anomaly flags, decisions queue (regret signals + pressure-board recommendations), standings + Pythag, recent-moves feed inline. Replaces Club v0.
22. **History view content** — port the existing CLI surfaces (`diamond records / awards / hof / streaks / draft <year>`) to web views.
23. **League view content** — standings (lights up earlier per item 15), leaderboards, awards races, free-agent pool.
24. **World view content** — all-leagues browser; thin until scope expands.
25. **Universes + chart builder + scatter** *(bundled)* — Vega-Lite + Plotly. Lives under Explore.
26. **Color-blind mode v2** — extend the `cb` theme to swap verdict / badge palettes (currently chrome-only).
27. **AI overlay** — settings, keyring, providers, use levels, cost layer. Cross-cutting; lights up Reviews and inline AI annotations.
28. **Reviews** — most AI-heavy, last because it depends on everything else.
29. **Setup wizard** — built last but visible first (the polish layer).
30. **Sync triggers + tracked-save management** — same time as the wizard.

Items 27 and 21 may swap order depending on energy — AI overlay is genuinely
useful even before cockpit anomaly flags need it. Items 11–16 are the
"low-hanging fruit revealed by the 2026-05-09 dump-CSV audit" cluster — all
half-day or smaller, all surface data that's already in the warehouse but
unexposed in the UI. Pick any of them when energy is short for a bigger
slice.

### Stat-mode toggle pattern (introduced on roster page 2026-05-09)

When a single table needs to expose multiple "personalities" of stats —
counting vs sabermetric vs Statcast contact — use a **three-position
segmented control** in the table's filter bar: `Basic ⇄ Advanced ⇄
Contact`. The three column sets are:

- **Basic** — the counting + slash / counting + ERA-WHIP-K9-BB9 line
  someone used to a box score expects. AVG/OBP/SLG/OPS for batters;
  ERA / WHIP / K/9 / BB/9 for pitchers.
- **Advanced** — the league-relative sabermetric stack. wOBA / wRAA /
  wRC / wRC+ / OPS+ / **bWAR** + park factor for batters; FIP / SIERA /
  ERA+ / **pWAR** + park factor for pitchers. bWAR + pWAR are the
  OOTP-canonical IE-reconciled values (combined; include defense /
  positional adjustment for batters and leverage for pitchers). The
  offense-only `oWAR` and custom-FIP `pit_WAR` live on the player page
  Advanced sections + glossary as inspectable alternatives.
- **Contact** — the Statcast cohort. BIP / max EV (P90) / avg EV /
  HH% / Brl% / SS%. Pitcher rows interpret all percentages as
  allowed-contact (lower = better; tooltip clarifies). Sub-30-BIP
  rows render as dashes.

Reuse this pattern wherever a dense table would otherwise need a
"basic/advanced toggle" — three slots is the natural decomposition for
this codebase given the warehouse coverage.

---

## Open questions

Not yet decided; flagged here so they don't get lost.

- **Anomaly-flag detection thresholds** — what counts as a "sharp regression"
  worth surfacing? Z-score over rolling window? % change vs season avg?
  Needs calibration once we have data flowing.
- **Universe naming convention** — "Watchlist" vs "Cohort" vs both?
  Currently undecided; lean is one term ("Universe") that covers casual
  and analytical use.
- **AI prompt library** — per-feature prompts (monthly review, player
  dossier, chart annotation) need to be authored, versioned, A/B-tested.
  Treat as their own artifact.
- **Onboarding analytics** — opt-in? If sharing with community, useful
  to know which features get used; respect privacy as a default.
- ~~**Theming** — light/dark/system, or skip until UI matures.~~ Closed 2026-05-08 — shipped four themes (light / dark / neutral / cb) per D18. Dark is the default.

Closed:
- ~~Tech stack pick~~ — locked 2026-05-07: FastAPI + Next.js per [D16](DECISIONS.md#d16).
- ~~Settings file format~~ — TOML, locked alongside D16.

---

## Decisions trail

Architectural decisions extracted from this design:
- [D13 — Two-tier player scope](DECISIONS.md#d13-two-tier-player-scope-org--reference)
- [D14 — AI overlay architecture](DECISIONS.md#d14-ai-overlay-architecture-keyring-pluggable-providers-four-tier-use-levels)
- [D15 — Stat dictionary as single source of truth](DECISIONS.md#d15-stat-dictionary-as-single-source-of-truth)
- [D16 — Tech stack: FastAPI + Next.js](DECISIONS.md#d16-tech-stack-fastapi--nextjs-app-router-pydantic-derived-ts-types)
- [D17 — Information architecture: five-tab scope+purpose nav](DECISIONS.md#d17-information-architecture-five-tab-scopepurpose-nav)
- [D18 — UI theme system: CSS-variable semantic tokens, four themes, dark default](DECISIONS.md#d18-ui-theme-system-css-variable-semantic-tokens-four-themes-dark-default)

Decisions still to be recorded as they crystallize:
- Specific anomaly-detection algorithms
- Universe export schema
- Theming approach
