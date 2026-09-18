import { NextResponse } from 'next/server'

import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

/**
 * Set or change the password. A 409 `reauthentication_needed` means Supabase
 * emailed a code; the form resubmits with it as `nonce`.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ password?: unknown; current_password?: unknown; nonce?: unknown }>(
    request
  )
  if (isResponse(body)) return body
  if (typeof body.password !== 'string') {
    return NextResponse.json({ detail: 'Enter a new password.' }, { status: 400 })
  }
  return forward('/auth/account/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      password: body.password,
      current_password: typeof body.current_password === 'string' ? body.current_password : null,
      nonce: typeof body.nonce === 'string' && body.nonce ? body.nonce : null,
    }),
  })
}
