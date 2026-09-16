import { describe, expect, it } from 'vitest'

import { canManage, sharePath, sharedPictureUrl } from '@/lib/access'
import { ApiError } from '@/lib/api/errors'
import { decodeError, throwForStatus, upstream } from '@/lib/api/server'

/**
 * The two pure seams the whole BFF sits on, neither of which had a test.
 *
 * `decodeError` is the one that matters: every error a user reads comes out of
 * it, and every failure mode is silent. Flattening a structured 402 would leave
 * the entitlement panel with nothing to render; dropping the API's own sentence
 * would replace "that URL cannot be fetched: 10.0.0.1" with "Request failed".
 *
 * `canManage` is two lines and is the whole viewer/owner boundary in the UI.
 * It is not the security boundary — the API re-checks every mutation — but a
 * viewer meeting a button that 404s is the bug it exists to prevent.
 */

/** A `Response` with the given status and raw body text. */
function res(status: number, body: string | null, headers: Record<string, string> = {}): Response {
  return new Response(body, { status, headers })
}

describe('decodeError', () => {
  it("uses FastAPI's string detail as the message", async () => {
    const decoded = await decodeError(res(422, JSON.stringify({ detail: 'Enter an email.' })))
    expect(decoded).toEqual({ message: 'Enter an email.', detail: undefined })
  })

  it('keeps a structured detail whole', async () => {
    // The 402 entitlement denial. A client renders it as a panel with the
    // numbers in it, so flattening it to a string would lose the payload.
    const denial = { code: 'insufficient_credits', needed: 40, balance: 5 }
    const decoded = await decodeError(res(402, JSON.stringify({ detail: denial })))
    expect(decoded.detail).toEqual(denial)
  })

  it("takes a structured detail's own message when it has one", async () => {
    const decoded = await decodeError(
      res(402, JSON.stringify({ detail: { code: 'x', message: 'Not enough credits.' } }))
    )
    expect(decoded.message).toBe('Not enough credits.')
  })

  it('falls back to the status line for an empty body', async () => {
    const decoded = await decodeError(res(502, null))
    expect(decoded.message).toBeTruthy()
    expect(decoded.detail).toBeUndefined()
  })

  it('does not throw on a body that is not JSON', async () => {
    // A proxy's HTML error page, which is exactly when a decoder that assumes
    // JSON would turn a bad gateway into an unhandled exception.
    const decoded = await decodeError(res(502, '<html>Bad Gateway</html>'))
    expect(decoded.message).toContain('Bad Gateway')
  })

  it('truncates a runaway body rather than putting it in a toast', async () => {
    const decoded = await decodeError(res(500, 'x'.repeat(5000)))
    expect(decoded.message.length).toBeLessThanOrEqual(400)
  })

  it('handles a JSON body with no `detail` at all', async () => {
    const decoded = await decodeError(res(500, JSON.stringify({ error: 'nope' })))
    expect(decoded.detail).toEqual({ error: 'nope' })
  })
})

describe('throwForStatus', () => {
  it('throws an ApiError carrying the status, the detail and Retry-After', async () => {
    const error = await throwForStatus(
      res(429, JSON.stringify({ detail: 'Too many attempts.' }), { 'Retry-After': '30' })
    ).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 429,
      message: 'Too many attempts.',
      retryAfter: 30,
    })
  })

  it('reports no Retry-After as null rather than as NaN or zero', async () => {
    // Zero would read as "retry immediately", which is the opposite of unknown.
    const error = (await throwForStatus(res(500, null)).catch((e: unknown) => e)) as ApiError
    expect(error.retryAfter).toBeNull()
  })
})

describe('upstream', () => {
  it('appends a query string only when there is one', () => {
    expect(upstream('/experts')).toMatch(/\/experts$/)
    expect(upstream('/experts', new URLSearchParams())).toMatch(/\/experts$/)
    expect(upstream('/experts', new URLSearchParams({ limit: '5' }))).toMatch(/\/experts\?limit=5$/)
  })

  it('tolerates a null params, which is what an unfiltered handler passes', () => {
    expect(upstream('/experts', null)).toMatch(/\/experts$/)
  })
})

describe('canManage', () => {
  it('is false for a viewer and true for an owner', () => {
    expect(canManage({ access: 'viewer' })).toBe(false)
    expect(canManage({ access: 'owner' })).toBe(true)
  })

  it('defaults to manageable when the server sends no access at all', () => {
    // An older server only ever returned the caller's own experts, so absent
    // means owner. Defaulting the other way would hide every control on it.
    expect(canManage({} as { access: 'owner' })).toBe(true)
  })
})

describe('share URLs', () => {
  it('are relative, so they work on whatever origin serves them', () => {
    expect(sharePath('abc')).toBe('/share/abc')
    expect(sharedPictureUrl('abc', 'v1')).toBe('/api/share/abc/picture?v=v1')
  })

  it('encode a token that would otherwise change the path', () => {
    expect(sharePath('a/b?c')).toBe('/share/a%2Fb%3Fc')
    expect(sharedPictureUrl('a/b', 'v/1')).toBe('/api/share/a%2Fb/picture?v=v%2F1')
  })
})
