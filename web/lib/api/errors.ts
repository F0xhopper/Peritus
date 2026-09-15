/**
 * The two errors the proxy layer throws, kept in their own module so a Client
 * Component can import `ApiError` without dragging `next/headers` in with it.
 */

/**
 * A non-2xx from FastAPI.
 *
 * `detail` holds the *structured* body when the API sent one — the 402
 * entitlement denial is an object with the numbers and the one available
 * remedy in it, and flattening that to a string would throw away the whole
 * payload the UI is supposed to render.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly retryAfter: number | null

  constructor(status: number, message: string, detail?: unknown, retryAfter?: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfter = retryAfter ?? null
  }
}

/**
 * The refresh token is dead (or was never there). Callers turn this into a
 * redirect to `/login?next=`; it is never shown to the user as an error.
 */
export class NotAuthenticatedError extends Error {
  constructor(message = 'Not authenticated') {
    super(message)
    this.name = 'NotAuthenticatedError'
  }
}

/**
 * Next signals `notFound()` and `redirect()` by throwing, and those throws carry
 * a `digest` beginning with `NEXT_`. Any wrapper that catches broadly must
 * rethrow them, or a `notFound()` inside a fetcher silently becomes a rendered
 * error page.
 */
export function isNextControlFlow(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const digest = (error as { digest?: unknown }).digest
  return typeof digest === 'string' && digest.startsWith('NEXT_')
}

/** Parse a `Retry-After` header. Seconds form only; HTTP-date is not used by the API. */
export function parseRetryAfter(value: string | null): number | null {
  if (!value) return null
  const seconds = Number(value)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

/** The message to show a user for an unknown failure, by status. */
export function friendlyMessage(status: number, fallback: string): string {
  if (status === 0) return 'Could not reach the Peritus API.'
  if (status === 429) return 'Too many requests — wait a moment and try again.'
  if (status === 503) return 'The service is temporarily unavailable.'
  if (status >= 500) return 'The Peritus API hit an internal error.'
  return fallback
}
