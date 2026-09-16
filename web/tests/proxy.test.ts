import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  NotAuthenticatedError,
  isNextControlFlow,
  parseRetryAfter,
} from '@/lib/api/errors'

/**
 * The refresh-once behaviour, against a mocked FastAPI.
 *
 * This is the path that decides whether a user stays signed in, and it has
 * three distinct failure modes that must not be confused:
 *
 * 1. **Access token expired, refresh token good** → refresh once, retry once,
 *    succeed. The user notices nothing.
 * 2. **Refresh token dead** → `NotAuthenticatedError`, cookies cleared,
 *    redirect to sign in.
 * 3. **Auth server unreachable (503)** → an `ApiError`, *not* a sign-out. The
 *    refresh token is very likely still valid, and logging someone out
 *    mid-build over a DNS blip is the bug the API's 503 exists to prevent.
 *
 * `next/headers` is mocked with a real in-memory cookie jar, because
 * `proxyFetch` reads and writes it and the interesting assertions are about
 * what ends up in it.
 */

const UPSTREAM = 'http://api.test'

interface Jar {
  store: Map<string, string>
  writable: boolean
}

const jar: Jar = { store: new Map(), writable: true }

vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) => {
      const value = jar.store.get(name)
      return value === undefined ? undefined : { name, value }
    },
    set: (spec: { name: string; value: string } | string, maybeValue?: string) => {
      // A server component's cookie store throws on write; the proxy has to
      // survive that and still use the fresh token for the request in hand.
      if (!jar.writable) throw new Error('Cookies can only be modified in a Server Action')
      if (typeof spec === 'string') jar.store.set(spec, maybeValue ?? '')
      else jar.store.set(spec.name, spec.value)
    },
    delete: (name: string) => {
      if (!jar.writable) throw new Error('Cookies can only be modified in a Server Action')
      jar.store.delete(name)
    },
  }),
}))

const server = setupServer()

beforeAll(() => {
  process.env.PERITUS_API_URL = UPSTREAM
  server.listen({ onUnhandledRequest: 'error' })
})
afterEach(() => {
  server.resetHandlers()
  jar.store.clear()
  jar.writable = true
})
afterAll(() => server.close())

/** Imported lazily so the `next/headers` mock is in place first. */
async function proxy() {
  return import('@/lib/api/proxy')
}

let refreshCalls = 0
let expertsCalls: (string | null)[] = []

beforeEach(() => {
  refreshCalls = 0
  expertsCalls = []
})

/** The upstream: `/experts` needs a live token, `/auth/refresh` mints one. */
function handlers(options: { refreshStatus?: number; liveToken?: string } = {}) {
  const { refreshStatus = 200, liveToken = 'fresh-access' } = options
  return [
    http.get(`${UPSTREAM}/experts`, ({ request }) => {
      const auth = request.headers.get('authorization')
      expertsCalls.push(auth)
      if (auth === `Bearer ${liveToken}`) return HttpResponse.json([{ id: 1, name: 'a' }])
      return HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 })
    }),
    http.post(`${UPSTREAM}/auth/refresh`, async ({ request }) => {
      refreshCalls += 1
      const body = (await request.json()) as { refresh_token: string }
      if (refreshStatus !== 200) {
        return HttpResponse.json({ detail: 'refresh failed' }, { status: refreshStatus })
      }
      if (body.refresh_token !== 'good-refresh') {
        return HttpResponse.json({ detail: 'Invalid refresh token' }, { status: 401 })
      }
      return HttpResponse.json({
        access_token: liveToken,
        refresh_token: 'rotated-refresh',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: null,
        user: { id: 'u1', email: 'a@b.c' },
      })
    }),
  ]
}

