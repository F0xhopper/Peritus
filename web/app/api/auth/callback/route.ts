import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

import { callApi, appUrl, decodeError } from '@/lib/api/server'
import {
  LOGIN_NEXT_COOKIE,
  PKCE_COOKIE,
  clearedPkceCookies,
  sessionCookies,
} from '@/lib/auth/cookies'
import { safeNext } from '@/lib/auth/pkce'
import type { Session } from '@/lib/api/types'

/**
 * Where Google sends the user back to.
 *
 * GoTrue appends `?code=…` on success and `?error=…&error_description=…` when
 * the user cancelled or the provider refused. Both paths end in a redirect to a
 * page, never a JSON body: the browser got here by navigation, so an error has
 * to be rendered by the login card.
 *
 * The verifier cookie is consumed whatever happens. Leaving a used one behind
 * would let a replayed code be exchanged a second time.
 */
export async function GET(request: Request) {
  const url = new URL(request.url)
  const jar = await cookies()
  const next = safeNext(jar.get(LOGIN_NEXT_COOKIE)?.value)
  const verifier = jar.get(PKCE_COOKIE)?.value

  const fail = (message: string) => {
    const login = new URL('/login', appUrl())
    login.searchParams.set('next', next)
    login.searchParams.set('error', message.slice(0, 200))
    const response = NextResponse.redirect(login, { status: 302 })
    for (const cookie of clearedPkceCookies()) response.cookies.set(cookie)
    return response
  }

  // The provider said no. `error_description` is the human-readable half;
  // `access_denied` is the ordinary "user pressed cancel" and is not an error
  // worth alarming them about.
  const providerError = url.searchParams.get('error') ?? url.searchParams.get('error_code')
  if (providerError) {
    if (providerError === 'access_denied') {
      const login = new URL('/login', appUrl())
      login.searchParams.set('next', next)
      const response = NextResponse.redirect(login, { status: 302 })
      for (const cookie of clearedPkceCookies()) response.cookies.set(cookie)
      return response
    }
    return fail(url.searchParams.get('error_description') ?? providerError)
  }

  const code = url.searchParams.get('code')
  if (!code) return fail('Google sign-in returned no code. Try again.')
  if (!verifier) {
    // The 10-minute cookie expired, or the flow was started in another browser.
    return fail('That sign-in attempt expired. Try again.')
  }

  const res = await callApi('/auth/oauth/exchange', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auth_code: code, code_verifier: verifier }),
  })
  if (!res.ok) {
    const { message } = await decodeError(res)
    return fail(message || 'Could not complete Google sign-in.')
  }

  const session = (await res.json()) as Session
  const response = NextResponse.redirect(new URL(next, appUrl()), { status: 302 })
  for (const cookie of sessionCookies(session)) response.cookies.set(cookie)
  for (const cookie of clearedPkceCookies()) response.cookies.set(cookie)
  return response
}
