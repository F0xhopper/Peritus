import { NextResponse } from 'next/server'

import { ApiError } from '@/lib/api/errors'
import { proxyJson } from '@/lib/api/proxy'
import { appUrl } from '@/lib/api/server'
import { pkceCookies } from '@/lib/auth/cookies'
import { challengeFor, createVerifier, safeNext } from '@/lib/auth/pkce'

/**
 * Begin Google sign-in.
 *
 * A GET that ends in a 302, because OAuth is a redirect dance and the browser
 * has to be the one that travels. The steps, in the order they matter:
 *
 * 1. Mint a PKCE verifier here, server-side, and keep it in an httpOnly cookie.
 *    Only its SHA-256 challenge is sent anywhere, so an intercepted auth code
 *    is worthless without this cookie — which page JavaScript cannot read.
 * 2. Ask the API for GoTrue's authorize URL. The `redirect_to` is built from
 *    server configuration and never from anything in the request, so this
 *    endpoint cannot be pointed at another origin. GoTrue's own allowlist is
 *    the second line: an unlisted `redirect_to` is accepted by `/authorize`
 *    and then replaced with the project's Site URL when the code comes back,
 *    so a code is never delivered off-origin — but the check happens there,
 *    not here, and a missing allowlist entry looks like "sign-in works and
 *    lands on the wrong site" rather than an error.
 * 3. Remember where the user was heading in a second short-lived cookie, since
 *    there is nowhere else to put it: the callback arrives from Google, not
 *    from us, and anything in the URL is Google's to decide.
 *
 * `NEXT_PUBLIC_APP_URL` — not the request's own origin — builds the redirect,
 * so the value must match the Supabase allowlist exactly. Deriving it from the
 * request would silently work in development and fail behind a proxy that
 * rewrites Host.
 */
export async function GET(request: Request) {
  const requestUrl = new URL(request.url)
  const next = safeNext(requestUrl.searchParams.get('next'))
  const redirectTo = `${appUrl()}/api/auth/callback`

  const verifier = createVerifier()
  const challenge = await challengeFor(verifier)

  try {
    const params = new URLSearchParams({
      provider: 'google',
      code_challenge: challenge,
      redirect_to: redirectTo,
    })
    const { url } = await proxyJson<{ url: string }>(`/auth/oauth/authorize?${params}`, {
      anonymous: true,
    })

    const response = NextResponse.redirect(url, { status: 302 })
    for (const cookie of pkceCookies(verifier, next)) response.cookies.set(cookie)
    return response
  } catch (error) {
    // A failure here (Supabase not configured, provider not enabled) must land
    // the user back on the login page with something readable, not on a JSON
    // error body — they arrived by clicking a button, not by calling an API.
    const login = new URL('/login', appUrl())
    login.searchParams.set('next', next)
    login.searchParams.set('error', errorMessage(error))
    return NextResponse.redirect(login, { status: 302 })
  }
}

const GENERIC = 'Could not start Google sign-in. Try an email code instead.'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    // The API says this plainly when Supabase is not configured, and it is the
    // most likely failure in a fresh deployment.
    return 'Google sign-in is not configured on this server.'
  }
  if (error instanceof Error && error.message) return error.message.slice(0, 200)
  return GENERIC
}
