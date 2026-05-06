// Roster page — interactive client component over the full org payload.
//
// Why client-side: the page fetches the whole org tree in one round-trip
// (~200 players / ~50KB), and the user wants instant filter / toggle
// response. URL-param-driven server filtering would re-fetch on every
// pill click — sluggish and overkill at this size. State lives here.
//
// Filter shape:
// - Level pills: pick one or many of the levels present in the data.
//   "All" reads as every level on. Click a single pill to drill down.
// - Role pills: All / Position players / Pitchers. Hides the table
//   sections that don't match.
// - Bats / Throws pills: optional further filter on bio.
// - Basic ⇄ Advanced toggle: swaps the visible stat columns. Both
//   stat blocks are already on every row from the server, so this is
//   a column-set switch with no re-fetch.
//
// Table strategy: dense Bref-style. Wide columns scroll horizontally
// on narrow viewports; we don't try to make all stats fit at every
// width because compromising column count makes the table less useful.
//
// Theme tokens per D18: every color is a semantic token
// (surface-card, content-primary, etc.) so the page reads cleanly on
// all four themes (light / dark / neutral / cb).

"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type {
  RosterBattingLine,
  RosterLevelGroup,
  RosterPitchingLine,
  RosterPlayer,
  RosterResponse,
} from "@/lib/types/api";

// ─────────────────────────────────────────────────────────────────────
// Number-formatting helpers — tight, no extra spaces
// ─────────────────────────────────────────────────────────────────────

const DASH = "—";

function fmtSlash(v: number | null): string {
  // Slash-line stat — 3 decimals, drop leading zero (".264" not "0.264").
  if (v === null || v === undefined) return DASH;
  const fixed = v.toFixed(3);
  return fixed.startsWith("0") ? fixed.slice(1) : fixed;
}

function fmt2(v: number | null): string {
  if (v === null || v === undefined) return DASH;
  return v.toFixed(2);
}

function fmt1(v: number | null): string {
  if (v === null || v === undefined) return DASH;
  return v.toFixed(1);
}

