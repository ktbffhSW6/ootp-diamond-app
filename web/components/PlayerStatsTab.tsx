"use client";

// Stats tab for the player page. Renders Bref-shaped year-by-year
// disclosure-row tables for batting + pitching.
//
// Disclosure pattern: when a player had multiple stints in a season
// (promotion/demotion or trade), the default row is the synthesized
// "TOT" combined row with a chevron; clicking expands an indented
// list of per-(level, team) stints below it.
//
// Per D15 (single-source-of-truth dictionary): every column header
// renders from `glossary[id].short_label`, with the first sentence
// of `description` as the tooltip. No hand-coded labels.
//
// Why a client component: the disclosure interaction needs useState.
// The bio header + tab strip stay server-rendered in the parent.

import { useState } from "react";

import type {
  GlossaryEntry,
  GlossaryListResponse,
  PlayerAdvancedBattingRow,
  PlayerAdvancedPitchingRow,
  PlayerBattingSeason,
  PlayerBattingStint,
  PlayerCareerBatting,
  PlayerCareerFielding,
  PlayerCareerPitching,
  PlayerFieldingRow,
  PlayerPitchingSeason,
  PlayerPitchingStint,
  PlayerResponse,
  TeamRef,
} from "@/lib/types/api";

// ─────────────────────────────────────────────────────────────────────────
// Dictionary lookup helpers
// ─────────────────────────────────────────────────────────────────────────

// Map field-name (matching Pydantic schema fields) → dictionary id.
// Keeps the mapping explicit so a rename on either side surfaces here
// rather than as a silently missing tooltip. The order of entries
// here is also the column order in the table.
const BATTING_COLUMNS: Array<[keyof PlayerBattingStint, string]> = [
  ["g", "G_batter"],
  ["pa", "PA"],
  ["ab", "AB"],
  ["r", "R"],
  ["h", "H"],
  ["d", "D"],
  ["t", "T"],
  ["hr", "HR"],
  ["rbi", "RBI"],
  ["sb", "SB"],
  ["bb", "BB"],
  ["so", "K_batter"],
  ["avg", "AVG"],
  ["obp", "OBP"],
  ["slg", "SLG"],
  ["ops", "OPS"],
];

// Advanced batting columns. Per-(year, league_id, level_id) grain
// from f_player_season_advanced_batting; multi-team-same-level stints
// collapse to one row using the dominant team's park factor.
//
// Order intent: counting → rate → value. bWAR (OOTP-canonical, IE-A-tier)
// + oWAR (offense-only, custom) sit side-by-side so the defensive
// component is the visible difference between the two columns.
const ADV_BATTING_COLUMNS: Array<[keyof PlayerAdvancedBattingRow, string]> = [
  ["pa", "PA"],
  ["woba", "wOBA"],
  ["wraa", "wRAA"],
  ["wrc", "wRC"],
  ["wrc_plus", "wRC_plus"],
  ["ops_plus", "OPS_plus"],
  ["o_war", "oWAR"],
  ["b_war", "bWAR"],
];

// Advanced pitching: pWAR (OOTP-canonical, IE-A-tier) + custom pit_WAR
// (flat-1.13-replacement) + RA9-WAR (runs-based parallel — defense /
// sequencing-sensitive). Three views of the same season.
const ADV_PITCHING_COLUMNS: Array<[keyof PlayerAdvancedPitchingRow, string]> = [
  ["ip_display", "IP"],
  ["fip", "FIP"],
  ["era_plus", "ERA_plus"],
  ["pit_war", "pit_WAR"],
  ["p_war", "pWAR"],
  ["p_ra9_war", "RA9_WAR"],
];

// Fielding columns. The schema is keyed by (year, position, team), so
// rows are flat rather than disclosure-grouped — see schemas/player.py
// for why combining across positions doesn't carry meaning.
const FIELDING_COLUMNS: Array<[keyof PlayerFieldingRow, string]> = [
  ["g", "G_fielder"],
  ["gs", "GS_fielder"],
  ["inn_display", "INN"],
  ["po", "PO"],
  ["a", "A"],
  ["e", "E"],
  ["dp", "DP"],
  ["fpct", "FPCT"],
];

