import { NextResponse } from 'next/server'

import { errorResponse, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { callApi, throwForStatus } from '@/lib/api/server'
import { clientAgent, signedIn } from '@/lib/auth/respond'
import type { SignupResult } from '@/lib/api/types'

/**
 * Create a password account.
 *
 * Usually answers `{confirmation_required: true}` and the form moves on to the
 * code page. When the Supabase project auto-confirms, the API returns a session
 * instead, and this signs the browser in on the spot. Either way the body
 * carries no token.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown; password?: unknown; name?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || typeof body.password !== 'string') {
    return NextResponse.json({ detail: 'Enter your email and a password.' }, { status: 400 })
  }

  try {
    const res = await callApi('/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...clientAgent(request) },
      body: JSON.stringify({
        email: body.email.trim(),
        password: body.password,
        name: typeof body.name === 'string' && body.name.trim() ? body.name.trim() : null,
      }),
    })
    if (!res.ok) await throwForStatus(res)
    const result = (await res.json()) as SignupResult
    if (result.session) return signedIn(result.session, { confirmation_required: false })
    return NextResponse.json({ confirmation_required: true }, { status: 202 })
  } catch (error) {
    return errorResponse(error)
  }
}
