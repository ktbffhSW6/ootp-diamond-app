"use client";

// Diamond AI sidebar (D33 → D35).
//
// A floating right-side panel reachable from every page via a launcher
// button in the top header. Powers tiers 1-4:
//
//   T1 (page-aware): the sidebar reads usePathname() and posts
//       `page_context.pathname` with every request. The system prompt
//       tells the model "the user is on /player/123 — they're asking
//       about that player unless they say otherwise."
//   T2 (analyst): backend exposes 8 tools (query_warehouse, get_player,
//       compare_players, get_glossary, list_leaderboard_stats,
//       create_metabase_card, describe_table, get_career_arc). The
//       model loops; we render each tool_use / tool_result block
//       inline so the user can see the work.
//   T3 (GM copilot): four mode pills (Chat / Call-up / Trade / Draft).
//       Non-default modes prepend a structured prompt template.
//   T4 (prompt-to-dashboard): create_metabase_card tool POSTs to
//       Metabase's REST API and returns the card URL; we render a
//       "Open in Workshop" link inline.
//
// D35 (this rev) — Claude.ai-style polish:
//   - Markdown rendering for assistant text (GFM tables, headings,
//     lists, inline + block code) via MarkdownMessage.
//   - Consecutive assistant turns coalesce into one labeled response
//     group, so a tool-using loop doesn't stack three "DIAMOND"
//     headers down the panel.
//   - User vs assistant asymmetry — user as a right-aligned pill,
//     assistant as flat full-width prose.
//   - SSE streaming via streamChat() — text deltas paint character
//     by character with an animated cursor.
//   - Header carries mode pills + Tools toggle + New + Close.
//   - Panel is resizable via a drag handle on the left edge.
//   - Copy button on each assistant response (hover-revealed).
//   - "Jump to latest" button when scrolled away from bottom.

import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  ChatContentBlock,
  ChatRequest,
  ChatTurn,
} from "@/lib/types/api";
import { streamChat, type StreamEvent } from "@/lib/ai-chat";
import { MarkdownMessage } from "@/components/ai/MarkdownMessage";
import { usePagePayload } from "@/components/PagePayloadProvider";

type Mode = "chat" | "callup" | "trade" | "draft";

const MODE_LABELS: Record<Mode, { label: string; hint: string }> = {
  chat: { label: "Chat", hint: "Open-ended" },
  callup: { label: "Call-up", hint: "Roster move" },
  trade: { label: "Trade", hint: "Evaluate idea" },
  draft: { label: "Draft", hint: "Class review" },
};

const VERBOSE_KEY = "diamond.ai.verbose";
const WIDTH_KEY = "diamond.ai.width";
const DEFAULT_WIDTH = 520;
const MIN_WIDTH = 380;
const MAX_WIDTH = 900;

// ────────────────────────────────────────────────────────────────────
// Top-level component
// ────────────────────────────────────────────────────────────────────

