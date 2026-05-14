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
- **League** (`/league`) — your scoped leagues (MLB tree + DSL + AFL). Standings, leaderboards, **compare**, awards races, free agents.
- **World** (`/world`) — every league in the save, scoped or not. For users who follow international ball / KBO / NPB / indy.
- **History** (`/history`) — past seasons across any scope. Records, awards, HoF, streaks, past draft classes.
- **Explore** (`/explore`) — **Chart Builder** workshop. Pick X/Y/color from the 32-stat catalog, filter, render. Per-2026-05-13 IA shuffle, /explore is no longer a hub-of-tools landing — per-player charts (spray, EV-LA) live inline on the player page; league-wide tools (leaderboards, compare) moved under /league.

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
- **Drift pill** *(Phase 4b D40, shipped 2026-05-14, commit `251a0dd`)* —
  header chip rendering "Drift NN.N%" colored green / amber / red based on
  the D40 invariants watchdog's overall.status. Adds a `· NR` red-count
  badge when reds > 0. Tooltips show the per-metric tally + last-run
  dump date. Consumes `/api/admin/invariants`. Hidden gracefully on
  warehouses that predate the watchdog.

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
  - **Recent form panel** *(Phase 4b Tier D, shipped 2026-05-14, commit
    `335d5c2`)* — sits above the year-by-year tables. Renders both batting
    and pitching aggregates over rolling calendar-day windows (default 7d
    / 15d / 30d). Anchor = player's most recent regular-season game (NOT
    today — works for retired players + mid-season views). Localized date
    range display ("Jul 24-31, 2028"). "No games in window" empty state.
    Component: `web/components/RecentFormPanel.tsx`. Consumes
    `/api/players/{id}/recent`.
