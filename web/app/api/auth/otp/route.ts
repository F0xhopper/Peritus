import { NextResponse } from 'next/server'

import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

/**
 * Request a six-digit login code.
 *
 * Everything interesting is passed through rather than interpreted: a 429 with
 * its `Retry-After` becomes the verify page's countdown, and the 400 an
 * invite-only workspace returns for an unknown email is the copy the login card
 * shows. Deciding here what those mean would put the policy in two places.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || !body.email.trim()) {
    return NextResponse.json({ detail: 'Enter an email address.' }, { status: 400 })
  }

  return forward('/auth/otp', {
    method: 'POST',
    anonymous: true,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: body.email.trim() }),
  })
}
