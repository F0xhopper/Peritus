import type { NextConfig } from 'next'

// Applied to every response. `X-Frame-Options: DENY` plus the CSP-less defaults
// are deliberate: the app renders no third-party frames and is never framed.
// HSTS is emitted unconditionally — browsers ignore it over plain http, so it
// costs nothing in development and is never forgotten in production.
const securityHeaders = [
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-DNS-Prefetch-Control', value: 'on' },
]

const nextConfig: NextConfig = {
  // `cacheComponents` and `partialPrefetching` stay off: every page in the app
  // shell is dynamic per user and would gain nothing from either.
  // `turbopackFileSystemCache*` are on by default in 16.3 — left alone.
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }]
  },
}

export default nextConfig
