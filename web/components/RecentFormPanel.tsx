// RecentFormPanel — "Last 7 / 15 / 30 days" stat lines on the player page.
//
// Phase 4b Tier D, D40. Consumes `/api/players/{id}/recent` which
// aggregates from the game-grain fact tables (`f_player_game_batting`
// + `f_player_game_pitching`). Window anchor is the player's most
// recent regular-season game (NOT today) — so retired players show
// their final-week form, mid-season views show through the latest dump.
//
// v1: shows all three windows stacked. No interactive toggle yet —
// the data payload is tiny (3 batting rows + 3 pitching rows) so we
// don't bother hiding any of it. A click-to-highlight pill toggle is
// a Phase 4b UI-rollout follow-up.
//
// Renders nothing if both `bat` and `pit` are empty (e.g. amateurs
// with no game data, or a warehouse predating Phase 4b Tier A).

import type { PlayerRecentResponse } from "@/lib/types/api";

interface Props {
  data: PlayerRecentResponse | null;
}

// Slash-line display: ".321" not "0.321"; null → "—".
function fmtSlash(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const s = value.toFixed(3);
  return value < 1 ? s.replace(/^0/, "") : s;
}

// Two-decimal display for ERA / WHIP / K-9 / BB-9; null → "—".
function fmt2(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(2);
}

// Bref-style IP display (172.1 = 172⅓). Source-of-truth comes from
// the backend as a float already.
function fmtIp(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(1);
}

// Localized date range — "Jul 24–31, 2028" reads better than
// "2028-07-24 to 2028-07-31". Compact for tight cells.
function formatDateRange(
  first: string | null | undefined,
  last: string | null | undefined,
): string {
  if (!first || !last) return "—";
  // Parse as local date so we don't TZ-shift the day backwards.
  const [fy, fm, fd] = first.split("-").map(Number);
  const [ly, lm, ld] = last.split("-").map(Number);
  const a = new Date(fy, fm - 1, fd);
  const b = new Date(ly, lm - 1, ld);
  const fmt: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const aStr = a.toLocaleDateString(undefined, fmt);
  const bStr = b.toLocaleDateString(undefined, fmt);
  if (a.getFullYear() === b.getFullYear()) {
    if (a.getMonth() === b.getMonth()) {
      // "Jul 24-31" — both fall in the same month
      return `${aStr.split(" ")[0]} ${a.getDate()}–${b.getDate()}, ${b.getFullYear()}`;
    }
    return `${aStr} – ${bStr}, ${b.getFullYear()}`;
  }
  return `${aStr}, ${a.getFullYear()} – ${bStr}, ${b.getFullYear()}`;
}

