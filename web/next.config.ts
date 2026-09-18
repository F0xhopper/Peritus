import type { NextConfig } from 'next'

/**
 * The content security policy, **in report-only mode**.
 *
 * Report-only on purpose, and this is the step before enforcing rather than a
 * softer version of it: a CSP that blocks something the app needs takes the
 * page down with no error anyone reads, so it runs for a while first and the
 * browser console says what it *would* have blocked. Promote it to
 * `Content-Security-Policy` once that console is quiet.
 *
 * Two directives are looser than they look, and both have a specific reason:
 *
 * - **`script-src 'unsafe-inline'`.** React's streaming runtime writes inline
 *   `<script>` tags to reveal each Suspense boundary as its data arrives.
 *   Tightening this means a per-request nonce, which means computing the header
 *   in `proxy.ts` — worth doing, but at enforcement time, not now, because a
 *   nonce that misses one script is exactly the silent breakage above.
 * - **`style-src 'unsafe-inline'`.** `experimental.inlineCss` puts the
 *   stylesheet in the document, which is what removed 0.6–0.9s of LCP.
 *
 * Everything else is as tight as the app actually needs. There are no
 * third-party scripts, no third-party fonts at runtime (`next/font` self-hosts
 * Inter at build time), and every network call goes to this origin — the API is
 * reached through `/api/*`, never from the browser directly.
 */
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  // `data:` and `blob:` for the generated avatars and anything the image
  // optimiser produces; expert pictures are served from this origin. Google's
  // image host for the signed-in person's own profile picture, which is the one
  // image loaded from elsewhere.
  "img-src 'self' data: blob: https://*.googleusercontent.com",
  "font-src 'self'",
  "connect-src 'self'",
  // The modern spelling of `X-Frame-Options: DENY`, which is kept below for
  // browsers that do not implement this one.
  "frame-ancestors 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  // Nothing may rewrite where relative URLs resolve, and a form may only post
  // to this origin — which between them close off most injected-markup tricks.
  "base-uri 'none'",
  "form-action 'self'",
].join('; ')

// Applied to every response. HSTS is emitted unconditionally — browsers ignore
// it over plain http, so it costs nothing in development and is never
// forgotten in production.
const securityHeaders = [
  { key: 'Content-Security-Policy-Report-Only', value: contentSecurityPolicy },
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
