import { NextResponse } from 'next/server'

import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'

/** Start moving the account to a new address; a code goes to it. */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ email?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || !body.email.trim()) {
    return NextResponse.json({ detail: 'Enter the new email address.' }, { status: 400 })
  }
  return forward('/auth/account/email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: body.email.trim() }),
  })
}
