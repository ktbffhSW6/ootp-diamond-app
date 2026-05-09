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
  PlayerPositionFielding,
  PlayerResponse,
  PlayerSituationalRow,
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

// ─────────────────────────────────────────────────────────────────────────
// Defensive profile — per-position scouted-rating cube
//
// Surfaces players_fielding_current.fielding_rating_pos1..9 + _pot +
// fielding_experience1..9 from `position_fielding`. Sorted by experience
// descending so the "where they actually play" view comes first.
// Empty rows (zero rating, zero experience) collapse to a single
// "no scouted ratings" line — keeps the table dense for the typical
// case (~3-4 positions of real signal per player).
// ─────────────────────────────────────────────────────────────────────────

// Color hint for the 20-80 rating scale (matches scouting convention).
// Cells stay the same width — only the text color shifts.
function ratingClass(rating: number | null): string {
  if (rating == null) return "text-content-muted";
  if (rating >= 70) return "text-emerald-700 dark:text-emerald-300 font-semibold";
  if (rating >= 60) return "text-emerald-600 dark:text-emerald-400";
  if (rating >= 50) return "text-content-primary";
  if (rating >= 40) return "text-amber-700 dark:text-amber-400";
  return "text-rose-700 dark:text-rose-400";
}

function DefensiveProfileTable({
  rows,
}: {
  rows: PlayerPositionFielding[];
}) {
  // Hide rows that have nothing to say at all (no current rating, no
  // ceiling, no experience). For most position players this still
  // leaves 4-7 rows; for pitchers it usually leaves just P.
  const meaningful = rows.filter(
    (r) =>
      r.rating_current != null ||
      r.rating_potential != null ||
      r.experience != null,
  );

  if (meaningful.length === 0) {
    return null;
  }

  // Sort by experience desc (nulls last), then by rating desc as
  // tiebreaker — surfaces the spots the player has actually logged
  // innings at first.
  const sorted = [...meaningful].sort((a, b) => {
    const expA = a.experience ?? -1;
    const expB = b.experience ?? -1;
    if (expB !== expA) return expB - expA;
    return (b.rating_current ?? 0) - (a.rating_current ?? 0);
  });

  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        Defensive Profile
      </h2>
      <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-elevated text-xs uppercase text-content-muted">
            <tr>
              <th className="w-16 px-2 py-1.5 text-left font-medium">Pos</th>
              <th
                className="px-2 py-1.5 text-right font-medium"
                title="Current scouted rating at this position (20-80 scale). Reflects the user's scouting view."
              >
                Current
              </th>
              <th
                className="px-2 py-1.5 text-right font-medium"
                title="Ceiling at this position (20-80 scale) — what the player projects to if they keep getting reps."
              >
                Ceiling
              </th>
              <th
                className="px-2 py-1.5 text-right font-medium"
                title="OOTP play-attempt counter at this position. A relative weight, not a sample-size threshold — useful for ranking 'where this guy actually plays' vs 'where they could play.'"
              >
                Plays
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.position} className="border-t border-border">
                <td className="px-2 py-1.5 text-left font-mono text-sm text-content-primary">
                  {r.position_name}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono text-sm tabular-nums ${ratingClass(r.rating_current)}`}
                >
                  {r.rating_current ?? "—"}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono text-sm tabular-nums ${ratingClass(r.rating_potential)}`}
                >
                  {r.rating_potential ?? "—"}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                  {r.experience ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-content-muted">
        20-80 scale (50 = league-average defender). Sorted by play count
        — the spots above the table&apos;s &ldquo;—&rdquo; experience
        rows are where the player&apos;s actually logged innings; the
        spots below show ceiling without realized reps. Source:
        latest{" "}
        <code className="font-mono text-[11px]">players_fielding_current</code>.
      </p>
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
// Situational splits (clutch / RISP) — shared batting + pitching renderer
// ─────────────────────────────────────────────────────────────────────────
//
// One block per (year, level) tuple, sorted year DESC + level (MLB first).
// `f_pa_event` is multi-year now (L0 cross-dump dedup at L2 build time),
// so a player with a 4-year career can show 4-16 blocks (more if they
// bounced through MLB + AAA + AA in any year).
//
// Two callers share the same renderer:
// - `SituationalBattingTable` (side="batter") — slash is what the
//   player HIT. Higher OPS in clutch = good. Color: emerald above All
//   baseline, rose below.
// - `SituationalPitchingTable` (side="pitcher") — slash is what the
//   pitcher ALLOWED. Higher OPS in clutch = bad. Color flips: emerald
//   below All baseline (kept opp from scoring), rose above (gave up
//   too much).
//
// Each tuple shows four rows: All / RISP / RISP, 2 out / Late & Close.
// The "All" row is the parity baseline — its slash should match the
// regular batting section's row for the same (year, level). When OPS
// in a split row beats the All row's OPS we render the value in
// emerald (clutch hitter); when it lags we render in rose. The
// magnitude isn't surfaced numerically — qualitative cue only — to
// keep the table dense.

function fmtSlash(v: number | null): string {
  if (v == null) return "—";
  const s = v.toFixed(3);
  return v < 1 ? s.replace(/^0/, "") : s;
}

type SituationalSide = "batter" | "pitcher";

function opsCellClass(
  splitOps: number | null,
  baselineOps: number | null,
  isBaseline: boolean,
  side: SituationalSide,
): string {
  // Baseline (the "All" row) always renders in primary content color so
  // the eye anchors there. Splits with no sample stay neutral.
  if (isBaseline || splitOps == null || baselineOps == null) {
    return "text-content-primary";
  }
  // 25-point OPS gap = the Bref-conventional "clutch" threshold on the
  // splits page. Anything inside ±25 reads as noise; outside it as
  // signal. Small samples are inherently noisy — the cue is
  // qualitative, not predictive.
  //
  // For batters: higher OPS in clutch = good (emerald). For pitchers:
  // higher OPS allowed in clutch = bad (rose). The color directions
  // invert; the threshold magnitude is the same.
  const delta = splitOps - baselineOps;
  const goodThreshold = side === "batter" ? 0.025 : -0.025;
  const badThreshold = side === "batter" ? -0.025 : 0.025;
  if (side === "batter") {
    if (delta >= goodThreshold) return "text-emerald-600 dark:text-emerald-400";
    if (delta <= badThreshold) return "text-rose-600 dark:text-rose-400";
  } else {
    if (delta <= goodThreshold) return "text-emerald-600 dark:text-emerald-400";
    if (delta >= badThreshold) return "text-rose-600 dark:text-rose-400";
  }
  return "text-content-primary";
}

interface SituationalGroup {
  year: number;
  level_id: number;
  level_name: string | null;
  rows: PlayerSituationalRow[];
}

function groupSituational(rows: PlayerSituationalRow[]): SituationalGroup[] {
  const groups = new Map<string, SituationalGroup>();
  for (const r of rows) {
    const key = `${r.year}-${r.level_id}`;
    let g = groups.get(key);
    if (!g) {
      g = {
        year: r.year,
        level_id: r.level_id,
        level_name: r.level_name,
        rows: [],
      };
      groups.set(key, g);
    }
    g.rows.push(r);
  }
  // Group iteration matches insertion order — and the API returns rows
  // pre-sorted year DESC + level (MLB first), so we get the right
  // group order for free.
  return [...groups.values()];
}

function SituationalTable({
  rows,
  side,
}: {
  rows: PlayerSituationalRow[];
  side: SituationalSide;
}) {
  const groups = groupSituational(rows);
  const title =
    side === "batter" ? "Situational batting" : "Situational pitching";

  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-content-muted">
        {title}
      </h2>
      <div className="space-y-4">
        {groups.map((g) => {
          const baselineOps =
            g.rows.find((r) => r.split === "all")?.ops ?? null;
          return (
            <div
              key={`${g.year}-${g.level_id}`}
              className="overflow-x-auto rounded-md border border-border bg-surface-card"
            >
              <header className="flex items-baseline gap-2 border-b border-border bg-surface-elevated/50 px-3 py-1.5 text-xs">
                <span className="font-mono text-content-primary">
                  {g.year}
                </span>
                <span className="text-content-muted">·</span>
                <span className="font-mono text-content-secondary">
                  {g.level_name ?? `level ${g.level_id}`}
                </span>
                <span className="ml-auto text-[10px] uppercase tracking-wide text-content-muted">
                  Regular season
                </span>
              </header>
              <table className="min-w-full text-sm">
                <thead className="bg-surface-elevated/30 text-xs uppercase text-content-muted">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium">
                      Split
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Plate appearances">
                      PA
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="At-bats">
                      AB
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Hits">
                      H
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Doubles">
                      2B
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Triples">
                      3B
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Home runs">
                      HR
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Walks">
                      BB
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Strikeouts">
                      K
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Batting average — H/AB">
                      AVG
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="On-base percentage">
                      OBP
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="Slugging percentage">
                      SLG
                    </th>
                    <th className="px-2 py-1.5 text-right font-medium" title="On-base + slugging">
                      OPS
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {g.rows.map((r) => {
                    const isBaseline = r.split === "all";
                    const opsClass = opsCellClass(
                      r.ops,
                      baselineOps,
                      isBaseline,
                      side,
                    );
                    return (
                      <tr
                        key={r.split}
                        className={
                          isBaseline
                            ? "border-t border-border bg-surface-elevated/40"
                            : "border-t border-border"
                        }
                      >
                        <td
                          className={
                            isBaseline
                              ? "px-3 py-1.5 text-left text-sm font-semibold text-content-primary"
                              : "px-3 py-1.5 text-left text-sm text-content-secondary"
                          }
                        >
                          {r.split_label}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {r.pa}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {r.ab}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {r.h}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                          {r.doubles}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                          {r.triples}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                          {r.hr}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                          {r.bb}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-secondary">
                          {r.k}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {fmtSlash(r.avg)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {fmtSlash(r.obp)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-sm tabular-nums text-content-primary">
                          {fmtSlash(r.slg)}
                        </td>
                        <td
                          className={`px-2 py-1.5 text-right font-mono text-sm tabular-nums ${opsClass}`}
                        >
                          {fmtSlash(r.ops)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
      <p className="mt-1 text-xs text-content-muted">
        <strong>RISP</strong> = runner on 2nd or 3rd at start of PA.
        {" "}<strong>RISP, 2 out</strong> = the same with two outs (the
        last-out RBI chance). <strong>Late &amp; Close</strong> = 7th
        inning or later with the tying run on base, at the plate, or on
        deck.{" "}
        {side === "batter" ? (
          <>
            OPS in a split row is colored emerald when it beats the
            &ldquo;All&rdquo; baseline by ≥25 points, rose when it
            lags by ≥25 — clutch hitters reach for the ball.
          </>
        ) : (
          <>
            Slash columns reflect what the pitcher{" "}
            <em>allowed</em>; OPS-allowed in a split row is colored
            emerald when it&apos;s ≥25 points{" "}
            <em>better</em> (lower) than the &ldquo;All&rdquo;
            baseline, rose when it&apos;s ≥25 points worse — clutch
            pitchers shrink the strike zone with runners on.
          </>
        )}
        {" "}Smaller gaps are noise on small samples. Splits are
        regular season only and cover every save year the warehouse
        has ingested.
      </p>
    </section>
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
  const hasDefensiveProfile = (player.position_fielding ?? []).some(
    (r) =>
      r.rating_current != null ||
      r.rating_potential != null ||
      r.experience != null,
  );
  // Situational requires actual PA — empty arrays for the
  // wrong-handed audience (pitchers don't get batter splits;
  // position players don't get pitcher splits) and for pre-warehouse
  // imports without a per-PA log.
  const hasSituationalBatting =
    (player.situational_batting ?? []).length > 0;
  const hasSituationalPitching =
    (player.situational_pitching ?? []).length > 0;

  return (
    <div className="space-y-8">
      {!hasBatting && !hasPitching && !hasFielding && !hasDefensiveProfile && (
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

      {hasSituationalBatting && (
        <SituationalTable rows={player.situational_batting} side="batter" />
      )}

      {hasSituationalPitching && (
        <SituationalTable rows={player.situational_pitching} side="pitcher" />
      )}

      {hasFielding && (
        <FieldingTable
          rows={player.fielding_rows}
          career={player.fielding_career}
          headers={fieldingHeaders}
        />
      )}

      {hasDefensiveProfile && (
        <DefensiveProfileTable rows={player.position_fielding} />
      )}
    </div>
  );
}
