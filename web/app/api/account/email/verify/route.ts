import { NextResponse } from 'next/server'

import { errorResponse, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { proxyFetch } from '@/lib/api/proxy'
import { throwForStatus } from '@/lib/api/server'
import { clientAgent, signedIn } from '@/lib/auth/respond'
import type { EmailChangeResult } from '@/lib/api/types'

/**
 * Enter a code from an email change. When the change completes, GoTrue issues a
 * session carrying the new address, and it replaces the cookies here — the old
 * access token still says the old email until it expires.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ email?: unknown; token?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || typeof body.token !== 'string') {
    return NextResponse.json({ detail: 'Enter the code.' }, { status: 400 })
  }
  try {
    const res = await proxyFetch('/auth/account/email/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...clientAgent(request) },
      body: JSON.stringify({ email: body.email.trim(), token: body.token.trim() }),
    })
    if (!res.ok) await throwForStatus(res)
    const result = (await res.json()) as EmailChangeResult
    if (result.complete && result.session) return signedIn(result.session, { complete: true })
    return NextResponse.json({ complete: false, message: result.message })
  } catch (error) {
    return errorResponse(error)
  }
}
