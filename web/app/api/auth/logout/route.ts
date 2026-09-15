import { NextResponse } from 'next/server'

import { guardOrigin } from '@/lib/api/route'
import { proxyVoid } from '@/lib/api/proxy'
import { clearedSessionCookies } from '@/lib/auth/cookies'

/**
 * Sign out everywhere.
 *
 * The upstream revoke is best-effort; the cookies are cleared either way. A
 * failed revoke must never leave a user looking signed in — an expired token is
 * already un-revokable, and the API treats that as success.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  try {
    await proxyVoid('/auth/logout', { method: 'POST' })
  } catch {
    /* already signed out, or the auth server is unreachable */
  }

  const response = NextResponse.json({ ok: true })
  for (const cookie of clearedSessionCookies()) response.cookies.set(cookie)
  return response
}
