import 'server-only'

import { NextResponse } from 'next/server'

import { ApiError, NotAuthenticatedError } from '@/lib/api/errors'
import { proxyFetch, type ProxyInit } from '@/lib/api/proxy'
import { appUrl } from '@/lib/api/server'

/**
 * Shared plumbing for the BFF route handlers under `app/api/`.
 *
 * Every handler is the same three lines — guard, forward, hand the response
 * back — so the interesting part of each file is which upstream path it names
 * and which query parameters it lets through.
 */

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

/**
 * CSRF guard on every mutating handler.
 *
 * `SameSite=Lax` already stops a cross-site POST from carrying the session
 * cookie, but it is one mechanism, it has historically had edge cases in
 * released browsers, and `Sec-Fetch-Site` costs nothing to check. A request
 * with neither header is allowed only when it is same-origin by `Origin`.
 */
export function guardOrigin(request: Request): NextResponse | null {
  if (SAFE_METHODS.has(request.method)) return null

  const site = request.headers.get('sec-fetch-site')
  if (site) {
    // `none` is a user-typed URL or a bookmark, which cannot be a POST from a
    // page; `same-origin` is the app itself. Everything else is cross-site.
    if (site === 'same-origin' || site === 'none') return null
    return NextResponse.json({ detail: 'Cross-site request refused.' }, { status: 403 })
  }

  const origin = request.headers.get('origin')
  if (!origin) {
    // No Origin and no Sec-Fetch-Site: not a browser fetch from a page. Server
    // to server and curl land here; both are same-origin by construction
    // because they already hold the session cookie.
    return null
  }
  const expected = new Set([appUrl(), new URL(request.url).origin])
  if (expected.has(origin.replace(/\/+$/, ''))) return null
  return NextResponse.json({ detail: 'Cross-site request refused.' }, { status: 403 })
}

/** Turn a thrown proxy error into the response the browser should see. */
export function errorResponse(error: unknown): NextResponse {
  if (error instanceof NotAuthenticatedError) {
    return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 })
  }
  if (error instanceof ApiError) {
    // `detail` is preserved as an object when the API sent one, so a 402's
    // numbers and remedy survive the hop through this layer.
    const body = error.detail !== undefined ? { detail: error.detail } : { detail: error.message }
    const headers = new Headers()
    if (error.retryAfter !== null) headers.set('Retry-After', String(error.retryAfter))
    return NextResponse.json(body, { status: error.status || 502, headers })
  }
  return NextResponse.json({ detail: 'Unexpected proxy failure.' }, { status: 500 })
}

/** Copy the headers a client needs from an upstream response. */
const FORWARDED_HEADERS = [
  'content-type',
  'content-disposition',
  'content-length',
  'cache-control',
  // Without this a picture's ETag never reaches the browser, so it re-downloads
  // the same bytes on every navigation and the immutable cache is pointless.
  'etag',
  'retry-after',
  'x-peritus-export-rows',
  'x-request-id',
]

function forwardedHeaders(res: Response): Headers {
  const headers = new Headers()
  for (const name of FORWARDED_HEADERS) {
    const value = res.headers.get(name)
    if (value) headers.set(name, value)
  }
  return headers
}

/**
 * Forward one upstream call, buffering the body.
 *
 * Used for everything that is not SSE or a file download. Buffering is
 * deliberate here: it lets the handler return a real status and a JSON body,
 * which is what the client's error handling reads.
 */
// Statuses the Fetch spec forbids a body on. Constructing a `Response` for one
// of these with *any* body — an empty ArrayBuffer included — throws, so they
// have to be built with an explicit null. 304 matters here: a revalidated
// picture comes back on this path, and buffering its (empty) body first is the
// difference between a cached image and a TypeError in the route handler.
const NULL_BODY_STATUSES = new Set([204, 205, 304])

export async function forward(path: string, init: ProxyInit = {}): Promise<NextResponse> {
  try {
    const res = await proxyFetch(path, init)
    if (NULL_BODY_STATUSES.has(res.status)) {
      return new NextResponse(null, { status: res.status, headers: forwardedHeaders(res) })
    }
    const body = await res.arrayBuffer()
    return new NextResponse(body, { status: res.status, headers: forwardedHeaders(res) })
  } catch (error) {
    return errorResponse(error)
  }
}

/**
 * Forward a streaming upstream call without buffering.
 *
 * The body is handed through untouched, so SSE frames reach the browser as they
 * are produced and a build log tails in real time. `X-Accel-Buffering: no` and
 * the no-transform cache header are there for the reverse proxies that would
 * otherwise hold a chunk back waiting for more.
 */
export async function forwardStream(path: string, init: ProxyInit = {}): Promise<Response> {
  try {
    const res = await proxyFetch(path, { ...init, stream: true })
    if (!res.ok) {
      const body = await res.arrayBuffer()
      return new NextResponse(body, { status: res.status, headers: forwardedHeaders(res) })
    }
    return new Response(res.body, {
      status: res.status,
      headers: {
        'Content-Type': res.headers.get('content-type') ?? 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    })
  } catch (error) {
    return errorResponse(error)
  }
}

/** A file download: stream the body and keep the filename the API chose. */
export async function forwardDownload(path: string, init: ProxyInit = {}): Promise<Response> {
  try {
    const res = await proxyFetch(path, { ...init, stream: true })
    if (!res.ok) {
      const body = await res.arrayBuffer()
      return new NextResponse(body, { status: res.status, headers: forwardedHeaders(res) })
    }
    return new Response(res.body, { status: res.status, headers: forwardedHeaders(res) })
  } catch (error) {
    return errorResponse(error)
  }
}

/** Pick only the query parameters a handler is allowed to pass upstream. */
export function pickParams(url: string, allowed: readonly string[]): URLSearchParams {
  const incoming = new URL(url).searchParams
  const out = new URLSearchParams()
  for (const key of allowed) {
    const value = incoming.get(key)
    if (value !== null && value !== '') out.set(key, value)
  }
  return out
}

/** `?a=1` or '' — appended to an upstream path. */
export function query(params: URLSearchParams): string {
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

/** Read a JSON body, or 400 if it is not JSON. */
export async function jsonBody<T>(request: Request): Promise<T | NextResponse> {
  try {
    return (await request.json()) as T
  } catch {
    return NextResponse.json({ detail: 'Expected a JSON body.' }, { status: 400 })
  }
}

export function isResponse(value: unknown): value is NextResponse {
  return value instanceof NextResponse || value instanceof Response
}