const PITCHING_COLUMNS: Array<[keyof PlayerPitchingStint, string]> = [
  ["w", "W"],
  ["l", "L"],
  ["era", "ERA"],
  ["g", "G_pitcher"],
  ["gs", "GS"],
  ["sv", "SV"],
  ["ip_display", "IP"],
  ["h", "H_allowed"],
  ["r", "R_allowed"],
  ["er", "ER"],
  ["hr", "HR_allowed"],
  ["bb", "BB_allowed"],
  ["so", "K_pitcher"],
  ["whip", "WHIP"],
  ["k_per_9", "K_pitcher"],   // K/9 reuses the K dictionary entry; column header overridden below
  ["bb_per_9", "BB_allowed"], // ditto for BB/9
];

// Where the field-name → dictionary lookup doesn't capture the column
// header (rate-per-9 derivatives, IP/INN display variants), pin the
// header here. Tooltip still pulls from the related dictionary entry.
const COLUMN_HEADER_OVERRIDES: Partial<Record<string, string>> = {
  k_per_9: "K/9",
  bb_per_9: "BB/9",
  ip_display: "IP",
  inn_display: "INN",
};

function buildGlossaryIndex(g: GlossaryListResponse): Record<string, GlossaryEntry> {
  return Object.fromEntries(g.entries.map((e) => [e.id, e]));
}

function tooltipFor(entry: GlossaryEntry | undefined): string | undefined {
  if (!entry) return undefined;
  // First sentence of description is the canonical short tooltip.
  const firstSentence = entry.description.split(".")[0];
  return firstSentence ? `${firstSentence}.` : entry.description;
}

// ─────────────────────────────────────────────────────────────────────────
// Cell formatting
// ─────────────────────────────────────────────────────────────────────────

// Slash-line stats render to 3 decimals leading-zero-stripped (Bref style).
// FPCT + wOBA share the same convention (.985, .992, .380, etc.).
const SLASH_FIELDS = new Set(["avg", "obp", "slg", "ops", "fpct", "woba"]);
// ERA / WHIP / K9 / BB9 / FIP render to 2 decimals.
const TWO_DP_FIELDS = new Set(["era", "whip", "k_per_9", "bb_per_9", "fip"]);
// IP / INN render as `int.frac` (Bref convention: 172.1 = 172⅓).
const IP_FIELDS = new Set(["ip_display", "inn_display"]);
// One-decimal stats (WAR, runs).
const ONE_DP_FIELDS = new Set([
  "o_war", "b_war",
  "pit_war", "p_war", "p_ra9_war",
  "wraa", "wrc",
]);

function formatCell(field: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value !== "number") return String(value);
  if (SLASH_FIELDS.has(field)) {
    // ".000" not "0.000" — stripped leading zero for sub-1 values
    const s = value.toFixed(3);
    return value < 1 ? s.replace(/^0/, "") : s;
  }
  if (TWO_DP_FIELDS.has(field)) {
    return value.toFixed(2);
  }
  if (IP_FIELDS.has(field)) {
    return value.toFixed(1);
  }
  if (ONE_DP_FIELDS.has(field)) {
    return value.toFixed(1);
  }
  // Counting stats: integer display.
  return Number.isInteger(value) ? String(value) : value.toString();
}

// ─────────────────────────────────────────────────────────────────────────
// Team / level cell
// ─────────────────────────────────────────────────────────────────────────

