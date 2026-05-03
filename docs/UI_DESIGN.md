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

## Tech stack candidates

Not yet picked — call when UI work starts.

| Stack | Pros | Cons |
|---|---|---|
| **FastAPI + Next.js** | Best polish; React ecosystem (Vega-Lite, KaTeX, Plotly all first-class); future web-share path | Two codebases (Python + TS); dev setup heavier |
| **Streamlit** | Single Python codebase; fast iteration; built-in charts | Less polished UI; harder to do bespoke layouts; weaker for graph-builder UI |
| **Tauri + Vue/Svelte** | Native desktop feel; small binary | Learning curve; smaller ecosystem |
| **Dash (Plotly)** | Python-only; good for analytics dashboards | Limited beyond dashboards; harder for custom UX |

Lean: **FastAPI + Next.js** for the app, with shared TS types generated
from Python Pydantic models. Most polish, best fit for Bloomberg/Factset
ambition. Slowest to start, but the right substrate.

---

## Build order

Roughly in priority. Each phase is a meaningful artifact; later phases
share components with earlier ones.

1. **Reference scope expansion** *(small)* — D13 implementation
2. **Stat dictionary + glossary** — infrastructure for everything else
3. **Player page** — first user-facing feature; consumes glossary tooltips
4. **Promotion/demotion tool** — actively useful; reuses player page components
5. **Leaderboards** — Fangraphs-style; column headers from glossary
6. **Universes + chart builder + scatter** *(bundled)* — Vega-Lite + Plotly
7. **AI overlay** — settings, keyring, providers, use levels, cost layer
8. **Cockpit dashboard** — emerges naturally from previous components
9. **Reviews** — most AI-heavy, last because it depends on everything else
10. **Setup wizard** — built last but visible first (the polish layer)
11. **Sync triggers + tracked-save management** — same time as the wizard

Items 7 and 8 may swap order depending on energy — AI overlay is genuinely
useful even before cockpit anomaly flags need it.

---

## Open questions

Not yet decided; flagged here so they don't get lost.

- **Tech stack final pick** — FastAPI + Next.js leaning, but worth a sanity
  check before committing
- **Anomaly-flag detection thresholds** — what counts as a "sharp regression"
  worth surfacing? Z-score over rolling window? % change vs season avg?
  Needs calibration once we have data flowing
- **Universe naming convention** — "Watchlist" vs "Cohort" vs both?
  Currently undecided; lean is one term ("Universe") that covers casual
  and analytical use
- **AI prompt library** — per-feature prompts (monthly review, player
  dossier, chart annotation) need to be authored, versioned, A/B-tested.
  Treat as their own artifact.
- **Settings file format** — TOML vs JSON vs YAML? Lean TOML (Python-native
  parsing, comment-friendly, hand-editable)
- **Onboarding analytics** — opt-in? If sharing with community, useful
  to know which features get used; respect privacy as a default
- **Theming** — light/dark/system, or skip until UI matures

---

## Decisions trail

Architectural decisions extracted from this design:
- [D13 — Two-tier player scope](DECISIONS.md#d13-two-tier-player-scope-org--reference)
- [D14 — AI overlay architecture](DECISIONS.md#d14-ai-overlay-architecture-keyring-pluggable-providers-four-tier-use-levels)
- [D15 — Stat dictionary as single source of truth](DECISIONS.md#d15-stat-dictionary-as-single-source-of-truth)

Decisions still to be recorded as they crystallize:
- Tech stack pick (when UI work begins)
- Specific anomaly-detection algorithms
- Settings file location and format
