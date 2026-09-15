import { NextResponse } from 'next/server'

import { errorResponse, guardOrigin } from '@/lib/api/route'
import { callApi, throwForStatus } from '@/lib/api/server'
import { REFRESH_COOKIE, clearedSessionCookies, sessionCookies } from '@/lib/auth/cookies'
import type { Session } from '@/lib/api/types'
import { cookies } from 'next/headers'

/**
 * Rotate the session from the refresh cookie.
 *
 * `proxy.ts` and `proxyFetch` both refresh on their own, so nothing in the app
 * normally calls this. It exists for the client-side case they cannot cover: a
 * tab left open past the access cookie's life with a stream to reopen.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const jar = await cookies()
  const refresh = jar.get(REFRESH_COOKIE)?.value
  if (!refresh) {
    return NextResponse.json({ detail: 'No session to refresh.' }, { status: 401 })
  }

  try {
    const res = await callApi('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) {
      // 503 is "we could not reach the auth server", which must not log anyone
      // out: the refresh token is very likely still good.
      if (res.status === 503) await throwForStatus(res)
      const dead = NextResponse.json({ detail: 'Session expired.' }, { status: 401 })
      for (const cookie of clearedSessionCookies()) dead.cookies.set(cookie)
      return dead
    }
    const session = (await res.json()) as Session
    const response = NextResponse.json({ user: session.user })
    for (const cookie of sessionCookies(session)) response.cookies.set(cookie)
    return response
  } catch (error) {
    return errorResponse(error)
  }
}