describe('proxyFetch', () => {
  it('sends the access token straight through when it is live', async () => {
    server.use(...handlers({ liveToken: 'live-access' }))
    jar.store.set('peritus_access_token', 'live-access')
    jar.store.set('peritus_refresh_token', 'good-refresh')

    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).resolves.toEqual([{ id: 1, name: 'a' }])
    expect(refreshCalls).toBe(0)
  })

  it('refreshes once and retries when the access token is stale', async () => {
    server.use(...handlers())
    jar.store.set('peritus_access_token', 'stale-access')
    jar.store.set('peritus_refresh_token', 'good-refresh')

    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).resolves.toEqual([{ id: 1, name: 'a' }])

    expect(refreshCalls).toBe(1)
    // Once with the stale token, once with the fresh one. Never a third time.
    expect(expertsCalls).toEqual(['Bearer stale-access', 'Bearer fresh-access'])
    // The rotated pair is persisted.
    expect(jar.store.get('peritus_access_token')).toBe('fresh-access')
    expect(jar.store.get('peritus_refresh_token')).toBe('rotated-refresh')
  })

  it('refreshes before spending a request when only the refresh cookie exists', async () => {
    // The ordinary expired-access case: the access cookie has simply lapsed.
    server.use(...handlers())
    jar.store.set('peritus_refresh_token', 'good-refresh')

    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).resolves.toEqual([{ id: 1, name: 'a' }])
    expect(refreshCalls).toBe(1)
    // Only one upstream call: no request was wasted on a certain 401.
    expect(expertsCalls).toEqual(['Bearer fresh-access'])
  })

  it('throws NotAuthenticatedError and clears the cookies when the refresh token is dead', async () => {
    server.use(...handlers())
    jar.store.set('peritus_access_token', 'stale-access')
    jar.store.set('peritus_refresh_token', 'dead-refresh')

    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).rejects.toBeInstanceOf(NotAuthenticatedError)
    expect(jar.store.has('peritus_access_token')).toBe(false)
    expect(jar.store.has('peritus_refresh_token')).toBe(false)
  })

  it('throws NotAuthenticatedError with no cookies at all, without calling upstream', async () => {
    server.use(...handlers())
    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).rejects.toBeInstanceOf(NotAuthenticatedError)
    expect(expertsCalls).toEqual([])
    expect(refreshCalls).toBe(0)
  })

  it('does NOT sign the user out when the auth server is unreachable', async () => {
    // The distinction the API draws deliberately: 503 is "we could not reach
    // the auth server", not "your session is over". A DNS blip once logged a
    // user out mid-build, discarding a perfectly valid refresh token.
    server.use(...handlers({ refreshStatus: 503 }))
    jar.store.set('peritus_access_token', 'stale-access')
    jar.store.set('peritus_refresh_token', 'good-refresh')

    const { proxyJson } = await proxy()
    const error = await proxyJson('/experts').catch((thrown: unknown) => thrown)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(503)
    expect(error).not.toBeInstanceOf(NotAuthenticatedError)
    // The session survives.
    expect(jar.store.get('peritus_refresh_token')).toBe('good-refresh')
  })

  it('still succeeds when the cookie store is read-only, as in a server render', async () => {
    // A server component cannot write cookies. The request must go through on
    // the fresh token anyway; `proxy.ts` persists it on the next navigation.
    server.use(...handlers())
    jar.store.set('peritus_access_token', 'stale-access')
    jar.store.set('peritus_refresh_token', 'good-refresh')
    jar.writable = false

    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts')).resolves.toEqual([{ id: 1, name: 'a' }])
    expect(jar.store.get('peritus_access_token')).toBe('stale-access')
  })

  it('sends no bearer for an anonymous call', async () => {
    server.use(
      http.get(`${UPSTREAM}/auth/status`, ({ request }) => {
        expect(request.headers.get('authorization')).toBeNull()
        return HttpResponse.json({ auth_enabled: true, login_available: true })
      })
    )
    jar.store.set('peritus_access_token', 'live-access')
    const { proxyJson } = await proxy()
    await expect(proxyJson('/auth/status', { anonymous: true })).resolves.toMatchObject({
      auth_enabled: true,
    })
  })
})

