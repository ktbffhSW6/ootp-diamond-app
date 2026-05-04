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
};

export default nextConfig;
