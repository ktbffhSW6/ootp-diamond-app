"use client";

// Page payload bridge for the AI sidebar (D33 follow-up).
//
// Each data-fetching page can publish its data to this client-side
// context; the AISidebar reads it and includes it in
// `page_context.payload` on every chat request, so the model sees
// what the user sees.
//
// Pattern:
//   1. Page (server component) fetches its data.
//   2. Wraps children in <PagePayloadBridge data={...} />.
//   3. The bridge calls setPagePayload() on mount + whenever data
//      changes.
//   4. AISidebar consumes via usePagePayload().
//
// Why a Context (vs sessionStorage / window globals): React Context
// is the idiomatic React way, plays nicely with strict mode, and
// limits the data lifetime to the current page mount (clears on
// navigation, no stale data leaking between pages).
//
// Cap on payload size: 16KB serialized. Larger payloads get
// truncated with a marker so we don't blow out the model's context
// window or pay surprise tokens. The model can always call tools
// (query_warehouse, get_player) for finer-grained data.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Payload = Record<string, unknown> | null;

interface Ctx {
  payload: Payload;
  setPayload: (p: Payload) => void;
}

const PagePayloadCtx = createContext<Ctx>({
  payload: null,
  setPayload: () => {},
});

export function PagePayloadProvider({ children }: { children: ReactNode }) {
  const [payload, setPayloadState] = useState<Payload>(null);
  const setPayload = useCallback((p: Payload) => {
    setPayloadState(p ? truncatePayload(p) : null);
  }, []);
  const value = useMemo(() => ({ payload, setPayload }), [payload, setPayload]);
  return (
    <PagePayloadCtx.Provider value={value}>
      {children}
    </PagePayloadCtx.Provider>
  );
}

export function usePagePayload(): Payload {
  return useContext(PagePayloadCtx).payload;
}

/**
 * Server-component-friendly bridge: place this inside any page that
 * wants to publish its fetched data to the AI sidebar. Clears the
 * payload when this component unmounts (page navigation).
 *
 * Example:
 *   const data = await getCockpit();
 *   return (
 *     <>
 *       <PagePayloadBridge data={data} />
 *       <CockpitView data={data} />
 *     </>
 *   );
 */
export function PagePayloadBridge({ data }: { data: unknown }) {
  const { setPayload } = useContext(PagePayloadCtx);
  useEffect(() => {
    setPayload((data as Payload) ?? null);
    return () => setPayload(null);
  }, [data, setPayload]);
  return null;
}

const PAYLOAD_BYTES_CAP = 16 * 1024;

function truncatePayload(p: Record<string, unknown>): Record<string, unknown> {
  try {
    const serialized = JSON.stringify(p);
    if (serialized.length <= PAYLOAD_BYTES_CAP) return p;
    // Too big — keep top-level keys but trim arrays / nested objects
    // we know are likely the bulk. Surface the structure for the
    // model with a marker.
    return {
      _truncated: true,
      _original_size_bytes: serialized.length,
      _hint:
        "Page payload truncated to fit context window. Use tools to fetch specifics.",
      _top_level_keys: Object.keys(p),
    };
  } catch {
    return p;
  }
}