function fmtSigned1(v: number | null): string {
  // wRAA convention: signed value with one decimal — "+12.4" / "-3.1".
  // Highlights the relative-to-average meaning at a glance.
  if (v === null || v === undefined) return DASH;
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}`;
}

function fmtInt(v: number | null): string {
  if (v === null || v === undefined) return DASH;
  return String(v);
}

function fmtParkAvg(v: number | null): string {
  // Park factor: 1.00 = neutral. We render Bref-style (e.g. "1.04",
  // "0.97") so a quick scan reveals the home-park bias.
  if (v === null || v === undefined) return DASH;
  return v.toFixed(2);
}

function fmtIp(v: number | null): string {
  // OOTP IP convention: 172.1 means 172⅓, render verbatim.
  if (v === null || v === undefined) return DASH;
  return v.toFixed(1);
}

function fmtWl(w: number, l: number): string {
  return `${w}-${l}`;
}

// ─────────────────────────────────────────────────────────────────────
// Filter / toggle types
// ─────────────────────────────────────────────────────────────────────

type RoleFilter = "all" | "batter" | "pitcher";
type HandFilter = "all" | "R" | "L" | "S";
// Three-way stat-mode toggle:
// - basic    → counting + slash-line / counting + ERA-WHIP-K9-BB9
// - advanced → wOBA / wRC+ / OPS+ / bWAR / FIP / SIERA / ERA+ / pWAR
//              (bWAR + pWAR are OOTP-canonical, IE-reconciled. The custom
//              offense-only oWAR + flat-replacement pit_WAR remain in the
//              warehouse for the glossary cross-reference + player page.)
// - contact  → Statcast cohort (BIP / maxEV / avgEV / HH% / Brl% / SS%)
type StatMode = "basic" | "advanced" | "contact";

// Pill labels — match constants.py LEVEL_NAMES so the pill matches
// the section header text downstream.
const LEVEL_LABEL: Record<number, string> = {
  1: "MLB",
  2: "AAA",
  3: "AA",
  4: "A+",
  5: "A",
  6: "Rk",
  7: "DSL",
  8: "DSL2",
};

// ─────────────────────────────────────────────────────────────────────
// Filter pill — small reusable
// ─────────────────────────────────────────────────────────────────────

function Pill({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={
        active
          ? "rounded-md bg-content-primary px-2.5 py-1 text-xs font-medium text-surface-page"
          : "rounded-md border border-border px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-elevated"
      }
    >
      {children}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Stat-mode segmented control — Basic ⇄ Advanced
// ─────────────────────────────────────────────────────────────────────

const STAT_MODE_LABEL: Record<StatMode, string> = {
  basic: "Basic",
  advanced: "Advanced",
  contact: "Contact",
};

function StatModeToggle({
  mode,
  setMode,
}: {
  mode: StatMode;
  setMode: (m: StatMode) => void;
}) {
  return (
    <div
      className="inline-flex items-center rounded-md border border-border bg-surface-card p-0.5 text-xs font-medium"
      role="group"
      aria-label="Stat mode"
    >
      {(["basic", "advanced", "contact"] as StatMode[]).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => setMode(m)}
          className={
            mode === m
              ? "rounded bg-content-primary px-3 py-1 text-surface-page"
              : "rounded px-3 py-1 text-content-secondary hover:text-content-primary"
          }
        >
          {STAT_MODE_LABEL[m]}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Player row — name + position cell, shared across batter/pitcher tables
// ─────────────────────────────────────────────────────────────────────

function NameCell({ player }: { player: RosterPlayer }) {
  return (
    <td className="px-3 py-1.5 align-middle whitespace-nowrap">
      <Link
        href={`/player/${player.player_id}`}
        className="font-medium text-link underline-offset-2 hover:text-link-hover hover:underline"
      >
        {player.full_name}
      </Link>
    </td>
  );
}

function MetaCells({
  player,
  hand,
}: {
  player: RosterPlayer;
  // For batters we show "B/T" (e.g. "L/R"); for pitchers just the
  // throwing hand since they don't bat in any DH-era league.
  hand: "bt" | "t";
}) {
  return (
    <>
      <td className="px-2 py-1.5 align-middle font-mono text-xs text-content-secondary whitespace-nowrap">
        {player.primary_position}
      </td>
      <td className="px-2 py-1.5 align-middle font-mono text-xs text-content-secondary text-right">
        {player.age ?? DASH}
      </td>
      <td className="px-2 py-1.5 align-middle font-mono text-xs text-content-secondary text-right">
        {hand === "bt" ? `${player.bats}/${player.throws}` : player.throws}
      </td>
      <td className="px-2 py-1.5 align-middle font-mono text-xs text-content-secondary text-right">
        {player.overall_rating ?? DASH}
      </td>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Batter table
// ─────────────────────────────────────────────────────────────────────

function BatterTable({
  players,
  mode,
}: {
  players: RosterPlayer[];
  mode: StatMode;
}) {
  if (players.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="bg-surface-elevated text-left text-[11px] uppercase tracking-wide text-content-muted">
            <th className="px-3 py-2 font-medium">Player</th>
            <th className="px-2 py-2 font-medium">Pos</th>
            <th className="px-2 py-2 font-medium text-right">Age</th>
            <th className="px-2 py-2 font-medium text-right">B/T</th>
            <th className="px-2 py-2 font-medium text-right">OVR</th>
            {mode === "basic" && (
              <>
                <th className="px-2 py-2 font-medium text-right">G</th>
                <th className="px-2 py-2 font-medium text-right">PA</th>
                <th className="px-2 py-2 font-medium text-right">AB</th>
                <th className="px-2 py-2 font-medium text-right">H</th>
                <th className="px-2 py-2 font-medium text-right">HR</th>
                <th className="px-2 py-2 font-medium text-right">RBI</th>
                <th className="px-2 py-2 font-medium text-right">SB</th>
                <th className="px-2 py-2 font-medium text-right">BB</th>
                <th className="px-2 py-2 font-medium text-right">SO</th>
                <th className="px-2 py-2 font-medium text-right">AVG</th>
                <th className="px-2 py-2 font-medium text-right">OBP</th>
                <th className="px-2 py-2 font-medium text-right">SLG</th>
                <th className="px-2 py-2 font-medium text-right">OPS</th>
              </>
            )}
            {mode === "advanced" && (
              <>
                <th className="px-2 py-2 font-medium text-right">PA</th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Weighted On-Base Average — linear-weighted measure of total offensive value per PA. ~.320 is league average."
                >
                  wOBA
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Weighted Runs Above Average — runs created above league average given league context."
                >
                  wRAA
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Weighted Runs Created — total runs produced at league context (not normalized)."
                >
                  wRC
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Weighted Runs Created Plus — wRC park-adjusted, scaled to 100 = league average."
                >
                  wRC+
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="OPS Plus — OPS park-adjusted, scaled to 100 = league average."
                >
                  OPS+
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Combined bWAR — offense + defense (zr + framing + arm) + positional adjustment + base-running. OOTP's directly-supplied WAR field; reconciles to IE WAR as A-tier. (Diamond's offense-only oWAR is in the player page + glossary.)"
                >
                  bWAR
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Park factor used for this row (1.00 = neutral). Halved per Diamond convention before applying to OPS+ / wRC+."
                >
                  Park
                </th>
              </>
            )}
            {mode === "contact" && (
              <>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Balls in play this season at the current level. Threshold for cohort stats is 30 BIP — sub-threshold rows render as dashes."
                >
                  BIP
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Max EV — 90th-percentile exit velocity per Statcast convention (not the absolute peak). Stable signal of top-end power."
                >
                  Max EV
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Average exit velocity across all balls in play."
                >
                  Avg EV
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Hard Hit % — share of BIP at EV ≥ 95 mph."
                >
                  HH%
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Barrel % — Statcast expanding-window definition (EV ≥ 98 + LA window widening with EV)."
                >
                  Brl%
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Sweet Spot % — share of BIP with launch angle in [8°, 32°]."
                >
                  SS%
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <BatterRow key={p.player_id} player={p} mode={mode} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BatterRow({
  player,
  mode,
}: {
  player: RosterPlayer;
  mode: StatMode;
}) {
  const b: RosterBattingLine | null = player.batting;
  return (
    <tr className="border-t border-border hover:bg-surface-elevated">
      <NameCell player={player} />
      <MetaCells player={player} hand="bt" />
      {mode === "basic" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.g ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.pa ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.ab ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.h ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.hr ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.rbi ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.sb ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.bb ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.so ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtSlash(b?.avg ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtSlash(b?.obp ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtSlash(b?.slg ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmtSlash(b?.ops ?? null)}</td>
        </>
      )}
      {mode === "advanced" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.pa ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtSlash(b?.woba ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtSigned1(b?.wraa ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(b?.wrc ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmtInt(b?.wrc_plus ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.ops_plus ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(b?.b_war ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs text-content-muted">
            {fmtParkAvg(b?.park_avg ?? null)}
          </td>
        </>
      )}
      {mode === "contact" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(b?.statcast_bip ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(b?.statcast_max_ev ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(b?.statcast_avg_ev ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(b?.statcast_hard_hit_pct ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(b?.statcast_barrel_pct ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(b?.statcast_sweet_spot_pct ?? null)}</td>
        </>
      )}
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Pitcher table
// ─────────────────────────────────────────────────────────────────────

function PitcherTable({
  players,
  mode,
}: {
  players: RosterPlayer[];
  mode: StatMode;
}) {
  if (players.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="bg-surface-elevated text-left text-[11px] uppercase tracking-wide text-content-muted">
            <th className="px-3 py-2 font-medium">Player</th>
            <th className="px-2 py-2 font-medium">Pos</th>
            <th className="px-2 py-2 font-medium text-right">Age</th>
            <th className="px-2 py-2 font-medium text-right">T</th>
            <th className="px-2 py-2 font-medium text-right">OVR</th>
            {mode === "basic" && (
              <>
                <th className="px-2 py-2 font-medium text-right">G</th>
                <th className="px-2 py-2 font-medium text-right">GS</th>
                <th className="px-2 py-2 font-medium text-right">W-L</th>
                <th className="px-2 py-2 font-medium text-right">SV</th>
                <th className="px-2 py-2 font-medium text-right">IP</th>
                <th className="px-2 py-2 font-medium text-right">ERA</th>
                <th className="px-2 py-2 font-medium text-right">WHIP</th>
                <th className="px-2 py-2 font-medium text-right">K/9</th>
                <th className="px-2 py-2 font-medium text-right">BB/9</th>
              </>
            )}
            {mode === "advanced" && (
              <>
                <th className="px-2 py-2 font-medium text-right">IP</th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Fielding Independent Pitching — ERA-scale estimate built from K/BB/HR/HBP only. Strips out defense + sequencing."
                >
                  FIP
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Skill-Interactive ERA — ERA-scale regression on K/BB/(GB-FB) per BF. Credits weak-contact-inducing skill that FIP ignores."
                >
                  SIERA
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="ERA Plus — ERA inverted, park-adjusted, scaled to 100 = league average. Higher is better."
                >
                  ERA+
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="FIP-WAR — OOTP's directly-supplied pitcher WAR (includes leverage adjustment for relievers). Reconciles to IE WAR as A-tier. (Diamond's custom flat-1.13-replacement pit_WAR is in the player page + glossary.)"
                >
                  pWAR
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Park factor used for this row (1.00 = neutral). Diamond uses 80% of full park factor for ERA+ / pit_WAR."
                >
                  Park
                </th>
              </>
            )}
            {mode === "contact" && (
              <>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Balls in play allowed this season at the current level. Threshold for cohort stats is 30 BIP."
                >
                  BIP
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Max EV allowed — 90th-percentile of contact this pitcher gave up. Lower is better for a pitcher."
                >
                  Max EV
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Average exit velocity allowed across all balls in play."
                >
                  Avg EV
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Hard Hit % allowed — share of BIP at EV ≥ 95 mph. Lower is better."
                >
                  HH%
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Barrel % allowed — share of BIP meeting Statcast's expanding-window barrel definition. Lower is better."
                >
                  Brl%
                </th>
                <th
                  className="px-2 py-2 font-medium text-right"
                  title="Sweet Spot % allowed — share of BIP with launch angle in [8°, 32°]. Lower is better."
                >
                  SS%
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <PitcherRow key={p.player_id} player={p} mode={mode} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PitcherRow({
  player,
  mode,
}: {
  player: RosterPlayer;
  mode: StatMode;
}) {
  const p: RosterPitchingLine | null = player.pitching;
  return (
    <tr className="border-t border-border hover:bg-surface-elevated">
      <NameCell player={player} />
      <MetaCells player={player} hand="t" />
      {mode === "basic" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(p?.g ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(p?.gs ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">
            {p ? fmtWl(p.w, p.l) : DASH}
          </td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(p?.sv ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtIp(p?.ip_display ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt2(p?.era ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt2(p?.whip ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt2(p?.k_per_9 ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt2(p?.bb_per_9 ?? null)}</td>
        </>
      )}
      {mode === "advanced" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtIp(p?.ip_display ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt2(p?.fip ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt2(p?.siera ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmtInt(p?.era_plus ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(p?.p_war ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs text-content-muted">
            {fmtParkAvg(p?.park_avg ?? null)}
          </td>
        </>
      )}
      {mode === "contact" && (
        <>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmtInt(p?.statcast_bip ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(p?.statcast_max_ev ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(p?.statcast_avg_ev ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(p?.statcast_hard_hit_pct ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs font-medium">{fmt1(p?.statcast_barrel_pct ?? null)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-xs">{fmt1(p?.statcast_sweet_spot_pct ?? null)}</td>
        </>
      )}
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Level section — header + position-players table + pitchers table
// ─────────────────────────────────────────────────────────────────────

function LevelSection({
  group,
  role,
  hand,
  mode,
}: {
  group: RosterLevelGroup;
  role: RoleFilter;
  hand: HandFilter;
  mode: StatMode;
}) {
  // Apply hand filter inside the section so the per-table counts and
  // empty-state text reflect filters.
  const handPred = (p: RosterPlayer) =>
    hand === "all"
      ? true
      : (p.bats === hand || (hand === "S" && p.bats === "S"));

  // For pitchers the "B" code is meaningless (they almost never bat in
  // OOTP universal-DH leagues), so we filter pitchers on `throws` when
  // the hand pill is R/L (S not applicable to throws).
  const handPredPitcher = (p: RosterPlayer) =>
    hand === "all" || hand === "S"
      ? true
      : p.throws === hand;

  const positionPlayers =
    role === "pitcher" ? [] : group.position_players.filter(handPred);
  const pitchers = role === "batter" ? [] : group.pitchers.filter(handPredPitcher);

  if (positionPlayers.length === 0 && pitchers.length === 0) return null;

  return (
    <section className="space-y-4">
      <div className="flex items-baseline gap-3">
        <h2 className="text-xl font-semibold text-content-primary">
          {group.level_name}
        </h2>
        <span className="text-sm text-content-muted">
          {positionPlayers.length + pitchers.length} player
          {positionPlayers.length + pitchers.length === 1 ? "" : "s"}
          {role === "all" && (
            <>
              {" "}
              <span className="text-content-muted">
                ({positionPlayers.length} pos · {pitchers.length} P)
              </span>
            </>
          )}
        </span>
      </div>

      {positionPlayers.length > 0 && (
        <div className="space-y-2">
          {role === "all" && (
            <div className="text-xs uppercase tracking-wide text-content-muted">
              Position players
            </div>
          )}
          <BatterTable players={positionPlayers} mode={mode} />
        </div>
      )}

      {pitchers.length > 0 && (
        <div className="space-y-2">
          {role === "all" && (
            <div className="text-xs uppercase tracking-wide text-content-muted">
              Pitchers
            </div>
          )}
          <PitcherTable players={pitchers} mode={mode} />
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Top-level client component
// ─────────────────────────────────────────────────────────────────────

export default function RosterClient({
  data,
}: {
  data: RosterResponse;
}) {
  // Levels actually present in this org's payload — we won't render
  // pills for levels that have zero players (e.g. no DSL team).
  const presentLevelIds = data.groups.map((g) => g.level_id);

  // Filter state. `levels = null` means "all levels"; otherwise it's
  // the explicitly-selected single level. Multi-select is a possible
  // v2 enhancement but single-level drill-down covers the immediate
  // need ("show me just AAA").
  const [level, setLevel] = useState<number | null>(null);
  const [role, setRole] = useState<RoleFilter>("all");
  const [hand, setHand] = useState<HandFilter>("all");
  const [mode, setMode] = useState<StatMode>("basic");

  const visibleGroups = useMemo(
    () => (level === null ? data.groups : data.groups.filter((g) => g.level_id === level)),
    [data.groups, level],
  );

  const totalShown = useMemo(() => {
    let n = 0;
    for (const g of visibleGroups) {
      const pos = role === "pitcher" ? 0 : g.position_players.length;
      const pit = role === "batter" ? 0 : g.pitchers.length;
      n += pos + pit;
    }
    return n;
  }, [visibleGroups, role]);

  return (
    <div className="space-y-8">
      {/* Filter bar — sticks under the page header on long lists */}
      <div className="space-y-3 rounded-md border border-border bg-surface-card p-3">
        {/* Level row */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-content-muted">
            Level
          </span>
          <Pill active={level === null} onClick={() => setLevel(null)}>
            All
          </Pill>
          {presentLevelIds.map((lid) => (
            <Pill
              key={lid}
              active={level === lid}
              onClick={() => setLevel(lid)}
              title={LEVEL_LABEL[lid] ?? `Level ${lid}`}
            >
              {LEVEL_LABEL[lid] ?? `L${lid}`}
            </Pill>
          ))}
        </div>

        {/* Role + Hand + Stat-mode row */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-content-muted">
              Role
            </span>
            <Pill active={role === "all"} onClick={() => setRole("all")}>
              All
            </Pill>
            <Pill
              active={role === "batter"}
              onClick={() => setRole("batter")}
              title="Position players"
            >
              Position
            </Pill>
            <Pill active={role === "pitcher"} onClick={() => setRole("pitcher")}>
              Pitchers
            </Pill>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-content-muted">
              Hand
            </span>
            <Pill active={hand === "all"} onClick={() => setHand("all")}>
              All
            </Pill>
            <Pill
              active={hand === "R"}
              onClick={() => setHand("R")}
              title="Right-handed"
            >
              R
            </Pill>
            <Pill
              active={hand === "L"}
              onClick={() => setHand("L")}
              title="Left-handed"
            >
              L
            </Pill>
            <Pill
              active={hand === "S"}
              onClick={() => setHand("S")}
              title="Switch hitters (batters only)"
            >
              S
            </Pill>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-content-muted">
              Stats
            </span>
            <StatModeToggle mode={mode} setMode={setMode} />
          </div>
        </div>

        <div className="text-xs text-content-muted">
          Showing <span className="font-mono text-content-secondary">{totalShown}</span>{" "}
          player{totalShown === 1 ? "" : "s"} · {data.season} season
        </div>
      </div>

      {/* Empty / level groups */}
      {totalShown === 0 ? (
        <p className="text-sm text-content-muted">
          No players match these filters. Try broadening the level or role
          selection.
        </p>
      ) : (
        <div className="space-y-10">
          {visibleGroups.map((g) => (
            <LevelSection
              key={g.level_id}
              group={g}
              role={role}
              hand={hand}
              mode={mode}
            />
          ))}
        </div>
      )}
    </div>
  );
}
