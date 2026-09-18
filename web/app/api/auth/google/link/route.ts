import { NextResponse } from 'next/server'

import { ApiError, NotAuthenticatedError } from '@/lib/api/errors'
import { proxyJson } from '@/lib/api/proxy'
import { appUrl } from '@/lib/api/server'
import { pkceCookies } from '@/lib/auth/cookies'
import { challengeFor, createVerifier, safeNext } from '@/lib/auth/pkce'

/**
 * Add Google as a way into the signed-in account.
 *
 * The same PKCE dance as `/api/auth/google/start`, with one difference: the
 * authorize URL comes from GoTrue's *link* endpoint, which takes the user's
 * bearer, so the identity Google returns is attached to this account rather
 * than signing someone in. The code comes back to the same callback and is
 * exchanged the same way.
 *
 * A GET, because it ends in a navigation — and a GET that changes nothing on
 * its own: until the person approves at Google, nothing is linked.
 */
export async function GET(request: Request) {
  const next = safeNext(new URL(request.url).searchParams.get('next'), '/settings')
  const verifier = createVerifier()
  const challenge = await challengeFor(verifier)

  try {
    const params = new URLSearchParams({
      provider: 'google',
      code_challenge: challenge,
      redirect_to: `${appUrl()}/api/auth/callback`,
    })
    const { url } = await proxyJson<{ url: string }>(`/auth/account/identities/authorize?${params}`)
    const response = NextResponse.redirect(url, { status: 302 })
    for (const cookie of pkceCookies(verifier, next)) response.cookies.set(cookie)
    return response
  } catch (error) {
    if (error instanceof NotAuthenticatedError) {
      const login = new URL('/login', appUrl())
      login.searchParams.set('next', next)
      return NextResponse.redirect(login, { status: 302 })
    }
    const back = new URL(next, appUrl())
    back.searchParams.set(
      'auth_error',
      error instanceof ApiError && error.message
        ? error.message.slice(0, 200)
        : 'Could not start linking Google.'
    )
    return NextResponse.redirect(back, { status: 302 })
  }
}
