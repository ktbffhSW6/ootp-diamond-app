// Measure a DOM element's width and re-render whenever it changes.
//
// Used by Plot charts that need to fill their container instead of
// hardcoding a pixel width. Backed by ResizeObserver (supported in
// every modern browser; we don't ship to anything older). Returns a
// ref to attach to the container + the latest measured width.
//
// Usage:
//
//   const { ref, width } = useElementWidth(800);
//   useEffect(() => {
//     const chart = Plot.plot({ width, height: 480, marks: [...] });
//     ref.current?.replaceChildren(chart);
//     return () => chart.remove();
//   }, [width, /* other deps */]);
//
//   <div ref={ref} />
//
// The default-width arg matters: it's the value used during SSR and
// before the first observer callback fires. Set it to whatever looks
// reasonable on a typical desktop so the first paint isn't tiny.

import { useEffect, useRef, useState } from "react";

export function useElementWidth<T extends HTMLElement = HTMLDivElement>(
  initialWidth = 800,
): { ref: React.RefObject<T | null>; width: number } {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(initialWidth);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Set the initial width from the element synchronously so the
    // first chart render uses the real container size rather than
    // the SSR fallback. ResizeObserver delivers asynchronously, so
    // without this we'd flash the default-width chart for one frame.
    const initial = Math.floor(el.getBoundingClientRect().width);
    if (initial > 0 && initial !== initialWidth) {
      setWidth(initial);
    }
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.floor(entry.contentRect.width);
        // Avoid update churn from sub-pixel resizes; only re-render
        // when the integer width actually changes.
        if (w > 0) {
          setWidth((current) => (current === w ? current : w));
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
    // initialWidth intentionally omitted — it's only the SSR default,
    // not a runtime input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ref, width };
}
