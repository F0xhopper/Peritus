import { NextResponse, type NextRequest } from 'next/server'

import { callApi } from '@/lib/api/server'
import { ACCESS_COOKIE, REFRESH_COOKIE, sessionCookies } from '@/lib/auth/cookies'
import type { Session } from '@/lib/api/types'

/**
 * The auth gate for the `(app)` routes. (`proxy.ts` replaces `middleware.ts`
 * in Next 16; the function may be named `proxy` or be the default export.)
 *
 * Two jobs, and only these two:
 *
 * 1. No session cookies at all → 302 to `/login?next=<path>`, so an app URL
 *    pasted into a fresh browser lands back where it was aimed after sign-in.
 * 2. Only the refresh cookie → refresh **here**. This is the reason the gate
 *    exists at all: a server component cannot write cookies, so if the rotation
 *    did not happen at the edge the app would refresh on every single request
 *    and never persist the result.
 *
 * Everything else — authorisation, 404-for-other-people's-experts, the actual
 * data — is the API's business and is checked there on every call.
 */

const APP_PREFIXES = ['/experts', '/chats', '/settings', '/admin']

function isAppPath(pathname: string): boolean {
  return APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))
}

function loginRedirect(request: NextRequest): NextResponse {
  const url = request.nextUrl.clone()
  const next = `${request.nextUrl.pathname}${request.nextUrl.search}`
  url.pathname = '/login'
  url.search = ''
  url.searchParams.set('next', next)
  const res = NextResponse.redirect(url)
  // Whatever was there is unusable; clear it so the login page starts clean.
  res.cookies.delete(ACCESS_COOKIE)
  res.cookies.delete(REFRESH_COOKIE)
  return res
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  if (!isAppPath(pathname)) return NextResponse.next()

  const access = request.cookies.get(ACCESS_COOKIE)?.value
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value

  if (access) return NextResponse.next()
  if (!refresh) return loginRedirect(request)

  // Rotate at the edge and put the new pair on the response that continues to
  // the page, so the render below sees a live access cookie.
  let session: Session
  try {
    const res = await callApi('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (res.status === 503) {
      // The auth server is unreachable; the refresh token is probably fine. Let
      // the request through — the page's own fetch will fail with something
      // honest instead of silently logging a user out mid-build.
      return NextResponse.next()
    }
    if (!res.ok) return loginRedirect(request)
    session = (await res.json()) as Session
  } catch {
    return NextResponse.next()
  }

  const response = NextResponse.next({
    // Make the fresh token visible to this render, not only to the next one.
    request: {
      headers: (() => {
        const h = new Headers(request.headers)
        const jar = request.cookies
        jar.set(ACCESS_COOKIE, session.access_token)
        h.set('cookie', jar.toString())
        return h
      })(),
    },
  })
  // One definition of the cookie shape, in `lib/auth/cookies`. It was written
  // out here as well, and in `lib/api/proxy.ts`, and three copies of
  // httpOnly/secure/sameSite/path is three places for one of them to drift.
  for (const cookie of sessionCookies(session)) response.cookies.set(cookie)
  return response
}

export const config = {
  // Static assets, the image optimiser and `/api/*` are excluded: the route
  // handlers under `/api/auth/*` must stay reachable without a session, and
  // running an auth gate over CSS would break the login page it redirects to.
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|ico|webp|txt|xml)$).*)',
  ],
}
