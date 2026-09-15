import type { Session } from '@/lib/api/types'

/**
 * Session cookie shaping. The browser never holds a Supabase token in
 * JavaScript: both halves of the session live in httpOnly cookies that only the
 * route handlers and `proxy.ts` can read.
 */

export const ACCESS_COOKIE = 'peritus_access_token'
export const REFRESH_COOKIE = 'peritus_refresh_token'
export const PKCE_COOKIE = 'peritus_pkce_verifier'
export const LOGIN_NEXT_COOKIE = 'peritus_login_next'

/** Refresh tokens are long-lived; Supabase's default is 30 days. */
const REFRESH_MAX_AGE = 60 * 60 * 24 * 30

/**
 * Expire the access cookie a minute before the token itself, so a request that
 * leaves the browser just as the cookie expires never arrives with a token the
 * API has already started rejecting. The floor keeps a pathologically short
 * `expires_in` from producing a cookie that is already dead.
 */
const EXPIRY_MARGIN_SECONDS = 60
const MIN_ACCESS_MAX_AGE = 30

export interface CookieSpec {
  name: string
  value: string
  httpOnly: boolean
  secure: boolean
  sameSite: 'lax' | 'strict' | 'none'
  path: string
  maxAge: number
}

/**
 * Whether the session cookies carry `Secure`.
 *
 * On in production, which is the only thing that matters for a deployment. The
 * escape hatch exists for one reason: an end-to-end run drives a production
 * build over plain `http://127.0.0.1`, and **WebKit refuses a `Secure` cookie
 * over http even on loopback** (Chromium special-cases localhost; Safari does
 * not). Without it the whole sign-in path is untestable on the two WebKit
 * projects, which are the ones that catch iOS bugs.
 *
 * It is opt-in and has to be set deliberately — `playwright.config.ts` is the
 * only place that does. `NODE_ENV` alone stays the default, so forgetting to
 * set anything is the safe outcome.
 */
export function isProduction(): boolean {
  // Bracket access on purpose: Next replaces a statically written
  // `process.env.FOO` with its build-time value, so a dotted read here would
  // bake in whatever the variable was when `next build` ran (undefined) and
  // ignore it at runtime. The lookup has to be dynamic to be read per process.
  if (process.env['PERITUS_ALLOW_INSECURE_COOKIES'] === 'true') return false
  return process.env.NODE_ENV === 'production'
}

export function accessCookieMaxAge(expiresIn: number): number {
  return Math.max(MIN_ACCESS_MAX_AGE, Math.floor(expiresIn) - EXPIRY_MARGIN_SECONDS)
}

function base(name: string, value: string, maxAge: number): CookieSpec {
  return {
    name,
    value,
    httpOnly: true,
    secure: isProduction(),
    // Lax, not Strict: the Google OAuth callback is a cross-site top-level
    // navigation back into the app, and Strict would drop the cookies on it.
    // Mutating handlers carry an Origin / Sec-Fetch-Site check on top.
    sameSite: 'lax',
    path: '/',
    maxAge,
  }
}

/** The pair of cookies that carry a freshly minted session. */
export function sessionCookies(session: Session): CookieSpec[] {
  return [
    base(ACCESS_COOKIE, session.access_token, accessCookieMaxAge(session.expires_in)),
    base(REFRESH_COOKIE, session.refresh_token, REFRESH_MAX_AGE),
  ]
}

/** maxAge 0 deletes. Both halves go, always — a half-cleared session is worse
 *  than none, because `proxy.ts` would then try to refresh a dead token. */
export function clearedSessionCookies(): CookieSpec[] {
  return [base(ACCESS_COOKIE, '', 0), base(REFRESH_COOKIE, '', 0)]
}

/** The PKCE verifier and the post-login destination, both short-lived. */
export function pkceCookies(verifier: string, next: string): CookieSpec[] {
  return [
    base(PKCE_COOKIE, verifier, 600),
    base(LOGIN_NEXT_COOKIE, next, 600),
  ]
}

export function clearedPkceCookies(): CookieSpec[] {
  return [base(PKCE_COOKIE, '', 0), base(LOGIN_NEXT_COOKIE, '', 0)]
}
