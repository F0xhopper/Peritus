import 'server-only'

import { cookies } from 'next/headers'

import { ApiError, NotAuthenticatedError } from '@/lib/api/errors'
import { callApi, throwForStatus, type CallInit } from '@/lib/api/server'
import { ACCESS_COOKIE, REFRESH_COOKIE, accessCookieMaxAge, isProduction } from '@/lib/auth/cookies'
import type { Session } from '@/lib/api/types'

/**
 * The authenticated call into FastAPI, used by both route handlers and server
 * components.
 *
 * On a 401 it refreshes **once** and retries. If the refresh fails the session
 * is genuinely over and `NotAuthenticatedError` is thrown, which the callers
 * turn into a redirect to `/login?next=`. It never loops: a second 401 after a
 * successful refresh is reported as a 401, because retrying again would only
 * find the same thing.
 *
 * Writing the rotated cookies is best-effort by design. A route handler can
 * write them; a server component cannot, and `cookies().set` throws there. The
 * request must still succeed on the fresh token in that case — `proxy.ts`
 * refreshes at the edge on the next navigation, so the cookie catches up.
 */

interface RefreshResult {
  accessToken: string
  /** False in a server render, where the cookie store is read-only. */
  persisted: boolean
}

async function readCookie(name: string): Promise<string | undefined> {
  const jar = await cookies()
  return jar.get(name)?.value
}

async function writeSessionCookies(session: Session): Promise<boolean> {
  try {
    const jar = await cookies()
    const shared = { httpOnly: true, secure: isProduction(), sameSite: 'lax' as const, path: '/' }
    jar.set({
      ...shared,
      name: ACCESS_COOKIE,
      value: session.access_token,
      maxAge: accessCookieMaxAge(session.expires_in),
    })
    jar.set({
      ...shared,
      name: REFRESH_COOKIE,
      value: session.refresh_token,
      maxAge: 60 * 60 * 24 * 30,
    })
    return true
  } catch {
    // Server-component render: read-only cookie store. Not an error.
    return false
  }
}

async function clearSessionCookies(): Promise<void> {
  try {
    const jar = await cookies()
    jar.delete(ACCESS_COOKIE)
    jar.delete(REFRESH_COOKIE)
  } catch {
    /* read-only store — `proxy.ts` will clear them on the next navigation */
  }
}

/** Exchange the refresh cookie for a new session. Exported for `proxy.ts`. */
export async function refreshSession(refreshToken: string): Promise<Session> {
  const res = await callApi('/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!res.ok) {
    // 503 means "we could not reach the auth server", which is emphatically not
    // "your session is over" — the API draws that distinction deliberately, so
    // surface it as a transport error rather than logging the user out.
    if (res.status === 503) {
      throw new ApiError(503, 'The sign-in service is unreachable. Try again shortly.')
    }
    throw new NotAuthenticatedError('Session expired')
  }
  return (await res.json()) as Session
}

async function refreshOnce(): Promise<RefreshResult> {
  const refreshToken = await readCookie(REFRESH_COOKIE)
  if (!refreshToken) throw new NotAuthenticatedError('No refresh token')
  let session: Session
  try {
    session = await refreshSession(refreshToken)
  } catch (error) {
    if (error instanceof NotAuthenticatedError) await clearSessionCookies()
    throw error
  }
  const persisted = await writeSessionCookies(session)
  return { accessToken: session.access_token, persisted }
}

export interface ProxyInit extends Omit<CallInit, 'accessToken'> {
  /** Send without a bearer even if one is available (only `/auth/*` wants this). */
  anonymous?: boolean
}

export async function proxyFetch(path: string, init: ProxyInit = {}): Promise<Response> {
  const { anonymous, ...rest } = init

  if (anonymous) return callApi(path, rest)

  const access = await readCookie(ACCESS_COOKIE)
  const refresh = await readCookie(REFRESH_COOKIE)
  if (!access && !refresh) throw new NotAuthenticatedError('No session cookies')

  // A missing access cookie with a live refresh cookie is the ordinary
  // expired-access case: refresh before spending a request on a certain 401.
  let token = access
  if (!token) token = (await refreshOnce()).accessToken

  const first = await callApi(path, { ...rest, accessToken: token })
  if (first.status !== 401) return first

  // Release the discarded body so the connection is not held, but do **not**
  // await it: on a streaming response `cancel()` may not settle until the
  // server closes its end, which would make the retry wait on the request it
  // is replacing. Fire-and-forget still cancels.
  void first.body?.cancel().catch(() => {})
  const refreshed = await refreshOnce()
  return callApi(path, { ...rest, accessToken: refreshed.accessToken })
}

/** `proxyFetch` plus JSON decoding and the non-2xx throw. */
export async function proxyJson<T>(path: string, init: ProxyInit = {}): Promise<T> {
  const res = await proxyFetch(path, init)
  if (!res.ok) await throwForStatus(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** `proxyFetch` for a call whose body is discarded (DELETE, cancel, logout). */
export async function proxyVoid(path: string, init: ProxyInit = {}): Promise<void> {
  const res = await proxyFetch(path, init)
  if (!res.ok) await throwForStatus(res)
  // Not awaited, for the same reason as the retry path above.
  void res.body?.cancel().catch(() => {})
}

export { clearSessionCookies, writeSessionCookies }
