"use client";

// Diamond AI sidebar (D33).
//
// A floating right-side panel reachable from every page via a launcher
// button in the top header. Powers tiers 1-4:
//
//   T1 (page-aware): the sidebar reads usePathname() and posts
//       `page_context.pathname` with every request. The system prompt
//       tells the model "the user is on /player/123 — they're asking
//       about that player unless they say otherwise."
//   T2 (analyst): backend exposes 6 tools (query_warehouse, get_player,
//       compare_players, get_glossary, list_leaderboard_stats,
//       create_metabase_card). The model loops; we render each
//       tool_use / tool_result block inline so the user can see the
//       work.
//   T3 (GM copilot): three quick-action buttons set `mode` to
//       'callup' / 'trade' / 'draft' which the route prepends a
//       structured prompt for.
//   T4 (prompt-to-dashboard): create_metabase_card tool POSTs to
//       Metabase's REST API and returns the card URL; we render a
//       "Open in Workshop" link inline.
//
// Layout: a slide-out panel anchored to the right edge of the
// viewport. ~420px wide when open. Header shows the current page
// context. Body is a scrollable thread. Footer has mode buttons +
// textarea + send.

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
  ChatContentBlock,
  ChatRequest,
  ChatTurn,
} from "@/lib/types/api";
import { sendChat } from "@/lib/ai-chat";

type Mode = "chat" | "callup" | "trade" | "draft";

const MODE_LABELS: Record<Mode, { label: string; hint: string }> = {
  chat: { label: "Chat", hint: "Open-ended" },
  callup: { label: "Call-up", hint: "Roster move" },
  trade: { label: "Trade", hint: "Evaluate idea" },
  draft: { label: "Draft", hint: "Class review" },
};

// localStorage key for the verbose toggle. Persists across sessions
// so a user who turns on tool-call visibility for debugging keeps
// it on between launches.
const VERBOSE_KEY = "diamond.ai.verbose";

