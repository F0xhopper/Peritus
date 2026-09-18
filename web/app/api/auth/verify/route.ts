import { NextResponse } from 'next/server'

import { guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { postForSession } from '@/lib/auth/respond'

/**
 * Exchange an email code for a session: a sign-in code (`type: email`) or the
 * code that confirms a new account (`type: signup`).
 *
 * This is one of the places the session tokens exist in this process, and they
 * go straight into httpOnly cookies — the response body deliberately carries
 * only the user, so nothing in page JavaScript can ever read an access token.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown; token?: unknown; type?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || typeof body.token !== 'string') {
    return NextResponse.json({ detail: 'Enter the code we emailed you.' }, { status: 400 })
  }
  return postForSession(request, '/auth/verify', {
    email: body.email.trim(),
    token: body.token.trim(),
    type: body.type === 'signup' ? 'signup' : 'email',
  })
}
