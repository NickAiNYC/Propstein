import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone output is for self-hosted runs only (Docker / sandbox prod
  // tests: `bun run build:standalone` then `bun start`). On Vercel it strips
  // the default build output and every route 404s — the VERCEL env var is
  // present in all Vercel builds (preview and production alike).
  output: process.env.VERCEL ? undefined : "standalone",
  /* config options here */
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
};

export default nextConfig;