function TeamCell({ team }: { team: TeamRef | null }) {
  if (!team) {
    return <span className="font-mono text-content-muted">TOT</span>;
  }
  return (
    <span className="font-mono">
      <span className="text-content-primary">{team.abbr ?? "—"}</span>
      {team.level_name && team.level_name !== "MLB" && (
        <span className="ml-1.5 rounded bg-surface-elevated px-1 text-[10px] text-content-muted">
          {team.level_name}
        </span>
      )}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Disclosure row — one batting season
// ─────────────────────────────────────────────────────────────────────────

interface BattingSeasonRowProps {
  season: PlayerBattingSeason;
  expanded: boolean;
  onToggle: () => void;
}

function BattingSeasonRow({ season, expanded, onToggle }: BattingSeasonRowProps) {
  const isMultiStint = season.combined != null;
  const headRow = isMultiStint ? season.combined! : season.stints[0];
  return (
    <>
      <tr
        className={`border-t border-border ${
          isMultiStint ? "cursor-pointer hover:bg-surface-elevated" : ""
        }`}
        onClick={isMultiStint ? onToggle : undefined}
      >
        <td className="w-16 px-2 py-1.5 text-left font-mono text-sm tabular-nums text-content-primary">
          {isMultiStint && (
            <span
              className={`mr-1 inline-block transition-transform ${
                expanded ? "rotate-90" : ""
              } text-content-muted`}
            >
              ▶
            </span>
          )}
          {season.year}
        </td>
        <td className="w-12 px-2 py-1.5 text-right font-mono text-xs text-content-muted">
          {season.age ?? "—"}
        </td>
        <td className="w-32 px-2 py-1.5 text-left">
          <TeamCell team={headRow.team} />
        </td>
        {BATTING_COLUMNS.map(([field]) => (
          <td
            key={field as string}
            className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary"
          >
            {formatCell(field as string, (headRow as unknown as Record<string, unknown>)[field as string])}
          </td>
        ))}
      </tr>
      {isMultiStint &&
        expanded &&
        season.stints.map((stint, idx) => (
          <tr
            key={`${stint.team?.team_id ?? idx}-${stint.team?.level_id ?? idx}`}
            className="border-t border-border bg-surface-elevated/40 text-content-secondary"
          >
            <td className="px-2 py-1 text-left font-mono text-xs"></td>
            <td className="px-2 py-1 text-right"></td>
            <td className="pl-6 pr-2 py-1 text-left">
              <TeamCell team={stint.team} />
            </td>
            {BATTING_COLUMNS.map(([field]) => (
              <td
                key={field as string}
                className="px-2 py-1 text-right font-mono text-xs tabular-nums"
              >
                {formatCell(field as string, (stint as unknown as Record<string, unknown>)[field as string])}
              </td>
            ))}
          </tr>
        ))}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Disclosure row — one pitching season
// ─────────────────────────────────────────────────────────────────────────

interface PitchingSeasonRowProps {
  season: PlayerPitchingSeason;
  expanded: boolean;
  onToggle: () => void;
}

function PitchingSeasonRow({ season, expanded, onToggle }: PitchingSeasonRowProps) {
  const isMultiStint = season.combined != null;
  const headRow = isMultiStint ? season.combined! : season.stints[0];
  return (
    <>
      <tr
        className={`border-t border-border ${
          isMultiStint ? "cursor-pointer hover:bg-surface-elevated" : ""
        }`}
        onClick={isMultiStint ? onToggle : undefined}
      >
        <td className="w-16 px-2 py-1.5 text-left font-mono text-sm tabular-nums text-content-primary">
          {isMultiStint && (
            <span
              className={`mr-1 inline-block transition-transform ${
                expanded ? "rotate-90" : ""
              } text-content-muted`}
            >
              ▶
            </span>
          )}
          {season.year}
        </td>
        <td className="w-12 px-2 py-1.5 text-right font-mono text-xs text-content-muted">
          {season.age ?? "—"}
        </td>
        <td className="w-32 px-2 py-1.5 text-left">
          <TeamCell team={headRow.team} />
        </td>
        {PITCHING_COLUMNS.map(([field]) => (
          <td
            key={field as string}
            className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary"
          >
            {formatCell(field as string, (headRow as unknown as Record<string, unknown>)[field as string])}
          </td>
        ))}
      </tr>
      {isMultiStint &&
        expanded &&
        season.stints.map((stint, idx) => (
          <tr
            key={`${stint.team?.team_id ?? idx}-${stint.team?.level_id ?? idx}`}
            className="border-t border-border bg-surface-elevated/40 text-content-secondary"
          >
            <td className="px-2 py-1 text-left font-mono text-xs"></td>
            <td className="px-2 py-1 text-right"></td>
            <td className="pl-6 pr-2 py-1 text-left">
              <TeamCell team={stint.team} />
            </td>
            {PITCHING_COLUMNS.map(([field]) => (
              <td
                key={field as string}
                className="px-2 py-1 text-right font-mono text-xs tabular-nums"
              >
                {formatCell(field as string, (stint as unknown as Record<string, unknown>)[field as string])}
              </td>
            ))}
          </tr>
        ))}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Tables
// ─────────────────────────────────────────────────────────────────────────

interface ColumnHeader {
  field: string;
  label: string;
  tooltip?: string;
}

function buildHeaders(
  columns: Array<[string, string]>,
  glossary: Record<string, GlossaryEntry>,
): ColumnHeader[] {
  return columns.map(([field, dictId]) => {
    const entry = glossary[dictId];
    const overrideLabel = COLUMN_HEADER_OVERRIDES[field];
    return {
      field,
      label: overrideLabel ?? entry?.short_label ?? field.toUpperCase(),
      tooltip: tooltipFor(entry),
    };
  });
}

function StatTable({
  title,
  headers,
  body,
}: {
  title: string;
  headers: ColumnHeader[];
  body: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-elevated text-xs uppercase text-content-muted">
            <tr>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Year</th>
              <th className="w-12 px-2 py-1.5 text-right font-medium">Age</th>
              <th className="w-32 px-2 py-1.5 text-left font-medium">Team</th>
              {headers.map((h) => (
                <th
                  key={h.field}
                  className="px-2 py-1.5 text-right font-medium"
                  title={h.tooltip}
                >
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Career-totals row
// ─────────────────────────────────────────────────────────────────────────

function BattingCareerRow({
  career,
  columnOrder,
}: {
  career: PlayerCareerBatting;
  columnOrder: Array<[keyof PlayerBattingStint, string]>;
}) {
  return (
    <tr className="border-t-2 border-border-strong bg-surface-elevated font-semibold text-content-primary">
      <td className="px-2 py-1.5 text-left text-sm" colSpan={2}>
        Career
      </td>
      <td className="px-2 py-1.5"></td>
      {columnOrder.map(([field]) => (
        <td
          key={field as string}
          className="px-2 py-1.5 text-right font-mono text-sm tabular-nums"
        >
          {formatCell(field as string, (career as unknown as Record<string, unknown>)[field as string])}
        </td>
      ))}
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Advanced — per (year, league, level) flat rows
// ─────────────────────────────────────────────────────────────────────────

function AdvancedBattingTable({
  rows,
  headers,
}: {
  rows: PlayerAdvancedBattingRow[];
  headers: ColumnHeader[];
}) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        Advanced Batting
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-elevated text-xs uppercase text-content-muted">
            <tr>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Year</th>
              <th className="w-12 px-2 py-1.5 text-right font-medium">Age</th>
              <th className="w-20 px-2 py-1.5 text-left font-medium">Lvl/Lg</th>
              {headers.map((h) => (
                <th
                  key={h.field}
                  className="px-2 py-1.5 text-right font-medium"
                  title={h.tooltip}
                >
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={`${r.year}-${r.level_id}-${r.league_id}`}
                className="border-t border-border"
              >
                <td className="px-2 py-1.5 text-left font-mono text-sm tabular-nums text-content-primary">
                  {r.year}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs text-content-muted">
                  {r.age ?? "—"}
                </td>
                <td className="px-2 py-1.5 text-left font-mono">
                  <span className="text-content-primary">{r.level_name}</span>
                  <span className="ml-1 text-xs text-content-muted">
                    {r.league_abbr ?? "—"}
                  </span>
                </td>
                {ADV_BATTING_COLUMNS.map(([field]) => (
                  <td
                    key={field as string}
                    className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary"
                  >
                    {formatCell(field as string, (r as unknown as Record<string, unknown>)[field as string])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-content-muted">
        Per-(year, level) grain. Multi-team-same-level seasons collapse
        into one row using the dominant team&apos;s park factor.{" "}
        <strong>oWAR</strong> is Diamond&apos;s offense-only formula
        (wRAA-based); <strong>bWAR</strong> is OOTP&apos;s combined WAR
        (offense + defense + position + base-running, IE-reconciled).
        Gap = the defensive component. League constants are 2026-2029-only
        in this save — earlier years show &ldquo;—&rdquo; when no
        historical league baseline exists.
      </p>
    </section>
  );
}

function AdvancedPitchingTable({
  rows,
  headers,
}: {
  rows: PlayerAdvancedPitchingRow[];
  headers: ColumnHeader[];
}) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        Advanced Pitching
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-elevated text-xs uppercase text-content-muted">
            <tr>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Year</th>
              <th className="w-12 px-2 py-1.5 text-right font-medium">Age</th>
              <th className="w-20 px-2 py-1.5 text-left font-medium">Lvl/Lg</th>
              {headers.map((h) => (
                <th
                  key={h.field}
                  className="px-2 py-1.5 text-right font-medium"
                  title={h.tooltip}
                >
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={`${r.year}-${r.level_id}-${r.league_id}`}
                className="border-t border-border"
              >
                <td className="px-2 py-1.5 text-left font-mono text-sm tabular-nums text-content-primary">
                  {r.year}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-xs text-content-muted">
                  {r.age ?? "—"}
                </td>
                <td className="px-2 py-1.5 text-left font-mono">
                  <span className="text-content-primary">{r.level_name}</span>
                  <span className="ml-1 text-xs text-content-muted">
                    {r.league_abbr ?? "—"}
                  </span>
                </td>
                {ADV_PITCHING_COLUMNS.map(([field]) => (
                  <td
                    key={field as string}
                    className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary"
                  >
                    {formatCell(field as string, (r as unknown as Record<string, unknown>)[field as string])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-content-muted">
        Pitchers with ≥10 IP at the level only. Park-aware: ERA+ uses
        80% park factor (audit convention); pit_WAR uses replacement
        FIP × 1.13. <strong>pWAR</strong> is OOTP&apos;s directly-supplied
        FIP-WAR (with leverage adjustment for relievers — IE-reconciled).
        <strong> RA9-WAR</strong> is the runs-based parallel — gap vs
        pWAR signals defense / sequencing rather than skill differential.
      </p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Fielding — flat rows + per-position career rollup
// ─────────────────────────────────────────────────────────────────────────

function FieldingRowItem({ row }: { row: PlayerFieldingRow }) {
  return (
    <tr className="border-t border-border">
      <td className="w-16 px-2 py-1.5 text-left font-mono text-sm tabular-nums text-content-primary">
        {row.year}
      </td>
      <td className="w-12 px-2 py-1.5 text-right font-mono text-xs text-content-muted">
        {row.age ?? "—"}
      </td>
      <td className="w-16 px-2 py-1.5 text-left font-mono text-sm text-content-primary">
        {row.position_name}
      </td>
      <td className="w-32 px-2 py-1.5 text-left">
        <TeamCell team={row.team} />
      </td>
      {FIELDING_COLUMNS.map(([field]) => (
        <td
          key={field as string}
          className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary"
        >
          {formatCell(field as string, (row as unknown as Record<string, unknown>)[field as string])}
        </td>
      ))}
    </tr>
  );
}

function FieldingCareerRow({
  career,
}: {
  career: PlayerCareerFielding;
}) {
  return (
    <tr className="border-t-2 border-border-strong bg-surface-elevated font-semibold text-content-primary">
      <td className="px-2 py-1.5 text-left text-sm" colSpan={2}>
        Career
      </td>
      <td className="w-16 px-2 py-1.5 text-left font-mono text-sm">
        {career.position_name}
      </td>
      <td></td>
      {FIELDING_COLUMNS.map(([field]) => (
        <td
          key={field as string}
          className="px-2 py-1.5 text-right font-mono text-sm tabular-nums"
        >
          {formatCell(field as string, (career as unknown as Record<string, unknown>)[field as string])}
        </td>
      ))}
    </tr>
  );
}

function FieldingTable({
  rows,
  career,
  headers,
}: {
  rows: PlayerFieldingRow[];
  career: PlayerCareerFielding[];
  headers: ColumnHeader[];
}) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        Fielding
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-elevated text-xs uppercase text-content-muted">
            <tr>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Year</th>
              <th className="w-12 px-2 py-1.5 text-right font-medium">Age</th>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Pos</th>
              <th className="w-32 px-2 py-1.5 text-left font-medium">Team</th>
              {headers.map((h) => (
                <th
                  key={h.field}
                  className="px-2 py-1.5 text-right font-medium"
                  title={h.tooltip}
                >
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <FieldingRowItem
                key={`${r.year}-${r.position}-${r.team?.team_id ?? "x"}`}
                row={r}
              />
            ))}
            {career.length > 0 &&
              career.map((c) => (
                <FieldingCareerRow key={c.position} career={c} />
              ))}
          </tbody>
        </table>
      </div>
      {career.length > 1 && (
        <p className="mt-1 text-xs text-content-muted">
          Career rows are per-position; cross-position totals omitted on
          purpose (combining PO+A+E across positions doesn&apos;t carry
          meaningful semantics).
        </p>
      )}
    </section>
  );
}

function PitchingCareerRow({
  career,
  columnOrder,
}: {
  career: PlayerCareerPitching;
  columnOrder: Array<[keyof PlayerPitchingStint, string]>;
}) {
  return (
    <tr className="border-t-2 border-border-strong bg-surface-elevated font-semibold text-content-primary">
      <td className="px-2 py-1.5 text-left text-sm" colSpan={2}>
        Career
      </td>
      <td className="px-2 py-1.5"></td>
      {columnOrder.map(([field]) => (
        <td
          key={field as string}
          className="px-2 py-1.5 text-right font-mono text-sm tabular-nums"
        >
          {formatCell(field as string, (career as unknown as Record<string, unknown>)[field as string])}
        </td>
      ))}
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────

export function PlayerStatsTab({
  player,
  glossary,
}: {
  player: PlayerResponse;
  glossary: GlossaryListResponse;
}) {
  const dict = buildGlossaryIndex(glossary);
  const battingHeaders = buildHeaders(
    BATTING_COLUMNS as Array<[string, string]>,
    dict,
  );
  const pitchingHeaders = buildHeaders(
    PITCHING_COLUMNS as Array<[string, string]>,
    dict,
  );
  const fieldingHeaders = buildHeaders(
    FIELDING_COLUMNS as Array<[string, string]>,
    dict,
  );
  const advBattingHeaders = buildHeaders(
    ADV_BATTING_COLUMNS as Array<[string, string]>,
    dict,
  );
  const advPitchingHeaders = buildHeaders(
    ADV_PITCHING_COLUMNS as Array<[string, string]>,
    dict,
  );

  const [expandedBatting, setExpandedBatting] = useState<Set<number>>(
    () => new Set(),
  );
  const [expandedPitching, setExpandedPitching] = useState<Set<number>>(
    () => new Set(),
  );

  const toggle = (
    set: Set<number>,
    setter: (v: Set<number>) => void,
    year: number,
  ) => {
    const next = new Set(set);
    if (next.has(year)) next.delete(year);
    else next.add(year);
    setter(next);
  };

  const hasBatting = player.batting_seasons.length > 0;
  const hasPitching = player.pitching_seasons.length > 0;
  const hasFielding = player.fielding_rows.length > 0;
  const hasAdvBatting = player.advanced_batting.length > 0;
  const hasAdvPitching = player.advanced_pitching.length > 0;

  return (
    <div className="space-y-8">
      {!hasBatting && !hasPitching && !hasFielding && (
        <p className="text-sm text-content-muted">
          No batting, pitching, or fielding stats yet for this player.
        </p>
      )}

      {hasBatting && (
        <StatTable
          title="Batting"
          headers={battingHeaders}
          body={
            <>
              {player.batting_seasons.map((s) => (
                <BattingSeasonRow
                  key={s.year}
                  season={s}
                  expanded={expandedBatting.has(s.year)}
                  onToggle={() =>
                    toggle(expandedBatting, setExpandedBatting, s.year)
                  }
                />
              ))}
              {player.batting_career && (
                <BattingCareerRow
                  career={player.batting_career}
                  columnOrder={BATTING_COLUMNS}
                />
              )}
            </>
          }
        />
      )}

      {hasPitching && (
        <StatTable
          title="Pitching"
          headers={pitchingHeaders}
          body={
            <>
              {player.pitching_seasons.map((s) => (
                <PitchingSeasonRow
                  key={s.year}
                  season={s}
                  expanded={expandedPitching.has(s.year)}
                  onToggle={() =>
                    toggle(expandedPitching, setExpandedPitching, s.year)
                  }
                />
              ))}
              {player.pitching_career && (
                <PitchingCareerRow
                  career={player.pitching_career}
                  columnOrder={PITCHING_COLUMNS}
                />
              )}
            </>
          }
        />
      )}

      {hasAdvBatting && (
        <AdvancedBattingTable
          rows={player.advanced_batting}
          headers={advBattingHeaders}
        />
      )}

      {hasAdvPitching && (
        <AdvancedPitchingTable
          rows={player.advanced_pitching}
          headers={advPitchingHeaders}
        />
      )}

      {hasFielding && (
        <FieldingTable
          rows={player.fielding_rows}
          career={player.fielding_career}
          headers={fieldingHeaders}
        />
      )}
    </div>
  );
}
