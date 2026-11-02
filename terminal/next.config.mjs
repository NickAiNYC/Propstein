/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The operator terminal is served from this workspace only. The static
  // viewer deployment (root vercel.json, outputDirectory: viewer) and the
  // frozen paid-tier scaffold (root app/) are deliberately untouched by it.
};

export default nextConfig;
