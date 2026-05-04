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
  PlayerBattingSeason,
  PlayerBattingStint,
  PlayerCareerBatting,
  PlayerCareerPitching,
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
// header (rate-per-9 derivatives), pin the header here. Tooltip still
// pulls from the related dictionary entry.
const COLUMN_HEADER_OVERRIDES: Partial<Record<string, string>> = {
  k_per_9: "K/9",
  bb_per_9: "BB/9",
  ip_display: "IP",
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
const SLASH_FIELDS = new Set(["avg", "obp", "slg", "ops"]);
// ERA / WHIP / K9 / BB9 render to 2 decimals.
const TWO_DP_FIELDS = new Set(["era", "whip", "k_per_9", "bb_per_9"]);
// IP renders as `int.frac` (Bref convention: 172.1 = 172⅓).
const IP_FIELDS = new Set(["ip_display"]);

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
  // Counting stats: integer display.
  return Number.isInteger(value) ? String(value) : value.toString();
}

// ─────────────────────────────────────────────────────────────────────────
// Team / level cell
// ─────────────────────────────────────────────────────────────────────────

function TeamCell({ team }: { team: TeamRef | null }) {
  if (!team) {
    return <span className="font-mono text-slate-400">TOT</span>;
  }
  return (
    <span className="font-mono">
      <span className="text-slate-800">{team.abbr ?? "—"}</span>
      {team.level_name && team.level_name !== "MLB" && (
        <span className="ml-1.5 rounded bg-slate-100 px-1 text-[10px] text-slate-500">
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
        className={`border-t border-slate-100 ${
          isMultiStint ? "cursor-pointer hover:bg-slate-50" : ""
        }`}
        onClick={isMultiStint ? onToggle : undefined}
      >
        <td className="w-16 px-2 py-1.5 text-left font-mono text-sm tabular-nums">
          {isMultiStint && (
            <span
              className={`mr-1 inline-block transition-transform ${
                expanded ? "rotate-90" : ""
              } text-slate-400`}
            >
              ▶
            </span>
          )}
          {season.year}
        </td>
        <td className="w-12 px-2 py-1.5 text-right font-mono text-xs text-slate-500">
          {season.age ?? "—"}
        </td>
        <td className="w-32 px-2 py-1.5 text-left">
          <TeamCell team={headRow.team} />
        </td>
        {BATTING_COLUMNS.map(([field]) => (
          <td
            key={field as string}
            className="px-2 py-1.5 text-right font-mono text-sm tabular-nums"
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
            className="border-t border-slate-50 bg-slate-50/40 text-slate-600"
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
        className={`border-t border-slate-100 ${
          isMultiStint ? "cursor-pointer hover:bg-slate-50" : ""
        }`}
        onClick={isMultiStint ? onToggle : undefined}
      >
        <td className="w-16 px-2 py-1.5 text-left font-mono text-sm tabular-nums">
          {isMultiStint && (
            <span
              className={`mr-1 inline-block transition-transform ${
                expanded ? "rotate-90" : ""
              } text-slate-400`}
            >
              ▶
            </span>
          )}
          {season.year}
        </td>
        <td className="w-12 px-2 py-1.5 text-right font-mono text-xs text-slate-500">
          {season.age ?? "—"}
        </td>
        <td className="w-32 px-2 py-1.5 text-left">
          <TeamCell team={headRow.team} />
        </td>
        {PITCHING_COLUMNS.map(([field]) => (
          <td
            key={field as string}
            className="px-2 py-1.5 text-right font-mono text-sm tabular-nums"
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
            className="border-t border-slate-50 bg-slate-50/40 text-slate-600"
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
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      <div className="overflow-x-auto rounded-md border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
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
    <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold">
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

function PitchingCareerRow({
  career,
  columnOrder,
}: {
  career: PlayerCareerPitching;
  columnOrder: Array<[keyof PlayerPitchingStint, string]>;
}) {
  return (
    <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold">
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

  return (
    <div className="space-y-8">
      {!hasBatting && !hasPitching && (
        <p className="text-sm text-slate-500">
          No batting or pitching stats yet for this player.
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
    </div>
  );
}
