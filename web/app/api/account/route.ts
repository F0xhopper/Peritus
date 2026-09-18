import { NextResponse } from 'next/server'

import { errorResponse, forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { proxyFetch } from '@/lib/api/proxy'
import { throwForStatus } from '@/lib/api/server'
import { signedOut } from '@/lib/auth/respond'

/** The signed-in person's account. */
export async function GET() {
  return forward('/auth/account')
}

/** Rename. */
export async function PATCH(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ name?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.name !== 'string') {
    return NextResponse.json({ detail: 'Enter a name.' }, { status: 400 })
  }
  return forward('/auth/account', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: body.name }),
  })
}

/**
 * Delete the account. On success the session cookies go on the same response:
 * the tokens now name a user who does not exist.
 */
export async function DELETE(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<{ confirm_email?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.confirm_email !== 'string') {
    return NextResponse.json({ detail: 'Type your email address to confirm.' }, { status: 400 })
  }
  try {
    const res = await proxyFetch('/auth/account', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_email: body.confirm_email }),
    })
    if (!res.ok) await throwForStatus(res)
    return signedOut((await res.json()) as Record<string, unknown>)
  } catch (error) {
    return errorResponse(error)
  }
}
