// History · Records — all-time leaderboards.
//
// Drains the first /history stub. Backed by `GET /api/records?scope=
// &discipline=&category=&era=` which UNIONs save data, Lahman
// 1871-2019, BREF 2020-2025, the merged cross-source dedup, and
// Statcast 2015-2025 batted-ball quality.
//
// Server component; pickers are <Link> grids (no client state). Each
// row links to /player/<id> when the underlying record has an OOTP
// player_id (save universe). External-only rows (lahman/bref/statcast
// players who aren't in the save) render as plain text — no clickable
// target since the save's player pages don't extend to those people.
//
// Defaults (all optional via query string): scope=season, discipline=
// batting, category=HR, era=all, limit=25. Bad query strings fall
// back to defaults rather than 404'ing — deep-linked URLs stay alive.

import Link from "next/link";

import { getRecords } from "@/lib/api";
import type {
  RecordCategoryRef,
  RecordRow,
  RecordsResponse,
} from "@/lib/types/api";

export const metadata = { title: "Records — Diamond" };
export const dynamic = "force-dynamic";

// ─────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────

function fmtValue(category: string, value: number): string {
  // IP convention: outs → "X.Y" (Y ∈ {0,1,2}). f_record_player stores
  // IP as float-IP already (e.g. 4234.0 or 4234.1), but for the season
  // pitching IP records the underlying value is OOTP outs. Detect:
  // values with fractional .0/.33/.67 should be left alone; integer
  // values are outs. The simpler heuristic — IP records are always
  // <10000 and always integer outs in our build — formats safely.
  if (category === "IP") {
    const outs = Math.round(value);
    return `${Math.floor(outs / 3)}.${outs % 3}`;
  }
  if (category === "WAR") return value.toFixed(1);
  if (category === "MAX_EV" || category === "AVG_EV") return value.toFixed(1);
  if (
    category === "HARD_HIT_PCT" ||
    category === "BARREL_PCT" ||
    category === "SWEET_SPOT_PCT"
  ) {
    return value.toFixed(1);
  }
  if (category === "MAX_DIST") return Math.round(value).toString();
  // Counters: render as integer
  return Math.round(value).toString();
}

function fmtUnit(unit: string): string {
  if (!unit) return "";
  if (unit === "%") return "%";
  return ` ${unit}`;
}

// ─────────────────────────────────────────────────────────────────────
// Source chip — color-coded by source so multi-source leaderboards
// stay scannable at a glance.
// ─────────────────────────────────────────────────────────────────────

const SOURCE_LABEL: Record<string, string> = {
  save: "Save",
  lahman: "Lahman",
  bref: "BREF",
  merged: "Merged",
  statcast: "Statcast",
};

const SOURCE_TOOLTIP: Record<string, string> = {
  save:
    "Your OOTP save universe — counting stats from save play + imported real-history baseline.",
  lahman:
    "Real-life MLB history 1871-2019 (Lahman archive).",
  bref:
    "Real-life MLB 2020-2025 (Baseball-Reference, fills the post-Lahman gap).",
  merged:
    "Real-life career rollup — Lahman + BREF cross-source dedup keyed on bbref_id (Pujols Lahman 656 + BREF 30 = 686).",
  statcast:
    "Real Statcast 2015-2025 (pybaseball). EV / barrel / sweet-spot leaderboards.",
};

