import type { NextConfig } from "next";

// The Django API. In development it runs on :8000; in production set BACKEND_URL.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Browser calls go to same-origin /api/*, proxied to Django (no CORS needed).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  // The floating dev badge sits over the sidebar's route cards.
  devIndicators: false,
  experimental: {
    // Planning can take a while when the public routing server is slow.
    proxyTimeout: 90_000,
  },
};

export default nextConfig;
