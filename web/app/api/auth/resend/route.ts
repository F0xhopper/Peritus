import { NextResponse } from 'next/server'

import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

/**
 * Send the sign-up confirmation code again.
 *
 * Always 204 unless rate-limited: the API will not say whether the address has
 * an account, and neither does this.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || !body.email.trim()) {
    return NextResponse.json({ detail: 'Enter an email address.' }, { status: 400 })
  }
  return forward('/auth/resend', {
    method: 'POST',
    anonymous: true,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: body.email.trim() }),
  })
}