export function AISidebar() {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState<ChatTurn[]>([]);
  // While streaming, deltas accumulate into `streaming` and render
  // beneath the committed thread; on completion we append the
  // finished turns to `thread` and clear `streaming`.
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<Mode>("chat");
  const [error, setError] = useState<string | null>(null);
  const [verbose, setVerbose] = useState(false);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const pathname = usePathname();
  const pagePayload = usePagePayload();
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  // Restore prefs from localStorage on mount.
  useEffect(() => {
    try {
      setVerbose(localStorage.getItem(VERBOSE_KEY) === "1");
      const w = Number(localStorage.getItem(WIDTH_KEY));
      if (Number.isFinite(w) && w >= MIN_WIDTH && w <= MAX_WIDTH) {
        setWidth(w);
      }
    } catch {
      // ignore
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

  // Auto-scroll to bottom while streaming or when committed thread grows,
  // unless the user has scrolled up.
  useEffect(() => {
    if (atBottom) {
      threadEndRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [thread, streaming, atBottom]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(dist < 60);
  }, []);

  const send = useCallback(
    async (text: string, modeOverride?: Mode) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;
      setError(null);

      const userTurn: ChatTurn = {
        role: "user",
        content: [{ type: "text", text: trimmed }],
      };
      const optimistic = [...thread, userTurn];
      setThread(optimistic);
      setInput("");
      setAtBottom(true);

      // Initialize streaming state with one fresh assistant turn.
      const state: StreamingState = {
        turns: [{ role: "assistant", content: [] }],
      };
      setStreaming(state);

      const req: ChatRequest = {
        messages: thread,
        user_input: trimmed,
        page_context: {
          pathname: pathname ?? "/",
          payload: pagePayload ?? undefined,
        },
        mode: modeOverride ?? mode,
      };

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        await streamChat(req, {
          signal: ctrl.signal,
          onEvent: (ev) => {
            // Mutate the current streaming state in place (then clone
            // for setState so React sees a new reference).
            applyEvent(state, ev);
            setStreaming({ turns: cloneTurns(state.turns) });
          },
        });
        // Drain into the committed thread.
        const finalTurns = state.turns.filter(
          (t) => t.content.length > 0,
        );
        setThread([...optimistic, ...finalTurns]);
        setStreaming(null);
      } catch (e) {
        if ((e as Error)?.name === "AbortError") {
          // User cancelled — drain whatever streamed so far.
          const finalTurns = state.turns.filter(
            (t) => t.content.length > 0,
          );
          setThread([...optimistic, ...finalTurns]);
          setStreaming(null);
        } else {
          setError(e instanceof Error ? e.message : String(e));
          setThread(thread); // roll back the optimistic user turn
          setStreaming(null);
          setInput(trimmed);
        }
      } finally {
        abortRef.current = null;
      }
    },
    [thread, mode, pathname, streaming, pagePayload],
  );

  const stop = () => {
    abortRef.current?.abort();
  };

  const reset = () => {
    if (streaming) return;
    setThread([]);
    setInput("");
    setError(null);
    setMode("chat");
  };

  // Coalesce thread + in-flight streaming into "response groups": each
  // group is either one user message OR a contiguous run of
  // assistant + tool-result turns rendered under a single Diamond label.
  const groups = useMemo(
    () => groupTurns([...thread, ...(streaming?.turns ?? [])]),
    [thread, streaming],
  );

  // Drag-resize handle ─────────────────────────────────────────────
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  const onDragStart = (e: React.PointerEvent) => {
    dragRef.current = { startX: e.clientX, startW: width };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onDragMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = dragRef.current.startX - e.clientX; // dragging left grows
    const next = Math.max(
      MIN_WIDTH,
      Math.min(MAX_WIDTH, dragRef.current.startW + dx),
    );
    setWidth(next);
  };
  const onDragEnd = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    try {
      localStorage.setItem(WIDTH_KEY, String(width));
    } catch {
      // ignore
    }
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
  };

  return (
    <>
      {/* Floating launcher — bottom-right, always visible when closed */}
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
        style={{ width }}
        className={`fixed inset-y-0 right-0 z-40 flex max-w-[95vw] flex-col border-l border-border bg-surface-page shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!open}
      >
        {/* Drag handle */}
        <div
          onPointerDown={onDragStart}
          onPointerMove={onDragMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
          className="absolute inset-y-0 -left-1 z-50 w-2 cursor-col-resize select-none"
          title="Drag to resize"
          aria-label="Resize panel"
        />

        {/* Header — chrome, modes, tools toggle, new, close */}
        <header className="border-b border-border">
          <div className="flex items-center justify-between gap-2 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="text-accent">✦</span>
              <div>
                <div className="text-sm font-semibold text-content-primary">
                  Diamond AI
                </div>
                <div className="font-mono text-[10px] leading-tight text-content-muted">
                  {pathname ?? "/"}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
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
                Tools
              </button>
              <button
                type="button"
                onClick={reset}
                disabled={!!streaming}
                className="rounded border border-border px-2 py-1 text-xs text-content-secondary transition hover:bg-surface-card disabled:opacity-40"
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
          </div>
          {/* Mode pills (Tier 3) — moved into header in D35 Tier D */}
          <div className="flex gap-1 px-3 pb-2">
            {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                disabled={!!streaming}
                className={`flex-1 rounded border px-2 py-1 text-[11px] transition disabled:opacity-40 ${
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
        </header>

        {/* Thread */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto px-4 py-3"
        >
          {thread.length === 0 && !streaming && (
            <EmptyState onPrompt={(t, m) => send(t, m)} />
          )}
          {groups.map((g, i) => (
            <Group
              key={i}
              group={g}
              verbose={verbose}
              streaming={!!streaming && i === groups.length - 1 && g.role === "assistant"}
            />
          ))}
          {error && (
            <div className="my-2 rounded border border-rose-700 bg-rose-950/40 p-2 text-xs text-rose-200">
              {error}
            </div>
          )}
          <div ref={threadEndRef} />

          {/* Jump-to-latest button */}
          {!atBottom && (
            <button
              type="button"
              onClick={() => {
                threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
                setAtBottom(true);
              }}
              className="sticky bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-full border border-border bg-surface-card px-3 py-1 text-[11px] text-content-secondary shadow hover:bg-surface-elevated"
            >
              ↓ Jump to latest
            </button>
          )}
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
            disabled={!!streaming}
            className="flex-1 resize-none rounded border border-border bg-surface-card px-2.5 py-2 text-[14px] text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
          />
          {streaming ? (
            <button
              type="button"
              onClick={stop}
              className="rounded border border-border bg-surface-card px-3 py-2 text-sm font-medium text-content-secondary transition hover:bg-surface-elevated"
              title="Stop generating"
            >
              ◼ Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="rounded bg-accent px-3 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </form>
      </aside>
    </>
  );
}

// ────────────────────────────────────────────────────────────────────
// Streaming state machine
// ────────────────────────────────────────────────────────────────────

interface StreamingState {
  // Sequence of in-flight turns. The tool loop alternates:
  //   assistant → user(tool_results) → assistant → ...
  // We always have at least one trailing assistant turn ready to
  // accept text_delta / tool_use events.
  turns: ChatTurn[];
}

function applyEvent(state: StreamingState, ev: StreamEvent): void {
  if (ev.type === "iteration") {
    // Iteration boundary: ensure the trailing turn is a fresh
    // assistant. The first iteration's assistant was created when
    // the user submitted; subsequent iterations start a new one.
    const last = state.turns[state.turns.length - 1];
    if (!last || last.role !== "assistant" || last.content.length > 0) {
      state.turns.push({ role: "assistant", content: [] });
    }
    return;
  }

  if (ev.type === "text_delta") {
    const turn = ensureTrailingAssistant(state);
    const last = turn.content[turn.content.length - 1];
    if (last && last.type === "text") {
      last.text = (last.text ?? "") + ev.text;
    } else {
      turn.content.push({ type: "text", text: ev.text });
    }
    return;
  }

  if (ev.type === "tool_use") {
    const turn = ensureTrailingAssistant(state);
    turn.content.push({
      type: "tool_use",
      id: ev.id,
      name: ev.name,
      input: ev.input,
    });
    return;
  }

  if (ev.type === "tool_result") {
    // Append a user turn (per Anthropic protocol) carrying the result.
    const last = state.turns[state.turns.length - 1];
    if (last && last.role === "user") {
      last.content.push({
        type: "tool_result",
        tool_use_id: ev.tool_use_id,
        content: ev.content,
        is_error: ev.is_error,
      });
    } else {
      state.turns.push({
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: ev.tool_use_id,
            content: ev.content,
            is_error: ev.is_error,
          },
        ],
      });
    }
    return;
  }

  if (ev.type === "error") {
    const turn = ensureTrailingAssistant(state);
    turn.content.push({ type: "text", text: `\n\n⚠ ${ev.detail}` });
    return;
  }
  // 'done' — no state change; the caller will close out streaming.
}

function ensureTrailingAssistant(state: StreamingState): ChatTurn {
  const last = state.turns[state.turns.length - 1];
  if (last && last.role === "assistant") return last;
  const fresh: ChatTurn = { role: "assistant", content: [] };
  state.turns.push(fresh);
  return fresh;
}

function cloneTurns(turns: ChatTurn[]): ChatTurn[] {
  return turns.map((t) => ({
    role: t.role,
    content: t.content.map((b) => ({ ...b })),
  }));
}

// ────────────────────────────────────────────────────────────────────
// Coalescing: turns → response groups
// ────────────────────────────────────────────────────────────────────

interface ResponseGroup {
  role: "user" | "assistant";
  // For assistant groups, all turns + tool_result turns interleaved.
  // For user groups, exactly one turn.
  turns: ChatTurn[];
}

function groupTurns(turns: ChatTurn[]): ResponseGroup[] {
  const out: ResponseGroup[] = [];
  for (const t of turns) {
    const isUserText =
      t.role === "user" &&
      t.content.some((b) => b.type === "text");
    if (isUserText) {
      out.push({ role: "user", turns: [t] });
      continue;
    }
    // Assistant turn or tool-result-only user turn — merge into the
    // trailing assistant group, or start a new one.
    const last = out[out.length - 1];
    if (last && last.role === "assistant") {
      last.turns.push(t);
    } else {
      out.push({ role: "assistant", turns: [t] });
    }
  }
  return out;
}

// ────────────────────────────────────────────────────────────────────
// Group renderer
// ────────────────────────────────────────────────────────────────────

function Group({
  group,
  verbose,
  streaming,
}: {
  group: ResponseGroup;
  verbose: boolean;
  streaming: boolean;
}) {
  if (group.role === "user") {
    const turn = group.turns[0];
    const text = turn.content
      .filter((b) => b.type === "text")
      .map((b) => b.text ?? "")
      .join("\n");
    return (
      <div className="my-3 flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-surface-card px-3.5 py-2 text-[14px] text-content-primary">
          {text}
        </div>
      </div>
    );
  }

  // Assistant group — flat full-width prose with one Diamond label
  // and a hover-revealed copy button at the end.
  const blocks = group.turns.flatMap((t) =>
    t.content.map((b) => ({ role: t.role, block: b })),
  );

  // Filter visible blocks per verbose preference.
  const visible = blocks.filter(({ block }) => {
    if (block.type === "text") return true;
    if (block.type === "tool_use") return verbose;
    if (block.type === "tool_result")
      return verbose || isMetabaseCardResult(block) || block.is_error;
    return false;
  });
  if (visible.length === 0 && !streaming) return null;

  // Concatenated assistant text (for the copy button).
  const fullText = blocks
    .filter(({ block }) => block.type === "text")
    .map(({ block }) => block.text ?? "")
    .join("\n\n")
    .trim();

  return (
    <article className="group my-4">
      <header className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-accent">
        <span aria-hidden="true">✦</span>
        <span>Diamond</span>
      </header>
      <div className="space-y-2">
        {visible.map(({ block }, i) => {
          if (block.type === "text") {
            const isLastText =
              i ===
              visible
                .map((v, j) => (v.block.type === "text" ? j : -1))
                .filter((j) => j !== -1)
                .pop();
            return (
              <TextBlock
                key={i}
                block={block}
                streaming={streaming && isLastText}
              />
            );
          }
          if (block.type === "tool_use")
            return <ToolUseBlock key={i} block={block} />;
          if (block.type === "tool_result")
            return <ToolResultBlock key={i} block={block} />;
          return null;
        })}
        {streaming && visible.every((v) => v.block.type !== "text") && (
          <div className="flex items-center gap-1.5 text-xs text-content-muted">
            <BlinkingCursor />
            <span>Thinking…</span>
          </div>
        )}
      </div>
      {!streaming && fullText && (
        <div className="mt-2 flex justify-start opacity-0 transition-opacity group-hover:opacity-100">
          <CopyButton text={fullText} />
        </div>
      )}
    </article>
  );
}

function isMetabaseCardResult(b: ChatContentBlock): boolean {
  const c = b.content;
  return (
    !b.is_error &&
    !!c &&
    typeof c === "object" &&
    "card_url" in (c as Record<string, unknown>)
  );
}

// ────────────────────────────────────────────────────────────────────
// Block-level renderers
// ────────────────────────────────────────────────────────────────────

function TextBlock({
  block,
  streaming,
}: {
  block: ChatContentBlock;
  streaming: boolean;
}) {
  const text = block.text ?? "";
  return (
    <div>
      <MarkdownMessage text={text} />
      {streaming && <BlinkingCursor inline />}
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

  // Special: Metabase card created.
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
                    {cols.map((cn) => (
                      <th key={cn} className="px-1.5 py-0.5 text-left">
                        {cn}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 25).map((r, i) => (
                    <tr key={i} className="border-b border-border/40">
                      {cols.map((cn) => (
                        <td
                          key={cn}
                          className="whitespace-nowrap px-1.5 py-0.5 text-content-primary"
                        >
                          {String(r[cn] ?? "")}
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

// ────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────

function BlinkingCursor({ inline = false }: { inline?: boolean }) {
  return (
    <span
      className={`${inline ? "ml-0.5 inline-block" : "inline-block"} h-3.5 w-1.5 translate-y-[2px] animate-pulse bg-accent align-middle`}
      aria-hidden="true"
    />
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded border border-border bg-surface-card px-2 py-0.5 text-[10px] text-content-secondary transition hover:bg-surface-elevated"
      title="Copy response"
    >
      {copied ? "✓ Copied" : "Copy"}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────
// Empty state
// ────────────────────────────────────────────────────────────────────

function EmptyState({
  onPrompt,
}: {
  onPrompt: (text: string, mode?: Mode) => void;
}) {
  const pathname = usePathname() ?? "/";
  const suggestions = pickSuggestions(pathname);
  return (
    <div className="space-y-3 px-1 py-2 text-sm text-content-secondary">
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
