// PlayerContractCard — salary-by-year bar chart for the player page.
//
// Renders the active contract from `PlayerContract` as a visual
// timeline: one bar per year, height proportional to salary, current
// year highlighted, option years badged, no-trade chip in the
// header. Total + remaining USD totals on the right.
//
// Design notes:
//   - Pure CSS bars (no SVG / chart lib) — each year is a flex column
//     with a div whose height tracks salary / max. Reads like a Bref
//     contract grid but with shape.
//   - Option-year and opt-out badges sit beneath the year label so
//     long contracts (Henderson 8y, Crochet 7y) stay scannable.
//   - Buyout amount surfaces in the tooltip when a year has one.
//
// Skipped for v1: bonus incentives (minimum_pa_bonus, mvp_bonus,
// etc.) and AAV computation. Both are tracked in `contract_current`
// but rarely material to the GM-decision view.

import type { PlayerContract } from "@/lib/types/api";

const M = 1_000_000;

function fmtUsd(amount: number): string {
  if (amount === 0) return "—";
  if (amount >= M) {
    const m = amount / M;
    // 28.8M / 30M / 4M — drop trailing .0 for clean integers
    const fixed = m.toFixed(1);
    return `$${fixed.endsWith(".0") ? fixed.slice(0, -2) : fixed}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return `$${amount.toLocaleString("en-US")}`;
}

function fmtUsdLong(amount: number): string {
  return `$${amount.toLocaleString("en-US")}`;
}

// Option-year badge classes — kept short so they stack under the
// year label without crowding.
const OPTION_BADGE = {
  team: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  player: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  vesting:
    "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
};

interface OptionFlags {
  is_team_option: boolean;
  is_player_option: boolean;
  is_vesting_option: boolean;
}

function optionLabel(flags: OptionFlags): {
  label: string;
  cls: string;
} | null {
  if (flags.is_team_option) return { label: "TO", cls: OPTION_BADGE.team };
  if (flags.is_player_option) return { label: "PO", cls: OPTION_BADGE.player };
  if (flags.is_vesting_option)
    return { label: "VO", cls: OPTION_BADGE.vesting };
  return null;
}

export interface PlayerContractCardProps {
  contract: PlayerContract;
}

export function PlayerContractCard({ contract }: PlayerContractCardProps) {
  // Bar heights — proportional to salary, with a 6px floor so a $0
  // option year still renders as a sliver instead of disappearing.
  const maxSalary = Math.max(...contract.rows.map((r) => r.salary), 1);
  const yearsLabel = `${contract.years}-year deal`;
  const startEnd = `${contract.start_year}–${contract.start_year + contract.years - 1}`;

  return (
    <section className="rounded-md border border-border bg-surface-card">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-border px-4 py-2">
        <h2 className="text-base font-semibold text-content-primary">
          Contract
        </h2>
        <span className="font-mono text-xs text-content-muted">
          {contract.contract_team_abbr ?? "—"} · {yearsLabel} · {startEnd}
        </span>
        <div className="ml-auto flex flex-wrap items-baseline gap-3">
          {contract.no_trade && (
            <span
              className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-800 dark:bg-rose-900/40 dark:text-rose-300"
              title="Full no-trade clause"
            >
              No-trade
            </span>
          )}
          {contract.retained_by_prior_team && (
            <span
              className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
              title="Salary partially retained by a prior team after a trade"
            >
              Retained
            </span>
          )}
          <div className="text-right text-xs text-content-muted">
            <span className="text-content-secondary">Total</span>{" "}
            <span className="font-mono font-semibold text-content-primary">
              {fmtUsd(contract.total_value)}
            </span>
          </div>
          <div className="text-right text-xs text-content-muted">
            <span className="text-content-secondary">Remaining</span>{" "}
            <span className="font-mono font-semibold text-content-primary">
              {fmtUsd(contract.remaining_value)}
            </span>
          </div>
        </div>
      </header>

      <div className="px-4 py-4">
        <div className="flex items-end gap-1.5" style={{ minHeight: 96 }}>
          {contract.rows.map((row) => {
            const heightPct = Math.max(
              6,
              Math.round((row.salary / maxSalary) * 88),
            );
            const isPast =
              contract.current_year_index >= 0 &&
              row.season_index < contract.current_year_index;
            const barColor = row.is_current
              ? "bg-emerald-500 dark:bg-emerald-400"
              : isPast
                ? "bg-content-muted/50 dark:bg-content-muted/30"
                : "bg-sky-500/80 dark:bg-sky-500/70";
            const opt = optionLabel(row);
            const tooltip = [
              `${row.year}: ${fmtUsdLong(row.salary)}`,
              row.is_team_option ? "Team option" : null,
              row.is_player_option ? "Player option" : null,
              row.is_vesting_option ? "Vesting option" : null,
              row.has_buyout ? `Buyout ${fmtUsdLong(row.buyout_amount)}` : null,
              row.can_opt_out ? "Player opt-out" : null,
              row.is_current ? "Current year" : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={row.season_index}
                className="flex min-w-[44px] flex-1 flex-col items-center gap-1"
                title={tooltip}
              >
                <div
                  className="flex w-full flex-col justify-end"
                  style={{ height: 88 }}
                >
                  <div
                    className={`w-full rounded-sm ${barColor}`}
                    style={{ height: `${heightPct}%` }}
                  />
                </div>
                <div
                  className={`font-mono text-[10px] tabular-nums ${
                    row.is_current
                      ? "font-semibold text-emerald-700 dark:text-emerald-400"
                      : "text-content-muted"
                  }`}
                >
                  {fmtUsd(row.salary)}
                </div>
                <div className="font-mono text-[10px] tabular-nums text-content-secondary">
                  {row.year}
                </div>
                <div className="flex flex-wrap justify-center gap-0.5">
                  {opt && (
                    <span
                      className={`rounded px-1 py-px text-[8px] font-semibold uppercase tracking-wide ${opt.cls}`}
                      title={
                        row.is_team_option
                          ? "Team option year"
                          : row.is_player_option
                            ? "Player option year"
                            : "Vesting option year"
                      }
                    >
                      {opt.label}
                    </span>
                  )}
                  {row.has_buyout && (
                    <span
                      className="rounded bg-surface-elevated px-1 py-px text-[8px] font-medium uppercase tracking-wide text-content-muted"
                      title={`Buyout ${fmtUsdLong(row.buyout_amount)}`}
                    >
                      {fmtUsd(row.buyout_amount)} BO
                    </span>
                  )}
                  {row.can_opt_out && (
                    <span
                      className="rounded bg-rose-100 px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-rose-800 dark:bg-rose-900/40 dark:text-rose-300"
                      title="Player can opt out of the remainder of the deal"
                    >
                      Opt
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <footer className="border-t border-border px-4 py-2 text-[10px] text-content-muted">
        <span className="mr-3">
          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-emerald-500" />
          Current year
        </span>
        <span className="mr-3">
          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-content-muted/50" />
          Past
        </span>
        <span className="mr-3">
          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-sky-500/80" />
          Future
        </span>
        <span className="mr-3">
          <strong className="text-amber-700 dark:text-amber-400">TO</strong>{" "}
          team option
        </span>
        <span className="mr-3">
          <strong className="text-sky-700 dark:text-sky-400">PO</strong>{" "}
          player option
        </span>
        <span className="mr-3">
          <strong className="text-violet-700 dark:text-violet-400">VO</strong>{" "}
          vesting option
        </span>
        <span>
          <strong className="text-rose-700 dark:text-rose-400">Opt</strong>{" "}
          player opt-out
        </span>
      </footer>
    </section>
  );
}
