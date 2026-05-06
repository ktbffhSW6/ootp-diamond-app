// One-click "Quit" — kills both dev servers via the admin endpoint.
//
// Lives in the layout header so it's reachable from every page. Single
// click triggers the kill; the button swaps to a "Stopped" message
// once the API has acknowledged. We don't try to close the tab —
// `window.close()` only works for tabs JavaScript opened, and a
// manually-navigated tab will refuse the call. The user closes the
// tab; the dev servers are gone.

"use client";

import { useState } from "react";

import { shutdownApp } from "@/lib/api";

type QuitState = "idle" | "stopping" | "stopped" | "error";

export function QuitButton() {
  const [state, setState] = useState<QuitState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleClick() {
    setState("stopping");
    setErrorMsg(null);
    try {
      await shutdownApp();
      // Give the detached subprocess its 1s pause + a small buffer
      // before swapping the label. If the API died fast (uvicorn
      // graceful shutdown) the fetch above would still resolve since
      // the response was sent before the kill.
      setTimeout(() => setState("stopped"), 1500);
    } catch (err) {
      // If the API was already down (e.g., user clicks twice) the
      // fetch throws — treat that as already-stopped rather than a
      // hard error.
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.toLowerCase().includes("failed to fetch")) {
        setState("stopped");
        return;
      }
      setState("error");
      setErrorMsg(msg);
    }
  }

  if (state === "stopped") {
    return (
      <span className="text-xs text-slate-500">
        Stopped — close this tab.
      </span>
    );
  }
  if (state === "error") {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-rose-600">
          Shutdown failed: {errorMsg ?? "unknown"}
        </span>
        <button
          onClick={() => {
            setState("idle");
            setErrorMsg(null);
          }}
          className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
        >
          Reset
        </button>
      </div>
    );
  }
  return (
    <button
      onClick={handleClick}
      disabled={state === "stopping"}
      className="rounded border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-50"
      title="Stop both dev servers (Next.js :3000 + FastAPI :8000)"
    >
      {state === "stopping" ? "Stopping…" : "Quit"}
    </button>
  );
}
