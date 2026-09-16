/**
 * Server-only configuration and the low-level call into FastAPI.
 *
 * `PERITUS_API_URL` is deliberately not `NEXT_PUBLIC_`: the browser never talks
 * to FastAPI directly, which is what lets the API keep CORS closed.
 */

import { ApiError, parseRetryAfter } from '@/lib/api/errors'

export function apiBaseUrl(): string {
  return (process.env.PERITUS_API_URL || 'http://localhost:8000').replace(/\/+$/, '')
}

export function appUrl(): string {
  return (process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000').replace(/\/+$/, '')
}

/** Build an upstream URL, forwarding a whitelist of query parameters. */
export function upstream(path: string, params?: URLSearchParams | null): string {
  const qs = params?.toString()
  return `${apiBaseUrl()}${path}${qs ? `?${qs}` : ''}`
}

export interface CallInit extends Omit<RequestInit, 'cache' | 'next'> {
  accessToken?: string | null
  /** Streaming responses must not be buffered or cached by the fetch layer. */
  stream?: boolean
}

/**
 * One fetch to FastAPI with the bearer attached. No refresh logic — that lives
 * in `proxyFetch`, which calls this twice at most.
 */
export async function callApi(path: string, init: CallInit = {}): Promise<Response> {
  const { accessToken, stream, headers, ...rest } = init
  const merged = new Headers(headers)
  if (accessToken) merged.set('Authorization', `Bearer ${accessToken}`)

  try {
    return await fetch(`${apiBaseUrl()}${path}`, {
      ...rest,
      headers: merged,
      // Every call is per-user and must never be cached by the data layer.
      cache: 'no-store',
      // `duplex: 'half'` is required to send a stream as a request body; it is
      // harmless otherwise and keeps multipart pass-through working.
      ...(rest.body instanceof ReadableStream ? { duplex: 'half' } : {}),
      ...(stream ? { signal: rest.signal ?? undefined } : {}),
    } as RequestInit)
  } catch (cause) {
    // A transport failure is a 0, distinguishable from every real status so the
    // UI can say "could not reach the API" rather than inventing a 500.
    throw new ApiError(0, 'Could not reach the Peritus API.', undefined, null)
  }
}

/** Decode a FastAPI error body into `(message, detail)`. */
export async function decodeError(res: Response): Promise<{ message: string; detail: unknown }> {
  const text = await res.text().catch(() => '')
  if (!text)
    return { message: res.statusText || `Request failed (${res.status})`, detail: undefined }
  try {
    const body = JSON.parse(text) as unknown
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return { message: detail, detail: undefined }
      // A structured detail (the 402 payload, a validation error list) is kept
      // whole. `message` is only a fallback for a toast.
      if (detail && typeof detail === 'object') {
        const message =
          'message' in detail && typeof (detail as { message: unknown }).message === 'string'
            ? (detail as { message: string }).message
            : res.statusText || `Request failed (${res.status})`
        return { message, detail }
      }
    }
    return { message: text.slice(0, 400), detail: body }
  } catch {
    return { message: text.slice(0, 400), detail: undefined }
  }
}

export async function throwForStatus(res: Response): Promise<never> {
  const { message, detail } = await decodeError(res)
  throw new ApiError(res.status, message, detail, parseRetryAfter(res.headers.get('retry-after')))
}
