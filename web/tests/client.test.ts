import { afterEach, describe, expect, it, vi } from 'vitest'

import { ClientApiError, apiJson, apiSend, apiVoid, messageFor } from '@/lib/api/client'

/**
 * The browser's half of the BFF.
 *
 * Every client mutation goes through here, and the failure modes are the quiet
 * kind: a body that does not decode, a 429 whose `Retry-After` is dropped, an
 * API that said exactly what was wrong being reported as "Something went
 * wrong." One of these tests exists because of a real regression — `apiSend`
 * against a 204 threw a `SyntaxError` from `res.json()`, which surfaced as the
 * generic fallback and made a working sign-in look broken.
 */

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

afterEach(() => {
  fetchMock.mockReset()
})

/** A `Response` with the given status and JSON body. */
function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

describe('apiJson', () => {
  it('returns the decoded body on success', async () => {
    fetchMock.mockResolvedValue(json(200, { slug: 'thomism' }))
    await expect(apiJson<{ slug: string }>('/api/x')).resolves.toEqual({ slug: 'thomism' })
  })

  it("uses the API's own message when it sent one", async () => {
    // FastAPI's shape. This message is the whole point: the API knows why it
    // refused and the fallback does not.
    fetchMock.mockResolvedValue(json(422, { detail: 'That URL cannot be fetched: 10.0.0.1 …' }))
    await expect(apiJson('/api/x', {}, 'Could not add that URL.')).rejects.toMatchObject({
      status: 422,
      message: 'That URL cannot be fetched: 10.0.0.1 …',
    })
  })

  it('keeps a structured detail intact rather than flattening it', async () => {
    // The 402 entitlement denial is an object the UI renders as a panel; a
    // client that stringified it would have nothing to render.
    const denial = { code: 'insufficient_credits', needed: 40, balance: 5 }
    fetchMock.mockResolvedValue(json(402, { detail: denial }))
    const error = await apiJson('/api/experts/build').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ClientApiError)
    expect((error as ClientApiError).detail).toEqual(denial)
  })

  it('falls back by status when the body carries no message', async () => {
    fetchMock.mockResolvedValue(json(500, {}))
    await expect(apiJson('/api/x', {}, 'Could not save.')).rejects.toMatchObject({
      message: 'The Peritus API hit an internal error.',
    })
  })

  it('reports an unreachable API as status 0, not as a thrown TypeError', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(apiJson('/api/x')).rejects.toMatchObject({
      status: 0,
      message: 'Could not reach the Peritus API.',
    })
  })

  it('surfaces `Retry-After` so a countdown matches the limiter', async () => {
    fetchMock.mockResolvedValue(
      json(429, { detail: 'Too many attempts.' }, { 'Retry-After': '45' })
    )
    await expect(apiJson('/api/auth/otp')).rejects.toMatchObject({ status: 429, retryAfter: 45 })
  })

  it('throws a ClientApiError, not a SyntaxError, when there is no body to decode', async () => {
    // The regression: a 204 through `apiJson` used to throw out of
    // `res.json()`, which is not an `ApiError`, so `messageFor` reported the
    // fallback and a successful request looked like a failed one.
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    const error = await apiJson('/api/auth/otp', {}, 'Could not send a code.').catch(
      (e: unknown) => e
    )
    expect(error).toBeInstanceOf(ClientApiError)
  })
})

describe('apiVoid', () => {
  it('resolves on a 204 with no body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(apiVoid('/api/experts/x', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('still decodes a failure body', async () => {
    fetchMock.mockResolvedValue(json(409, { detail: 'This expert is building.' }))
    await expect(apiVoid('/api/x')).rejects.toMatchObject({
      status: 409,
      message: 'This expert is building.',
    })
  })
})

describe('apiSend', () => {
  it('sends JSON with the content type the API expects', async () => {
    fetchMock.mockResolvedValue(json(200, { ok: true }))
    await apiSend('/api/x', 'PATCH', { title: 'A name' })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe('{"title":"A name"}')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
  })

  it('omits the body and its header entirely when there is nothing to send', async () => {
    // A bodyless POST with a JSON content type is a lie about the request, and
    // some proxies will wait for a body that never arrives.
    fetchMock.mockResolvedValue(json(200, {}))
    await apiSend('/api/x', 'POST')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.body).toBeUndefined()
    expect(init.headers).toBeUndefined()
  })
})

describe('messageFor', () => {
  it('prefers the API error over the fallback', () => {
    expect(messageFor(new ClientApiError(400, 'Enter an email address.'), 'Nope')).toBe(
      'Enter an email address.'
    )
  })

  it('uses the fallback for anything else thrown', () => {
    expect(messageFor(new TypeError('boom'), 'Could not save.')).toBe('Could not save.')
    expect(messageFor('a string', 'Could not save.')).toBe('Could not save.')
  })
})
