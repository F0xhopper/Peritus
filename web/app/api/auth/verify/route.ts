import { NextResponse } from 'next/server'

import { ApiError } from '@/lib/api/errors'
import { errorResponse, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { callApi, throwForStatus } from '@/lib/api/server'
import { sessionCookies } from '@/lib/auth/cookies'
import type { Session } from '@/lib/api/types'

/**
 * Exchange an email code for a session.
 *
 * This is the one place the session tokens exist in this process, and they go
 * straight into httpOnly cookies — the response body deliberately carries only
 * the user, so nothing in page JavaScript can ever read an access token.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown; token?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || typeof body.token !== 'string') {
    return NextResponse.json({ detail: 'Enter the code we emailed you.' }, { status: 400 })
  }

  try {
    const res = await callApi('/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: body.email.trim(), token: body.token.trim() }),
    })
    if (!res.ok) await throwForStatus(res)
    const session = (await res.json()) as Session

    const response = NextResponse.json({ user: session.user })
    for (const cookie of sessionCookies(session)) response.cookies.set(cookie)
    return response
  } catch (error) {
    if (error instanceof ApiError) return errorResponse(error)
    return errorResponse(error)
  }
}