- **Charts** — embedded chart instances (powered by the chart builder):
  spray, EV/LA scatter, career trajectory
  - **Future**: per-dump trajectory chart (Phase 4b Tier B follow-up) —
    consumes `/api/players/{id}/trajectory` season_bat / season_pit arrays.
    Shows in-season month-by-month progression (e.g. Merrill 2028 AVG
    .231 → .290 → .284 → .282 → .288).
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
14. ✅ **Salary stream** — done 2026-05-12. New "Contract" section on the player page (between CareerArc and the tab strip). `PlayerContract` Pydantic schema flows the L1 `contract_current` view; option types (TO/PO/VO), buyouts, opt-outs, no-trade flags resolved server-side. CSS-bar viz per year, current-year highlight (emerald), past years muted, future years sky. Total + remaining USD totals in the header; option badges + opt-out + buyout chips below the year label. Crochet 7y/$185M (curr year 4 of 7, 2030 opt-out, 2032 TO with $5M buyout); Henderson 8y/$388.5M no-trade. Bonus incentives + AAV deferred.
15. ✅ **Standings page** (League tab) — done 2026-05-11. New `GET /api/standings?league_id=&year=` endpoint returns sub-league × division × team rows from `team_record_snapshot` at MAX(dump_date) within the chosen year. Defaults to MLB / latest year. League picker grouped by level (MLB / AAA / AA / A+ A / Rk DSL); year picker as a strip. User's org row gets a left-border accent + "You" pill. Magic-number sentinels (`-1` clinched, `1000` N/A) collapse into `magic_number: int | None` + `clinched: bool`; streak signed int → "W9"/"L4"/—. Below the standings: slim "Coming to League" stub strip preserves IA visibility for leaderboards / awards / FA pool. Pythagorean / RS / RA columns deferred (snapshot carries W-L-Pct only). AFL absent from picker (no `leagues` reference row).
16. ✅ **Situational splits** on player page — done 2026-05-12; **trimmed 2026-05-10 (D41)**. Situational batting + pitching sections, multi-year coverage. **11 splits per (year, level)** post-D41 organized into four clusters: **Leverage** (All / RISP / RISP 2-out / Late & Close) · **Bases** (empty / loaded) · **Platoon** (vs L / vs R, side-aware labels) · **Counts** (first pitch / two strikes / full count). Slash + counting per row. OPS color-coded vs the All baseline (emerald ≥25 pts in player's favor, rose ≥25 pts against; inverts for pitchers). Switch-hitters resolve to opposite of pitcher's throwing hand. The **spray cluster** (pull / center / oppo) was removed in commit `cd422af` per D41 — hit_xy lacks per-batter spray correlation (r=0.17), couldn't meet the OOTP-match invariant. Spray chart visualization survives on the player page (visually correct after the `[0,255]` clipping fix). Backed by `_fetch_situational(con, player_id, side)` reading from the multi-year `f_pa_event` + LEFT JOINs to `players_current` for handedness. Verified post-trim: Merrill 2028 returns 11 unique splits; no pull/center/oppo. Per `DATA_QUIRKS.md`, the L_IE re-enable path would surface OOTP's exact spray %s for org-roster players.
17. ✅ **Pressure board** — done 2026-05-12. `/pressure` lives. `GET /api/pressure?year=&limit=` returns per-level promotion candidates + pressure cases for the org tree. Two-column cards per level (MLB / AAA / AA / A+ / A / Rk / DSL); left = top performers (call-up worthy), right = strugglers (send-down candidates). Sample bars: 50 PA / 20 IP. Heat-scale-colored metric column. Cross-link to `/movements` for the "did vs should have" pairing. 2029 spotlights: Caleb Durbin 183 OPS+ at AAA vs his own 97 at MLB (clear "stop yo-yo'ing him" decision); Narvaez/Anthony/Langeliers as MLB pressure; Garcia/Rodriguez/White as AAA call-up cohort.
18. ✅ **Compare** — done 2026-05-12, **moved to `/league/compare?ids=` 2026-05-13** (was `/explore/compare`). `GET /api/compare?ids=` returns slim cards (career batting + pitching lines + WAR sparkline series + headline metric) for ≤4 players side by side. Cross-era via D20 baselines (Bonds 2001 / Trout 2018 / Skubal 2029 all carry full advanced numbers). Empty state surfaces three demo deep-links. The /explore/compare URL still works via permanent redirect.
19. ✅ **CareerArc on player page** *(in lieu of Charts tab v1)* — done 2026-05-12. Hand-rolled SVG line chart of career WAR by year, with WAR-magnitude dot fills, peak-tier reference band, year-axis ticks, and per-dot tooltips. Sits between bio header and tab strip on `/player/[id]`. Bonds 2001 spike, Trout's plateau, Skubal's ascending arc — all visible at a glance. The radial-arc Charts tab vision morphed into this simpler hand-rolled SVG once we had a clear use case; full chart lib still deferred.
20. ✅ **Custom leaderboards** — done 2026-05-13, **moved to `/league/leaderboards` 2026-05-13** (was `/explore/leaderboards`). TanStack Table 8.21 with URL-driven picker (stat / year / level / min-qualifier). Backend whitelists 32 stats across batting / pitching / Statcast (`LEADERBOARD_STATS` dict in `routes/leaderboards.py`); GET `/api/leaderboards/options` for the picker dropdown, GET `/api/leaderboards?stat=&year=&level_id=&league_id=&pa_min=&limit=` for the ranked rows. Direction is stat-driven (HR desc, ERA asc); client can re-sort any column without refetch. Heat-scale on plus-stat / WAR cells. Verified: HR 2029 → Hector Santiago 51 / Henderson 44 / Judge 44; ERA 2029 → Bradgley Rodriguez 2.56 / Yesavage 2.70 / Forret 2.70. The /explore/leaderboards URL still works via permanent redirect.
21. ✅ **Cockpit v2** — done 2026-05-12. `/` is now the cockpit dashboard. `GET /api/cockpit` composes Sox AL East standings + top-3 MLB promotion/pressure pairs + 6 spotlight cards (with inline career-WAR sparkline + auto-generated NLG insight per card — "Bounceback — 149 after 90 in 2028" / "Off year — 127 down from 186 peak") + last 8 movement-ledger rows. Single round-trip; year is implicit (latest). Anomaly flags + Pythag still deferred (need RS/RA snapshot + expected-wins derivation).
22. ✅ **History view content** — done 2026-05-12. All five sections (Records / Awards / HoF / Streaks / Draft) live. Hub page links through to each retrospective.
23. **League view content** — standings (item 15) + leaderboards (item 20) + compare (item 18) shipped. Awards races + FA pool still pending.
24. **World view content** — all-leagues browser; thin until scope expands.
25. ✅ **Chart Builder + per-player charts (spray, EV-LA)** *(bundled)* — done 2026-05-13. Per-player spray + EV-LA scatter live **inline on the player page** (gated on bip_count > 0; pitchers / non-MLB call-ups gracefully drop the sections). `/explore` is now the **Chart Builder workshop** — pick X (and optional Y, color) from the 32-stat catalog, filter by year/level/qualifier, render via `Plot.dot` (scatter mode) or `Plot.binX` + `Plot.rectY` (histogram mode when Y is omitted). Cross-table is fair game — every supported stat keys on (player, year, league, level) so the API LEFT-JOINs source tables transparently ("Avg EV vs HR" works). Backed by `GET /api/chart-builder?x=&y=&color=&year=&level_id=&qualifier_min=`. Permanent redirects forward old `/explore/spray|ev-la|leaderboards|compare` URLs to the new homes.

   **Stadium-overlay spray chart upgrade (2026-05-13 round 2)**: replaced the polar-fan SprayChart with a Savant-style **field-overlay scatter** — every BIP plotted at its synthesized field-absolute (angle, distance) position over a hand-drawn stadium silhouette. Distance estimated from `(EV² × sin(2·LA)) / g × drag_factor` with HR floor at park's foul-pole distance × 1.05. Stadium catalog (`web/lib/stadiums.ts`) covers all 30 MLB parks with official wall distances + heights; signature feature flair for **Fenway** (Green Monster — extra-thick LF segment + label), **Yankee Stadium** (short porch — indigo RF segment + PORCH label), **Wrigley** (ivy — dashed wall fill), **Oracle Park** (McCovey Cove — blue band beyond RF), **Daikin Park** (CF train rail), and dome parks (faint roof arc). Picker dropdown switches stadiums at the chart level; default is the active save's home park (`save.org_team_abbr`, BOS for the Sox save). Distance synthesized from EV+LA via projectile physics with empirical drag — HRs floored to clear the foul-pole distance × 1.05.

   **Player-page tab restructure (same round)**: page was a single long scroll (Stats → Spray → EV/LA → AI). Now `?tab=` (query-string state) drives a tab-filtered view: **Stats** (default) / **Charts** (Spray + EV/LA together) / **AI Summary** / placeholders for Game log / Comparisons / Scouting. Bio header + Service & Status + CareerArc + Contract stay always-visible above the tab bar (the "page metadata" strip). Charts tab disables itself for non-batters via `hasBip` gate.
26. **Color-blind mode v2** — extend the `cb` theme to swap verdict / badge palettes (currently chrome-only).
27. ✅ **AI overlay v1** — done 2026-05-13. `diamond/ai/` package with keyring-backed key storage + Anthropic + OpenAI adapters via httpx (no SDK deps). Endpoints: `GET /api/ai/settings`, `POST /api/ai/settings` (provider / model / use_level + write-only api_key), `POST /api/ai/summarize` (kind=player). Settings UI at `/settings/ai`; "✨ Summarize career" button on player page. v1 ships **on-demand** tier (the four-tier API surface lives in the schema but only acts on "off" gating). Pricing fetcher / daily cap / smart auto-runs / additional providers (Gemini / Ollama) deferred to v1.1.
28. **Reviews** — most AI-heavy, last because it depends on everything else.
29. ✅ **Setup wizard v1** — done 2026-05-13. `/settings/save` lives. `GET /api/saves` enumerates `*.lg` directories under the OOTP saves root with `has_warehouse` flag + `is_active` flag; `POST /api/saves/active` switches active save (validates name exists, persists to `~/.diamond/active_save.toml`, swaps in-memory warehouse singleton). UI cards per save with Active / Needs ingest badges.

   **Setup wizard v2.1 (2026-05-13 evening):** per-save scope is now persisted. `~/.diamond/save_configs.toml` stores `audit_team_id` + `reference_scope_enabled` + `league_ids` per save; `_resolve_initial_save()` and `build_save_config()` read it to construct the live SaveConfig. New endpoints `GET /api/saves/{name}/config` + `POST /api/saves/{name}/config` drive an inline Configure form on each save card — division-grouped 30-team dropdown for the audit_team_id pick + a reference-scope toggle. `POST /api/saves/active` now refuses (409) to activate a save that hasn't been configured (the gate prevents Sox-data-on-Padres-save confusion). `diamond ingest` gets a `--save NAME` flag so each save's warehouse can be built independently from the CLI. Legacy "Building the Green Monster.lg" gets a one-time bootstrap on first import so existing users don't hit the is_configured gate. Static `mlb_teams.py` catalog (30 entries: ARI/ATL/.../WSH with team_id 1-30 + city + division) backs the picker.
30. ✅ **Auto-ingest + in-app refresh (2026-05-13 evening)** — `dev.bat` chains `diamond ingest --all` between kill-stale and uvicorn so OOTP-side dumps land before the API binds. New endpoints `GET /api/admin/dump-status` (lock-free read; counts pending dumps via read-only DuckDB connection) + `POST /api/admin/ingest` (acquires warehouse lock, runs `build_warehouse(force=False, rebuild=True)`, releases). Header gets `RefreshButton.tsx` — polls dump-status every 60s, badge when pending, click triggers synchronous ingest. Plus `diamond status` CLI for terminal introspection.

31. ✅ **Photo cache D24 (2026-05-13 evening)** — `/api/photos/players/{id}.png` flipped from `max-age=86400, immutable` to ETag + Last-Modified revalidation with `Cache-Control: no-cache`. Newly-rendered face PNGs appear instantly when OOTP regenerates instead of after a 24h browser cache. 404s drop their cache header entirely.

32. ✅ **LSEG-Workspace density refactor D25 (2026-05-13 evening)** — full-width layout (drops `max-w-6xl`); compact 36px sticky header with backdrop-blur; `useElementWidth` hook drives responsive Plot charts (EvLaScatter + ChartBuilder fill containers, StadiumSprayChart caps at 720px); page-headers across 9 main pages collapsed from `text-3xl space-y-8` → LSEG-uniform `[CATEGORY] [Title · context]` pattern with `space-y-4`; default body `text-sm`; settings pages keep narrow `max-w-3xl` form containers. Reference shots in `docs/ui_examples/`.

33. **L_REF reference layer D26 (next major work, 2026-05-13 evening finding)** — new ingest module reading from `<docs>/Out of the Park Developments/OOTP Baseball 27/`: authoritative ballpark dimensions (`pt_ballparks.txt` 240 rows + `era_ballparks.txt` 3,105 rows × 155 years), era league averages (`era_stats.txt`), OOTP↔Lahman crosswalk (`stats/Master.csv` 24,747 rows), MiLB master (29MB), 1,829 logos with per-era variants (`.oi` files are PNGs, magic bytes confirmed), 343 ballcaps. Replaces `web/lib/stadiums.ts`, upgrades D22 to era-aware LH/RH-split park factors, swaps Chadwick crosswalk, enables real-team-logo rendering everywhere. See BACKLOG.md for slice breakdown.

**Sync triggers + tracked-save management** — folded into the auto-ingest item (30) above.

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
- **Contact** — the Statcast cohort. **Two columns post-D41 (2026-05-10)**:
  Max EV (90th-percentile) + HH%. Pitcher rows interpret HH% as
  allowed-contact (lower = better; tooltip clarifies). Sub-30-BIP rows
  render as dashes. The earlier 6-column form (BIP / Max EV / Avg EV /
  HH% / Brl% / SS%) was trimmed because BIP (80-82% IE match), Avg EV
  (83-87%), Brl% (74% batting), and SS% (no IE counterpart) couldn't
  meet D41's bit-for-bit OOTP match invariant. The L3 builder still
  materializes the dropped columns as drift watch + Phase 4b
  invariants-watchdog inputs. See **DATA_QUIRKS.md** for the full
  ledger of dropped columns + the L_IE re-enable path.

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
- [D22 — Historical park factors backfill](DECISIONS.md#d22--historical-park-factors-backfill-lahman-bpfppf-for-2019-mlb-seasons)
- [D23 — Chart stack: Observable Plot for cohort viz](DECISIONS.md#d23--chart-stack-observable-plot-for-cohort-viz-defer-vega-lite--webgl-until-json-spec-authoring-lands)
- [D24 — Photo cache: revalidation-based, no artificial TTL](DECISIONS.md#d24--photo-cache-revalidation-based-no-artificial-ttl)
- [D25 — LSEG-Workspace density refactor](DECISIONS.md#d25--lseg-workspace-density-refactor-full-width-responsive-charts-terminal-aesthetic)
- [D26 — L_REF reference layer from OOTP parent-folder data](DECISIONS.md#d26--l_ref-reference-layer-from-ootp-parent-folder-data)
- [D15 — Stat dictionary as single source of truth](DECISIONS.md#d15-stat-dictionary-as-single-source-of-truth)
- [D16 — Tech stack: FastAPI + Next.js](DECISIONS.md#d16-tech-stack-fastapi--nextjs-app-router-pydantic-derived-ts-types)
- [D17 — Information architecture: five-tab scope+purpose nav](DECISIONS.md#d17-information-architecture-five-tab-scopepurpose-nav)
- [D18 — UI theme system: CSS-variable semantic tokens, four themes, dark default](DECISIONS.md#d18-ui-theme-system-css-variable-semantic-tokens-four-themes-dark-default)

Decisions still to be recorded as they crystallize:
- Specific anomaly-detection algorithms
- Universe export schema
- Theming approach
