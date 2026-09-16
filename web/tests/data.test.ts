import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NotAuthenticatedError } from '@/lib/api/errors'

/**
 * The server-component data layer.
 *
 * Two behaviours, both of which are wrong in a way that renders *something*
 * rather than failing loudly:
 *
 * - **Failure translation.** A dead session has to become a redirect to
 *   `/login`, and a 404 has to become `notFound()`. The trap is that Next
 *   signals both of those by **throwing**, so a `catch` here that did not
 *   rethrow its own control flow would turn a deliberate 404 into a rendered
 *   error page — and the page would look like a bug in the API.
 * - **Absence that is not failure.** Build status before the first job and
 *   usage before anything is metered both 404 by design, and the page renders
 *   its "not yet" state from a null rather than a 404 page.
 *
 * The memoisation is deliberately *not* asserted here. `getExpert` is wrapped in
 * React's `cache`, which dedupes only inside a request render — outside one it
 * is a no-op, so a node test would measure nothing. Playwright covers it:
 * `generateMetadata` and the page body both call it on every expert page.
 *
 * One trap this file itself fell into, worth knowing before adding to it: do
 * **not** `vi.resetModules()` here. It gives `data.ts` a fresh copy of
 * `lib/api/errors`, so the `ApiError` this file throws is a different class from
 * the one `safely` checks with `instanceof` — and every translation silently
 * stops happening while the tests still look like they are exercising it.
 */

const proxyJson = vi.fn()
const redirect = vi.fn((url: string) => {
  // Next's `redirect` throws; the digest is how `isNextControlFlow` knows.
  const error = new Error(`NEXT_REDIRECT ${url}`) as Error & { digest: string }
  error.digest = `NEXT_REDIRECT;${url}`
  throw error
})
const notFound = vi.fn(() => {
  const error = new Error('NEXT_NOT_FOUND') as Error & { digest: string }
  error.digest = 'NEXT_HTTP_ERROR_FALLBACK;404'
  throw error
})

vi.mock('@/lib/api/proxy', () => ({ proxyJson: (...args: unknown[]) => proxyJson(...args) }))
vi.mock('next/navigation', () => ({
  redirect: (url: string) => redirect(url),
  notFound: () => notFound(),
}))
vi.mock('next/headers', () => ({ cookies: async () => new Map() }))

async function data() {
  return import('@/lib/api/data')
}

beforeEach(() => {
  proxyJson.mockReset()
  redirect.mockClear()
  notFound.mockClear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('failure translation', () => {
  it('sends a dead session to /login, carrying where it was going', async () => {
    proxyJson.mockRejectedValue(new NotAuthenticatedError())
    const { getExperts } = await data()

    await expect(getExperts('/experts/thomism')).rejects.toThrow(/NEXT_REDIRECT/)
    expect(redirect).toHaveBeenCalledWith('/login?next=%2Fexperts%2Fthomism')
  })

  it('treats a 401 the same as a dead refresh token', async () => {
    proxyJson.mockRejectedValue(new ApiError(401, 'Unauthorized'))
    const { getExperts } = await data()

    await expect(getExperts()).rejects.toThrow(/NEXT_REDIRECT/)
    expect(redirect).toHaveBeenCalledWith('/login?next=%2Fexperts')
  })

  it('turns a 404 into notFound(), not into an error page', async () => {
    proxyJson.mockRejectedValue(new ApiError(404, 'Expert not found'))
    const { getExpert } = await data()

    await expect(getExpert('gone')).rejects.toThrow()
    expect(notFound).toHaveBeenCalled()
  })

  it('rethrows anything else for the segment error boundary', async () => {
    // A 500 is not something a page can render around, and swallowing it would
    // show an empty expert instead of saying the API failed.
    proxyJson.mockRejectedValue(new ApiError(500, 'Internal'))
    const { getExperts } = await data()

    await expect(getExperts()).rejects.toMatchObject({ status: 500 })
    expect(redirect).not.toHaveBeenCalled()
    expect(notFound).not.toHaveBeenCalled()
  })

  it("does not swallow Next's own control flow", async () => {
    // The trap: `redirect()` and `notFound()` work by throwing, so a catch that
    // did not rethrow them would convert a deliberate 404 into a rendered error.
    const control = new Error('NEXT_NOT_FOUND') as Error & { digest: string }
    control.digest = 'NEXT_HTTP_ERROR_FALLBACK;404'
    proxyJson.mockRejectedValue(control)
    const { getExperts } = await data()

    await expect(getExperts()).rejects.toBe(control)
    expect(redirect).not.toHaveBeenCalled()
  })
})

describe('the endpoints that 404 by design', () => {
  it('report absence as null so the page can render its "not yet" state', async () => {
    // Build status before the first job, usage before anything is metered.
    proxyJson.mockRejectedValue(new ApiError(404, 'No build job for this expert'))
    const { getBuildStatus } = await data()

    await expect(getBuildStatus('thomism')).resolves.toBeNull()
    expect(notFound).not.toHaveBeenCalled()
  })

  it('still fail loudly on anything that is not a 404', async () => {
    proxyJson.mockRejectedValue(new ApiError(503, 'Unavailable'))
    const { getBuildStatus } = await data()

    await expect(getBuildStatus('thomism')).rejects.toMatchObject({ status: 503 })
  })
})
