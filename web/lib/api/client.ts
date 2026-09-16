/**
 * The browser's side of the BFF: one place that knows what a failed
 * `/api/…` response looks like.
 *
 * `lib/api/server.ts` does this for server components and route handlers.
 * Client components were doing it by hand — nineteen `if (!res.ok)` branches,
 * each guessing differently at what the body might contain, several of them
 * discarding the API's own message in favour of "Something went wrong."
 *
 * Two callers deliberately do not use this, and both need the `Response`
 * rather than a decoded body: `use-start-build` and `use-chat-stream` read SSE
 * frames as they arrive, and `web-vitals` fires a `keepalive` beacon on unload
 * whose answer nobody is around to read.
 *
 * The API always answers a failure with FastAPI's `{"detail": …}`, where the
 * detail is a **string** for ordinary errors and an **object** for the ones the
 * UI is meant to render — the 402 entitlement denial carries the numbers and
 * the one available remedy, and flattening it to a string throws the payload
 * away. `ClientApiError` keeps both: `message` for a toast, `detail` for a
 * component that knows what to do with it.
 */

import { ApiError, friendlyMessage, parseRetryAfter } from '@/lib/api/errors'

/**
 * A non-2xx from the BFF, with the API's own words where it gave any.
 *
 * Extends `ApiError` so a component can catch one type regardless of whether
 * the call came from a server loader or from the browser.
 */
export class ClientApiError extends ApiError {
  constructor(status: number, message: string, detail?: unknown, retryAfter?: number | null) {
    super(status, message, detail, retryAfter)
    this.name = 'ClientApiError'
  }
}

/** Status 0 means the request never got an answer: offline, DNS, a dropped connection. */
const UNREACHABLE = 0

async function decode(res: Response, fallback: string): Promise<ClientApiError> {
  let detail: unknown
  try {
    const body = (await res.json()) as { detail?: unknown } | null
    detail = body?.detail
  } catch {
    // A proxy error page, an empty body, a 502 from somewhere else. The status
    // is still the honest thing to report.
  }
  const message =
    typeof detail === 'string' && detail ? detail : friendlyMessage(res.status, fallback)
  return new ClientApiError(
    res.status,
    message,
    detail,
    parseRetryAfter(res.headers.get('retry-after'))
  )
}

async function call(path: string, init: RequestInit, fallback: string): Promise<Response> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ClientApiError(UNREACHABLE, friendlyMessage(UNREACHABLE, fallback))
  }
  if (!res.ok) throw await decode(res, fallback)
  return res
}

/**
 * A call that returns JSON. Throws `ClientApiError` on any failure.
 *
 * `fallback` is what the user sees when the API said nothing useful — so write
 * it about *this* action ("Could not save the avatar."), not about HTTP.
 */
export async function apiJson<T>(
  path: string,
  init: RequestInit = {},
  fallback = 'Something went wrong.'
): Promise<T> {
  const res = await call(path, init, fallback)
  try {
    return (await res.json()) as T
  } catch {
    // A 204, or a success with an empty body. Named rather than folded into
    // `fallback`, because the cause is a caller that should have used
    // `apiVoid` — and reported as the generic message it looks exactly like
    // the API having failed, which is how it goes unnoticed.
    throw new ClientApiError(res.status, fallback, undefined, null)
  }
}

/** A call whose success carries no body — a 204, or a body nobody reads. */
export async function apiVoid(
  path: string,
  init: RequestInit = {},
  fallback = 'Something went wrong.'
): Promise<void> {
  await call(path, init, fallback)
}

/** `apiJson` with a JSON body, which is most of the mutations. */
export function apiSend<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
  fallback?: string
): Promise<T> {
  return apiJson<T>(
    path,
    {
      method,
      ...(body === undefined
        ? {}
        : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    },
    fallback
  )
}

/** The message to show for anything thrown by the calls above. */
export function messageFor(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}
