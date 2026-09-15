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
  experimental: {
    // The stylesheet is render-blocking, and React only reveals a streamed
    // Suspense boundary 300ms after the first paint (`$RT + 300` in the inline
    // `$RC` runtime) — so on a slow connection a page whose data arrived with
    // the HTML still showed its `loading.tsx` skeleton until the CSS request
    // finished. Inlined, it arrives with the document. Measured with the
    // Lighthouse config (devtools throttling, median of 3): the seeded chat
    // 2.19s → 1.54s LCP, /experts 2.20s → 1.51s, / and /login 1.65s → 0.80s.
    // The cost is ~14KB of Tailwind re-sent on every full page load; client
    // navigations are unaffected.
    inlineCss: true,
  },
  async headers() {
    return [
      { source: '/:path*', headers: securityHeaders },
      // A share link's token is its access. It must not leak to a site linked
      // from the page through `Referer`, and the page must never be indexed.
      // Later entries win for the same header, so this overrides the default
      // referrer policy above for these paths only.
      {
        source: '/share/:path*',
        headers: [
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
        ],
      },
      {
        source: '/api/share/:path*',
        headers: [
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
        ],
      },
    ]
  },
}

export default nextConfig