function SourceChip({ source }: { source: string }) {
  const label = SOURCE_LABEL[source] ?? source;
  const tooltip = SOURCE_TOOLTIP[source] ?? "";
  // Distinct hue per source — pairs with theme tokens via dark: overrides.
  const cls =
    source === "save"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
      : source === "lahman"
        ? "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300"
        : source === "bref"
          ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
          : source === "merged"
            ? "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300"
            : source === "statcast"
              ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
              : "bg-surface-elevated text-content-muted";
  return (
    <span
      title={tooltip}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${cls}`}
    >
      {label}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Picker rows — three flat axes (Scope / Discipline / Category) plus
// the orthogonal Era filter. Every option is a <Link> with the full
// query string baked in; switching axes is a navigation, not a state
// mutation. No client component needed.
// ─────────────────────────────────────────────────────────────────────

function buildHref(args: {
  scope: string;
  discipline: string;
  category: string;
  era: string;
}): string {
  const params = new URLSearchParams({
    scope: args.scope,
    discipline: args.discipline,
    category: args.category,
    era: args.era,
  });
  return `/history/records?${params.toString()}`;
}

function PillRow({
  label,
  options,
  current,
  hrefBuilder,
  optionLabel,
  optionTitle,
}: {
  label: string;
  options: string[];
  current: string;
  hrefBuilder: (option: string) => string;
  optionLabel?: (option: string) => string;
  optionTitle?: (option: string) => string;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
        {label}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {options.map((opt) => {
          const active = opt === current;
          const display = optionLabel ? optionLabel(opt) : opt;
          const title = optionTitle?.(opt);
          return (
            <Link
              key={opt}
              href={hrefBuilder(opt)}
              title={title}
              className={
                active
                  ? "rounded bg-content-primary px-2 py-1 font-mono text-xs text-surface-page"
                  : "rounded border border-border px-2 py-1 font-mono text-xs text-content-secondary hover:bg-surface-elevated"
              }
            >
              {display}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Records table — single section, dense Bref-style layout. Year
// column hides on career-scope views.
// ─────────────────────────────────────────────────────────────────────

function RecordsTable({
  rows,
  scope,
  category,
  unit,
  isPlayerLinkable,
}: {
  rows: RecordRow[];
  scope: "season" | "career";
  category: string;
  unit: string;
  isPlayerLinkable: (row: RecordRow) => boolean;
}) {
  const showYear = scope === "season";
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-border bg-surface-card px-4 py-6 text-sm text-content-muted">
        No records found for this combination of axes + era. Try a different
        era filter (e.g. <span className="font-mono">all</span>) or pick a
        different category.
      </p>
    );
  }
  return (
    <section className="rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-surface-elevated text-[10px] uppercase tracking-wide text-content-muted">
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Rank in this rendered list (re-ranked across sources when era=all)"
            >
              #
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Player</th>
            {showYear && (
              <th className="px-3 py-1.5 text-right font-medium" title="Season">
                Year
              </th>
            )}
            <th className="px-3 py-1.5 text-left font-medium">Team</th>
            <th
              className="px-3 py-1.5 text-right font-medium"
              title="Stat value"
            >
              {category}
            </th>
            <th className="px-3 py-1.5 text-left font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const linkable = isPlayerLinkable(row);
            const nameCell = linkable && row.player_id !== null ? (
              <Link
                href={`/player/${row.player_id}`}
                className="font-medium text-link hover:text-link-hover hover:underline"
              >
                {row.display_name}
              </Link>
            ) : (
              <span
                className="font-medium text-content-primary"
                title={
                  row.external_id
                    ? `External ID: ${row.external_id}`
                    : undefined
                }
              >
                {row.display_name}
              </span>
            );
            return (
              <tr
                key={`${row.source}-${row.rank_in_source}-${row.display_name}-${row.year ?? "career"}`}
                className="border-t border-border hover:bg-surface-elevated"
              >
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-muted">
                  {row.rank}
                </td>
                <td className="px-3 py-1.5 align-middle">{nameCell}</td>
                {showYear && (
                  <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                    {row.year ?? "—"}
                  </td>
                )}
                <td className="px-3 py-1.5 font-mono text-xs text-content-muted">
                  {row.team_abbr ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                  {fmtValue(category, row.value)}
                  {unit && (
                    <span className="ml-0.5 text-[10px] text-content-muted">
                      {fmtUnit(unit)}
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 align-middle">
                  <SourceChip source={row.source} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

const SCOPE_OPTIONS = ["season", "career"] as const;
const DISCIPLINE_OPTIONS = ["batting", "pitching"] as const;
const ERA_OPTIONS = ["all", "save", "real", "statcast"] as const;

const ERA_LABEL: Record<string, string> = {
  all: "All",
  save: "Save",
  real: "Real (Lahman + BREF)",
  statcast: "Statcast",
};

const ERA_TOOLTIP: Record<string, string> = {
  all:
    "Merge every available source and re-rank globally — see save and real-life records side by side.",
  save:
    "Records from your OOTP save universe only.",
  real:
    "Real-life MLB history (Lahman 1871-2019 + BREF 2020-2025 + cross-source merged career totals).",
  statcast:
    "Real Statcast 2015-2025 only — EV / barrel / sweet-spot leaderboards.",
};

const SCOPE_LABEL: Record<string, string> = { season: "Season", career: "Career" };
const DISCIPLINE_LABEL: Record<string, string> = {
  batting: "Batting",
  pitching: "Pitching",
};

export default async function RecordsPage({
  searchParams,
}: {
  searchParams: Promise<{
    scope?: string;
    discipline?: string;
    category?: string;
    era?: string;
  }>;
}) {
  const params = await searchParams;
  const data: RecordsResponse = await getRecords({
    scope:
      params.scope === "season" || params.scope === "career"
        ? params.scope
        : undefined,
    discipline:
      params.discipline === "batting" || params.discipline === "pitching"
        ? params.discipline
        : undefined,
    category: params.category,
    era:
      params.era === "all" ||
      params.era === "save" ||
      params.era === "real" ||
      params.era === "statcast"
        ? params.era
        : undefined,
  });

  const activeCat: RecordCategoryRef | undefined = data.available_categories.find(
    (c) => c.category === data.category,
  );

  // Headline ("Most" vs "Fewest") — pitching rate-stats-allowed sort
  // ascending so lowest = best (the "Fewest" framing).
  const verb = data.direction === "asc" ? "Fewest" : "Most";
  const scopeLabel = SCOPE_LABEL[data.scope] ?? data.scope;
  const disciplineLabel = DISCIPLINE_LABEL[data.discipline] ?? data.discipline;
  const categoryLabel = activeCat?.label ?? data.category;

  // Player linking — when era is filtered to "save", player_id is the
  // OOTP id and clickable. When era is "all" / "real" / "statcast",
  // most rows have only external_id (real-life player not in the save),
  // so we link only when player_id is non-null on the row itself.
  const isPlayerLinkable = (row: RecordRow): boolean => row.player_id !== null;

  // Era filter — hide entirely when only one source exists for this
  // category (Career batting WAR is save-only, for instance). When
  // visible, grey out era options that would yield zero rows for this
  // category.
  const visibleEras = ERA_OPTIONS.filter((e) => {
    if (!activeCat) return true;
    if (e === "all") return true;
    if (e === "save") return activeCat.available_sources.includes("save");
    if (e === "real")
      return (
        activeCat.available_sources.includes("lahman") ||
        activeCat.available_sources.includes("bref") ||
        activeCat.available_sources.includes("merged")
      );
    if (e === "statcast")
      return activeCat.available_sources.includes("statcast");
    return false;
  });
  const showEraFilter = visibleEras.length > 1;

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <p className="text-xs font-medium uppercase tracking-wider text-content-muted">
          History · Records
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {verb} {categoryLabel} — {scopeLabel} {disciplineLabel}
        </h1>
        <p className="text-sm text-content-secondary">
          Showing top {data.rows.length}
          {data.total_in_source > data.rows.length && (
            <span className="text-content-muted">
              {" "}
              of {data.total_in_source}
            </span>
          )}
          {" "}from{" "}
          <span className="font-mono text-content-primary">{ERA_LABEL[data.era]}</span>
          {data.era === "all" && (
            <>
              {" "}— save, real-life Lahman + BREF, merged career rollups, and Statcast all merged into one list.
            </>
          )}
          {data.era === "save" && (
            <>
              {" "}— records from your OOTP save universe.
            </>
          )}
          {data.era === "real" && (
            <>
              {" "}— Lahman 1871-2019 + BREF 2020-2025 + merged career rollups via Chadwick Register.
            </>
          )}
          {data.era === "statcast" && (
            <>
              {" "}— pybaseball Statcast 2015-2025 batted-ball quality leaders.
            </>
          )}
        </p>
      </header>

      <div className="space-y-6">
        <div className="flex flex-wrap gap-x-8 gap-y-4">
          <PillRow
            label="Scope"
            options={[...SCOPE_OPTIONS]}
            current={data.scope}
            optionLabel={(opt) => SCOPE_LABEL[opt] ?? opt}
            hrefBuilder={(opt) =>
              buildHref({
                scope: opt,
                discipline: data.discipline,
                // Reset category — the legal set differs per scope/discipline.
                category: data.category,
                era: data.era,
              })
            }
          />
          <PillRow
            label="Discipline"
            options={[...DISCIPLINE_OPTIONS]}
            current={data.discipline}
            optionLabel={(opt) => DISCIPLINE_LABEL[opt] ?? opt}
            hrefBuilder={(opt) =>
              buildHref({
                scope: data.scope,
                discipline: opt,
                category: data.category,
                era: data.era,
              })
            }
          />
          {showEraFilter && (
            <PillRow
              label="Era"
              options={[...visibleEras]}
              current={data.era}
              optionLabel={(opt) => ERA_LABEL[opt] ?? opt}
              optionTitle={(opt) => ERA_TOOLTIP[opt] ?? ""}
              hrefBuilder={(opt) =>
                buildHref({
                  scope: data.scope,
                  discipline: data.discipline,
                  category: data.category,
                  era: opt,
                })
              }
            />
          )}
        </div>

        <PillRow
          label="Category"
          options={data.available_categories.map((c) => c.category)}
          current={data.category}
          optionTitle={(opt) =>
            data.available_categories.find((c) => c.category === opt)?.label ??
            opt
          }
          hrefBuilder={(opt) =>
            buildHref({
              scope: data.scope,
              discipline: data.discipline,
              category: opt,
              era: data.era,
            })
          }
        />
      </div>

      <RecordsTable
        rows={data.rows}
        scope={data.scope}
        category={data.category}
        unit={activeCat?.unit_label ?? ""}
        isPlayerLinkable={isPlayerLinkable}
      />

      {/* Source legend + caveats — small print so the chips have a key
          and the EV-scale gotcha is documented inline. */}
      <section className="space-y-3 border-t border-border pt-6">
        <h2 className="text-sm font-semibold text-content-secondary">
          Source legend
        </h2>
        <div className="flex flex-wrap gap-3">
          {(["save", "lahman", "bref", "merged", "statcast"] as const).map(
            (s) => (
              <div key={s} className="flex items-center gap-1.5">
                <SourceChip source={s} />
                <span className="text-xs text-content-secondary">
                  {SOURCE_TOOLTIP[s]}
                </span>
              </div>
            ),
          )}
        </div>
        <ul className="mt-2 space-y-1 text-xs text-content-muted">
          <li>
            <strong>Save vs Lahman duplicates</strong> — when a real-life
            record (Bonds 2001 73 HR) shows in both <em>save</em> and{" "}
            <em>lahman</em>, that's expected: OOTP imports Lahman directly,
            so the values match exactly. The two rows confirm the
            integration; era=<span className="font-mono">save</span> or{" "}
            <span className="font-mono">real</span> will show only one.
          </li>
          <li>
            <strong>Statcast EV scale</strong> — OOTP's per-PA exit
            velocity runs ~5 mph below real Statcast (save league-avg ~83
            mph vs real ~88-89). Don't compare save EV records with
            statcast EV records numerically; the source chip distinguishes
            them. See <code>docs/DATA_NOTES.md</code> "Statcast superstat
            calibration" for the full story.
          </li>
          <li>
            <strong>Player links</strong> — players with an OOTP{" "}
            <em>player_id</em> link to their player page. Real-life
            players who aren't in this save (most pre-1990s records) are
            stored only by their <em>bbref_id</em> / <em>mlb_id</em> and
            render as plain text.
          </li>
        </ul>
      </section>
    </div>
  );
}
