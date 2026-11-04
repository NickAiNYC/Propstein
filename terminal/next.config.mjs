/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  serverExternalPackages: ["pg"],
  typescript: {
    ignoreBuildErrors: true,
  },
};

export default nextConfig;
