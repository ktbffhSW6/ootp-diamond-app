// Next.js config — keep minimal until we hit a real reason to expand it.
//
// API URL: rather than hardcode `http://localhost:8000` everywhere, we
// expose `NEXT_PUBLIC_API_URL` (defaulting to `http://localhost:8000`)
// and read it from `web/lib/api.ts`. In production deploy (Phase 4+),
// the env var changes; the code doesn't.

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Per D16: Diamond is local-first, no SSR-on-Vercel trick needed yet.
  // Leaving server-component fetches as the data path — they hit the
  // FastAPI backend over localhost during dev.
  //
  // D32 (desktop shell): `output: 'standalone'` produces a self-contained
  // server tree at .next/standalone/{server.js, .next/, node_modules/}
  // that the desktop launcher spawns via `node server.js`. The standalone
  // tree only includes runtime deps, so the bundle stays small (~40MB
  // vs ~300MB of dev node_modules). Static assets (.next/static + public/)
  // are NOT auto-copied — `scripts/build_desktop.py` handles that step.
  output: "standalone",
  //
  // 2026-05-13 IA shuffle: /explore is now JUST the Chart Builder.
  // Per-player charts (spray, EV/LA) live inline on the player page;
  // league-wide tools (leaderboards, compare) moved under /league.
  // Permanent redirects so any external links / browser history /
  // copy-pasted deep-links keep working.
  async redirects() {
    return [
      // Per-player charts moved to inline sections on /player/[id].
      // Old `?player=ID` deep-links collapse to the player page; without
      // a player param we can't do anything useful, so land on /league
      // (where the Compare card surfaces three demo player IDs).
      {
        source: "/explore/spray",
        has: [{ type: "query", key: "player", value: "(?<id>\\d+)" }],
        destination: "/player/:id",
        permanent: true,
      },
      {
        source: "/explore/ev-la",
        has: [{ type: "query", key: "player", value: "(?<id>\\d+)" }],
        destination: "/player/:id",
        permanent: true,
      },
      { source: "/explore/spray", destination: "/league", permanent: true },
      { source: "/explore/ev-la", destination: "/league", permanent: true },

      // League-wide tools moved to /league/*.
      {
        source: "/explore/leaderboards",
        destination: "/league/leaderboards",
        permanent: true,
      },
      {
        source: "/explore/compare",
        destination: "/league/compare",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
