import { NextResponse } from 'next/server'

import { guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { postForSession } from '@/lib/auth/respond'

/**
 * Sign in with a password. A 403 `email_not_confirmed` means the password was
 * right and the address is not yet confirmed; the form routes to the code page,
 * and the API has already sent a fresh code.
 */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown; password?: unknown }>(request)
  if (isResponse(body)) return body
  if (typeof body.email !== 'string' || typeof body.password !== 'string' || !body.password) {
    return NextResponse.json({ detail: 'Enter your email and password.' }, { status: 400 })
  }
  return postForSession(request, '/auth/password/login', {
    email: body.email.trim(),
    password: body.password,
  })
}