describe('proxyJson error decoding', () => {
  it('preserves a structured 402 detail rather than flattening it to text', async () => {
    // The whole 402 payload is what the UI renders — the numbers and the one
    // available remedy. Flattening it would throw that away.
    const denial = {
      code: 'insufficient_credits',
      message: 'This standard build costs 3 credits, and you have 1.',
      required_credits: 3,
      available_credits: 1,
      tier: 'standard',
      plan: 'free',
      remedy: {
        kind: 'request_credits',
        label: 'Request credits',
        detail: 'Credits are issued manually while billing is in private beta.',
      },
    }
    server.use(
      http.post(`${UPSTREAM}/experts/build`, () =>
        HttpResponse.json({ detail: denial }, { status: 402 })
      )
    )
    jar.store.set('peritus_access_token', 'live-access')

    const { proxyJson } = await proxy()
    const error = (await proxyJson('/experts/build', { method: 'POST' }).catch(
      (thrown: unknown) => thrown
    )) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(402)
    expect(error.detail).toEqual(denial)
    // The message is the human half, for a toast fallback.
    expect(error.message).toBe(denial.message)
  })

  it('reads a string detail as the message', async () => {
    server.use(
      http.get(`${UPSTREAM}/experts`, () =>
        HttpResponse.json({ detail: 'Expert not found' }, { status: 404 })
      )
    )
    jar.store.set('peritus_access_token', 'live-access')
    const { proxyJson } = await proxy()
    const error = (await proxyJson('/experts').catch((thrown: unknown) => thrown)) as ApiError
    expect(error.status).toBe(404)
    expect(error.message).toBe('Expert not found')
    expect(error.detail).toBeUndefined()
  })

  it('carries Retry-After off a 429', async () => {
    server.use(
      http.get(`${UPSTREAM}/experts`, () =>
        HttpResponse.json(
          { detail: 'slow down' },
          { status: 429, headers: { 'Retry-After': '42' } }
        )
      )
    )
    jar.store.set('peritus_access_token', 'live-access')
    const { proxyJson } = await proxy()
    const error = (await proxyJson('/experts').catch((thrown: unknown) => thrown)) as ApiError
    expect(error.retryAfter).toBe(42)
  })

  it('reports a transport failure as status 0, distinguishable from a 500', async () => {
    server.use(http.get(`${UPSTREAM}/experts`, () => HttpResponse.error()))
    jar.store.set('peritus_access_token', 'live-access')
    const { proxyJson } = await proxy()
    const error = (await proxyJson('/experts').catch((thrown: unknown) => thrown)) as ApiError
    expect(error.status).toBe(0)
    expect(error.message).toContain('Could not reach')
  })

  it('returns undefined for a 204 rather than failing to parse an empty body', async () => {
    server.use(http.delete(`${UPSTREAM}/experts/x`, () => new HttpResponse(null, { status: 204 })))
    jar.store.set('peritus_access_token', 'live-access')
    const { proxyJson } = await proxy()
    await expect(proxyJson('/experts/x', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})

describe('isNextControlFlow', () => {
  it('recognises a NEXT_ digest, so notFound() is never swallowed', () => {
    // A wrapper that caught this would turn a deliberate 404 into an error page.
    expect(isNextControlFlow(Object.assign(new Error(), { digest: 'NEXT_NOT_FOUND' }))).toBe(true)
    expect(isNextControlFlow(Object.assign(new Error(), { digest: 'NEXT_REDIRECT;/login' }))).toBe(
      true
    )
  })

  it('does not mistake an ordinary error for control flow', () => {
    expect(isNextControlFlow(new Error('boom'))).toBe(false)
    expect(isNextControlFlow(Object.assign(new Error(), { digest: 'abc123' }))).toBe(false)
    expect(isNextControlFlow(null)).toBe(false)
    expect(isNextControlFlow('NEXT_NOT_FOUND')).toBe(false)
  })
})

describe('parseRetryAfter', () => {
  it('reads a seconds value', () => {
    expect(parseRetryAfter('30')).toBe(30)
    expect(parseRetryAfter('0')).toBe(0)
  })

  it('returns null for an absent or non-numeric value', () => {
    expect(parseRetryAfter(null)).toBeNull()
    expect(parseRetryAfter('Wed, 21 Oct 2026 07:28:00 GMT')).toBeNull()
    expect(parseRetryAfter('-5')).toBeNull()
  })
})
