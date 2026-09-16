import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  accessCookieMaxAge,
  clearedPkceCookies,
  clearedSessionCookies,
  pkceCookies,
  sessionCookies,
} from '@/lib/auth/cookies'
import { createVerifier, challengeFor, safeNext } from '@/lib/auth/pkce'
import type { Session } from '@/lib/api/types'

/**
 * Session cookie shaping and the PKCE helpers.
 *
 * Small surface, high consequence: an access cookie that outlives its token
 * produces a 401 on every request until it expires, and a `next` parameter that
 * is not validated is an open redirect on the login page.
 */

function session(expiresIn = 3600): Session {
  return {
    access_token: 'access-token-value',
    refresh_token: 'refresh-token-value',
    token_type: 'bearer',
    expires_in: expiresIn,
    expires_at: null,
    user: { id: 'user-1', email: 'someone@example.com' },
  }
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('accessCookieMaxAge', () => {
  it('expires a minute before the token does', () => {
    // The margin exists so a request leaving the browser as the cookie expires
    // never arrives with a token the API has already started rejecting.
    expect(accessCookieMaxAge(3600)).toBe(3540)
  })

  it('floors at 30s rather than producing an already-dead cookie', () => {
    expect(accessCookieMaxAge(45)).toBe(30)
    expect(accessCookieMaxAge(10)).toBe(30)
    expect(accessCookieMaxAge(0)).toBe(30)
  })

  it('truncates a fractional expires_in rather than rounding up', () => {
    expect(accessCookieMaxAge(3600.9)).toBe(3540)
  })
})

describe('sessionCookies', () => {
  it('sets both halves httpOnly and SameSite=Lax', () => {
    const cookies = sessionCookies(session())
    expect(cookies).toHaveLength(2)
    for (const cookie of cookies) {
      expect(cookie.httpOnly).toBe(true)
      // Lax, not Strict: the Google callback is a cross-site top-level
      // navigation and Strict would drop the cookies on it.
      expect(cookie.sameSite).toBe('lax')
      expect(cookie.path).toBe('/')
    }
  })

  it('gives the refresh cookie 30 days and the access cookie the token’s life', () => {
    const [access, refresh] = sessionCookies(session(3600))
    expect(access.name).toBe(ACCESS_COOKIE)
    expect(access.maxAge).toBe(3540)
    expect(refresh.name).toBe(REFRESH_COOKIE)
    expect(refresh.maxAge).toBe(60 * 60 * 24 * 30)
  })

  it('is not Secure in development and is in production', () => {
    vi.stubEnv('NODE_ENV', 'development')
    expect(sessionCookies(session())[0].secure).toBe(false)
    vi.stubEnv('NODE_ENV', 'production')
    expect(sessionCookies(session())[0].secure).toBe(true)
  })
})

describe('clearedSessionCookies', () => {
  it('clears both halves, never one', () => {
    // A half-cleared session is worse than none: `proxy.ts` would then try to
    // refresh a token that is already gone on every navigation.
    const cookies = clearedSessionCookies()
    expect(cookies.map((cookie) => cookie.name).sort()).toEqual(
      [ACCESS_COOKIE, REFRESH_COOKIE].sort()
    )
    for (const cookie of cookies) {
      expect(cookie.maxAge).toBe(0)
      expect(cookie.value).toBe('')
    }
  })
})

describe('pkceCookies', () => {
  it('holds the verifier for ten minutes, httpOnly', () => {
    const [verifier, next] = pkceCookies('a'.repeat(64), '/experts/abc')
    expect(verifier.maxAge).toBe(600)
    expect(verifier.httpOnly).toBe(true)
    expect(next.value).toBe('/experts/abc')
  })

  it('clears both when the flow ends', () => {
    for (const cookie of clearedPkceCookies()) expect(cookie.maxAge).toBe(0)
  })
})

describe('createVerifier', () => {
  it('produces a verifier inside RFC 7636’s length range', () => {
    // The API validates 43–128 characters on exchange, so a verifier outside
    // the range fails the whole sign-in with a 422.
    for (let i = 0; i < 20; i += 1) {
      const verifier = createVerifier()
      expect(verifier.length).toBeGreaterThanOrEqual(43)
      expect(verifier.length).toBeLessThanOrEqual(128)
      // Unreserved characters only — no padding, no + or /.
      expect(verifier).toMatch(/^[A-Za-z0-9\-_]+$/)
    }
  })

  it('is different every time', () => {
    const seen = new Set(Array.from({ length: 50 }, () => createVerifier()))
    expect(seen.size).toBe(50)
  })
})

describe('challengeFor', () => {
  it('is the base64url S256 digest, with no padding', async () => {
    // The known RFC 7636 appendix B vector.
    const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
    expect(await challengeFor(verifier)).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
  })

  it('is stable for the same verifier', async () => {
    const verifier = createVerifier()
    expect(await challengeFor(verifier)).toBe(await challengeFor(verifier))
  })
})

describe('safeNext', () => {
  it('keeps an in-app path', () => {
    expect(safeNext('/experts/abc/sources?decision=rejected')).toBe(
      '/experts/abc/sources?decision=rejected'
    )
  })

  it('refuses an absolute URL', () => {
    expect(safeNext('https://evil.example/steal')).toBe('/experts')
  })

  it('refuses a protocol-relative URL', () => {
    // `//evil.example` is a same-protocol absolute URL, and the single most
    // common open-redirect bypass.
    expect(safeNext('//evil.example')).toBe('/experts')
  })

  it('refuses a backslash, which some browsers normalise to a slash', () => {
    expect(safeNext('/\\evil.example')).toBe('/experts')
    expect(safeNext('/path\\..\\..')).toBe('/experts')
  })

  it('falls back for empty and missing values', () => {
    expect(safeNext(null)).toBe('/experts')
    expect(safeNext(undefined)).toBe('/experts')
    expect(safeNext('')).toBe('/experts')
  })

  it('honours a caller-supplied fallback', () => {
    expect(safeNext(null, '/chats')).toBe('/chats')
  })
})
