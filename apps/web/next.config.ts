import type { NextConfig } from "next";

const API = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";
const PROD = process.env.NODE_ENV === "production";

// Production only (`next dev` needs eval for Fast Refresh). Next's App Router inlines its bootstrap scripts, so
// script-src keeps 'unsafe-inline' until nonce-based CSP is wired through middleware; external scripts are blocked.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Lets a second dev server (e.g. an isolated test instance) run without sharing .next with the first.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  // No next/image in the app: keep the sharp-based optimizer (and its native image decoders) out of the attack surface.
  images: { unoptimized: true },
  // Browser calls stay same-origin (/api/*), so session cookies are first-party and CORS is not needed in the browser.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          ...(PROD ? [{ key: "Content-Security-Policy", value: CSP }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