export function AISidebar() {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<Mode>("chat");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verbose, setVerbose] = useState(false);
  const pathname = usePathname();
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Load verbose pref from localStorage on mount.
  useEffect(() => {
    try {
      setVerbose(localStorage.getItem(VERBOSE_KEY) === "1");
    } catch {
      // localStorage can throw in some embed contexts; ignore.
    }
  }, []);

  const toggleVerbose = () => {
    setVerbose((v) => {
      const next = !v;
      try {
        localStorage.setItem(VERBOSE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  };

  // Auto-scroll to bottom when new turns arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread, loading]);

  const send = useCallback(
    async (text: string, modeOverride?: Mode) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;
      setLoading(true);
      setError(null);

      const userTurn: ChatTurn = {
        role: "user",
        content: [{ type: "text", text: trimmed }],
      };
      // Optimistic append so the user sees their message instantly.
      const optimistic = [...thread, userTurn];
      setThread(optimistic);
      setInput("");

      const req: ChatRequest = {
        messages: thread,
        user_input: trimmed,
        page_context: { pathname: pathname ?? "/" },
        mode: modeOverride ?? mode,
      };

      try {
        const res = await sendChat(req);
        setThread([...optimistic, ...res.appended]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        // Roll back the optimistic user turn on failure so retries
        // don't accidentally double-append.
        setThread(thread);
        setInput(trimmed);
      } finally {
        setLoading(false);
      }
    },
    [thread, mode, pathname, loading],
  );

  const reset = () => {
    setThread([]);
    setInput("");
    setError(null);
    setMode("chat");
  };

  return (
    <>
      {/* Floating launcher button — bottom-right, always visible */}
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full border border-border bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-lg transition hover:opacity-90"
          title="Open Diamond AI"
        >
          <span aria-hidden="true">✦</span>
          <span>Ask Diamond</span>
        </button>
      )}

      {/* Sidebar panel */}
      <aside
        className={`fixed inset-y-0 right-0 z-40 flex w-[440px] max-w-[95vw] flex-col border-l border-border bg-surface-page shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!open}
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-content-primary">
              Diamond AI
            </div>
            <div className="font-mono text-[11px] text-content-muted">
              ctx: {pathname ?? "/"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleVerbose}
              className={`rounded border px-2 py-1 text-xs transition ${
                verbose
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-content-secondary hover:bg-surface-card"
              }`}
              title={
                verbose
                  ? "Hide tool calls (default)"
                  : "Show tool calls (debug)"
              }
            >
              {verbose ? "Tools ✓" : "Tools"}
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded border border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-card"
              title="New conversation"
            >
              New
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded border border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-card"
              title="Close"
            >
              ✕
            </button>
          </div>
        </header>

        {/* Thread */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {thread.length === 0 && !loading && (
            <EmptyState onPrompt={(t, m) => send(t, m)} />
          )}
          {thread.map((turn, i) => (
            <Turn key={i} turn={turn} verbose={verbose} />
          ))}
          {loading && (
            <div className="my-2 flex items-center gap-2 px-2 py-2 text-xs text-content-muted">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
              Thinking…
            </div>
          )}
          {error && (
            <div className="my-2 rounded border border-rose-700 bg-rose-950/40 p-2 text-xs text-rose-200">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Mode pills (Tier 3) */}
        <div className="flex gap-1 border-t border-border px-3 pt-2">
          {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`flex-1 rounded border px-2 py-1 text-[11px] transition ${
                mode === m
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-content-secondary hover:bg-surface-card"
              }`}
              title={MODE_LABELS[m].hint}
            >
              {MODE_LABELS[m].label}
            </button>
          ))}
        </div>

        {/* Input */}
        <form
          className="flex items-end gap-2 border-t border-border px-3 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder={
              mode === "chat"
                ? "Ask anything about the save…"
                : `${MODE_LABELS[mode].label}: describe the situation…`
            }
            rows={2}
            disabled={loading}
            className="flex-1 resize-none rounded border border-border bg-surface-card px-2 py-1.5 text-sm text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded bg-accent px-3 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </aside>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Empty state — shows quick-prompt suggestions per current page
// ─────────────────────────────────────────────────────────────────────

function EmptyState({
  onPrompt,
}: {
  onPrompt: (text: string, mode?: Mode) => void;
}) {
  const pathname = usePathname() ?? "/";
  const suggestions = pickSuggestions(pathname);
  return (
    <div className="space-y-3 px-2 py-2 text-sm text-content-secondary">
      <p>
        I&apos;m your sabermetrics co-pilot. I can query the warehouse,
        compare players, look up stats, and build Metabase cards for
        you. Try a prompt:
      </p>
      <div className="space-y-1.5">
        {suggestions.map((s, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onPrompt(s.text, s.mode)}
            className="block w-full rounded border border-border bg-surface-card px-3 py-2 text-left text-xs text-content-primary transition hover:border-accent"
          >
            {s.text}
          </button>
        ))}
      </div>
    </div>
  );
}

function pickSuggestions(
  pathname: string,
): { text: string; mode?: Mode }[] {
  if (pathname.startsWith("/player/")) {
    return [
      { text: "Summarize this player's career and current trajectory." },
      { text: "What are this player's strengths and weaknesses by Statcast and leverage stats?" },
      { text: "Compare this player to their peers at the same position." },
    ];
  }
  if (pathname.startsWith("/league") || pathname === "/") {
    return [
      { text: "Who should I call up from AAA right now?", mode: "callup" },
      { text: "Show me the top 10 MLB hitters by xwOBA in 2029." },
      { text: "Build a Metabase card of bWAR vs OPS+ scatter, 2029, 200+ PA." },
    ];
  }
  if (pathname.startsWith("/history/draft")) {
    return [
      { text: "Which 2026 draft picks have been the biggest hits?", mode: "draft" },
      { text: "Average WAR per pick by round across all classes." },
    ];
  }
  if (pathname.startsWith("/movements")) {
    return [
      { text: "Analyze a trade: I send Devers, get back two top prospects.", mode: "trade" },
      { text: "Which of my recent acquisitions are pulling weight?" },
    ];
  }
  return [
    { text: "Who's overperforming their xwOBA in MLB this year?" },
    { text: "Build a Metabase card showing my org's top WAR contributors." },
    { text: "Look up the formula for wRC+ and explain why it differs from OPS+." },
  ];
}

// ─────────────────────────────────────────────────────────────────────
// Turn renderer
// ─────────────────────────────────────────────────────────────────────

function Turn({ turn, verbose }: { turn: ChatTurn; verbose: boolean }) {
  const isUser = turn.role === "user";

  // User turns can be either a free-form text message OR tool_result
  // blocks (the route's tool loop emits user-side tool_result turns).
  // The latter renders compactly without the "user message" pill.
  const onlyToolResults =
    turn.content.length > 0 &&
    turn.content.every((b) => b.type === "tool_result");

  if (onlyToolResults) {
    // Even when verbose is off, show tool_result blocks that produced
    // a user-facing artifact (Metabase card link). Errors also stay
    // visible so the user knows when something failed silently.
    const visibleResults = turn.content.filter(
      (b) => verbose || isMetabaseCardResult(b) || b.is_error,
    );
    if (visibleResults.length === 0) return null;
    return (
      <div className="my-1.5 space-y-1.5">
        {visibleResults.map((b, i) => (
          <ToolResultBlock key={i} block={b} />
        ))}
      </div>
    );
  }

  // Filter assistant-side blocks: text always shown, tool_use only in
  // verbose mode. If everything got filtered, hide the turn entirely.
  const visibleBlocks = turn.content.filter((b) => {
    if (b.type === "text") return true;
    if (b.type === "tool_use") return verbose;
    if (b.type === "tool_result")
      return verbose || isMetabaseCardResult(b) || b.is_error;
    return false;
  });
  if (visibleBlocks.length === 0) return null;

  return (
    <div
      className={`my-2 ${isUser ? "ml-6" : "mr-6"} space-y-1.5`}
    >
      <div
        className={`text-[10px] uppercase tracking-wider ${
          isUser ? "text-right text-content-muted" : "text-accent"
        }`}
      >
        {isUser ? "You" : "Diamond"}
      </div>
      {visibleBlocks.map((b, i) => {
        if (b.type === "text") return <TextBlock key={i} block={b} />;
        if (b.type === "tool_use") return <ToolUseBlock key={i} block={b} />;
        if (b.type === "tool_result")
          return <ToolResultBlock key={i} block={b} />;
        return null;
      })}
    </div>
  );
}

function isMetabaseCardResult(b: ChatContentBlock): boolean {
  // Metabase card results are useful in non-verbose mode — the green
  // "Open in Workshop" link is the actionable artifact of the chat.
  const c = b.content;
  return (
    !b.is_error &&
    !!c &&
    typeof c === "object" &&
    "card_url" in (c as Record<string, unknown>)
  );
}

function TextBlock({ block }: { block: ChatContentBlock }) {
  return (
    <div className="whitespace-pre-wrap rounded border border-border bg-surface-card px-3 py-2 text-sm text-content-primary">
      {block.text ?? ""}
    </div>
  );
}

function ToolUseBlock({ block }: { block: ChatContentBlock }) {
  const name = block.name ?? "";
  const input = block.input ?? {};
  const isCard = name === "create_metabase_card";
  return (
    <details className="rounded border border-border bg-surface-elevated px-2 py-1.5 text-xs text-content-secondary">
      <summary className="cursor-pointer">
        <span className="font-mono text-accent">{name}</span>
        {isCard && (
          <span className="ml-2 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-accent">
            Tier 4
          </span>
        )}
      </summary>
      <pre className="mt-2 overflow-x-auto text-[11px]">
        {JSON.stringify(input, null, 2)}
      </pre>
    </details>
  );
}

function ToolResultBlock({ block }: { block: ChatContentBlock }) {
  const content = block.content;
  const isError = !!block.is_error;

  // Special: Metabase card created — render a launcher link inline.
  if (
    !isError &&
    content &&
    typeof content === "object" &&
    "card_url" in content
  ) {
    const c = content as Record<string, unknown>;
    const url = String(c.card_url ?? "");
    const cardName = String(c.name ?? "Card");
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block rounded border border-emerald-700 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-200 transition hover:border-emerald-500"
      >
        <div className="font-medium text-emerald-100">
          ✓ Created Metabase card: {cardName}
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-emerald-300/80">
          {url} ↗
        </div>
      </a>
    );
  }

  // Compact preview of warehouse query results
  if (
    !isError &&
    content &&
    typeof content === "object" &&
    "rows" in content
  ) {
    const c = content as Record<string, unknown>;
    const cols = (c.columns as string[]) ?? [];
    const rows = (c.rows as Record<string, unknown>[]) ?? [];
    const sql = String(c.sql ?? "");
    return (
      <details className="rounded border border-border bg-surface-elevated px-2 py-1.5 text-xs">
        <summary className="cursor-pointer text-content-secondary">
          <span className="text-emerald-400">✓</span> {rows.length} row
          {rows.length === 1 ? "" : "s"} from warehouse
        </summary>
        <div className="mt-2 space-y-2">
          <pre className="overflow-x-auto rounded bg-surface-page px-2 py-1 text-[10px] text-content-muted">
            {sql}
          </pre>
          {rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="text-[10px]">
                <thead>
                  <tr className="border-b border-border text-content-muted">
                    {cols.map((c) => (
                      <th key={c} className="px-1.5 py-0.5 text-left">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 25).map((r, i) => (
                    <tr key={i} className="border-b border-border/40">
                      {cols.map((c) => (
                        <td
                          key={c}
                          className="whitespace-nowrap px-1.5 py-0.5 text-content-primary"
                        >
                          {String(r[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > 25 && (
                <div className="mt-1 text-content-muted">
                  + {rows.length - 25} more rows…
                </div>
              )}
            </div>
          )}
        </div>
      </details>
    );
  }

  // Error or generic JSON
  return (
    <details
      className={`rounded border px-2 py-1.5 text-xs ${
        isError
          ? "border-rose-700 bg-rose-950/30 text-rose-200"
          : "border-border bg-surface-elevated text-content-secondary"
      }`}
    >
      <summary className="cursor-pointer">
        {isError ? "✗ Tool error" : "↩ Tool result"}
      </summary>
      <pre className="mt-2 overflow-x-auto text-[11px]">
        {typeof content === "string"
          ? content
          : JSON.stringify(content, null, 2)}
      </pre>
    </details>
  );
}