export function RecentFormPanel({ data }: Props) {
  if (!data) return null;
  const hasBat = data.bat.length > 0;
  const hasPit = data.pit.length > 0;
  if (!hasBat && !hasPit) return null;

  return (
    <section className="space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-content-primary">
          Recent form
        </h2>
        <p className="text-xs text-content-muted">
          Rolling calendar-day windows ending at last regular-season game.
        </p>
      </header>

      {hasBat && (
        <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
          <table className="min-w-full text-sm">
            <thead className="bg-surface-elevated text-content-secondary">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Window</th>
                <th className="px-2 py-2 text-right font-medium">G</th>
                <th className="px-2 py-2 text-right font-medium">PA</th>
                <th className="px-2 py-2 text-right font-medium">AB</th>
                <th className="px-2 py-2 text-right font-medium">H</th>
                <th className="px-2 py-2 text-right font-medium">2B</th>
                <th className="px-2 py-2 text-right font-medium">HR</th>
                <th className="px-2 py-2 text-right font-medium">R</th>
                <th className="px-2 py-2 text-right font-medium">RBI</th>
                <th className="px-2 py-2 text-right font-medium">BB</th>
                <th className="px-2 py-2 text-right font-medium">K</th>
                <th className="px-2 py-2 text-right font-medium">SB</th>
                <th className="px-2 py-2 text-right font-medium">AVG</th>
                <th className="px-2 py-2 text-right font-medium">OBP</th>
                <th className="px-2 py-2 text-right font-medium">SLG</th>
                <th className="px-2 py-2 text-right font-medium">OPS</th>
                <th className="px-3 py-2 text-left font-medium text-content-muted">Span</th>
              </tr>
            </thead>
            <tbody>
              {data.bat.map((row) => (
                <tr key={`bat-${row.window_days}`} className="border-t border-border">
                  <td className="px-3 py-2 font-medium text-content-primary">
                    Last {row.window_days}d
                  </td>
                  {row.games_in_window === 0 ? (
                    <td
                      colSpan={16}
                      className="px-3 py-2 text-center text-content-muted"
                    >
                      No regular-season games in window
                    </td>
                  ) : (
                    <>
                      <td className="px-2 py-2 text-right">{row.games_in_window}</td>
                      <td className="px-2 py-2 text-right">{row.pa}</td>
                      <td className="px-2 py-2 text-right">{row.ab}</td>
                      <td className="px-2 py-2 text-right">{row.h}</td>
                      <td className="px-2 py-2 text-right">{row.d}</td>
                      <td className="px-2 py-2 text-right">{row.hr}</td>
                      <td className="px-2 py-2 text-right">{row.r}</td>
                      <td className="px-2 py-2 text-right">{row.rbi}</td>
                      <td className="px-2 py-2 text-right">{row.bb}</td>
                      <td className="px-2 py-2 text-right">{row.k}</td>
                      <td className="px-2 py-2 text-right">{row.sb}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmtSlash(row.avg)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmtSlash(row.obp)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmtSlash(row.slg)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmtSlash(row.ops)}</td>
                      <td className="px-3 py-2 text-left text-xs text-content-muted">
                        {formatDateRange(row.first_date, row.last_date)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasPit && (
        <div className="overflow-x-auto rounded-md border border-border bg-surface-card">
          <table className="min-w-full text-sm">
            <thead className="bg-surface-elevated text-content-secondary">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Window</th>
                <th className="px-2 py-2 text-right font-medium">G</th>
                <th className="px-2 py-2 text-right font-medium">GS</th>
                <th className="px-2 py-2 text-right font-medium">IP</th>
                <th className="px-2 py-2 text-right font-medium">H</th>
                <th className="px-2 py-2 text-right font-medium">R</th>
                <th className="px-2 py-2 text-right font-medium">ER</th>
                <th className="px-2 py-2 text-right font-medium">BB</th>
                <th className="px-2 py-2 text-right font-medium">K</th>
                <th className="px-2 py-2 text-right font-medium">HR</th>
                <th className="px-2 py-2 text-right font-medium">ERA</th>
                <th className="px-2 py-2 text-right font-medium">WHIP</th>
                <th className="px-2 py-2 text-right font-medium">K/9</th>
                <th className="px-2 py-2 text-right font-medium">BB/9</th>
                <th className="px-3 py-2 text-left font-medium text-content-muted">Span</th>
              </tr>
            </thead>
            <tbody>
              {data.pit.map((row) => (
                <tr key={`pit-${row.window_days}`} className="border-t border-border">
                  <td className="px-3 py-2 font-medium text-content-primary">
                    Last {row.window_days}d
                  </td>
                  {row.games_in_window === 0 ? (
                    <td
                      colSpan={14}
                      className="px-3 py-2 text-center text-content-muted"
                    >
                      No appearances in window
                    </td>
                  ) : (
                    <>
                      <td className="px-2 py-2 text-right">{row.games_in_window}</td>
                      <td className="px-2 py-2 text-right">{row.starts}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmtIp(row.ip_display)}</td>
                      <td className="px-2 py-2 text-right">{row.h}</td>
                      <td className="px-2 py-2 text-right">{row.r}</td>
                      <td className="px-2 py-2 text-right">{row.er}</td>
                      <td className="px-2 py-2 text-right">{row.bb}</td>
                      <td className="px-2 py-2 text-right">{row.k}</td>
                      <td className="px-2 py-2 text-right">{row.hr_allowed}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmt2(row.era)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmt2(row.whip)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmt2(row.k_per_9)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums">{fmt2(row.bb_per_9)}</td>
                      <td className="px-3 py-2 text-left text-xs text-content-muted">
                        {formatDateRange(row.first_date, row.last_date)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
