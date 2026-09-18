import { NextResponse } from 'next/server'

import { guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import { postForSession } from '@/lib/auth/respond'

/** A reset code and a new password → signed in, every other session revoked. */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const body = await jsonBody<{ email?: unknown; token?: unknown; password?: unknown }>(request)
  if (isResponse(body)) return body
  if (
    typeof body.email !== 'string' ||
    typeof body.token !== 'string' ||
    typeof body.password !== 'string'
  ) {
    return NextResponse.json({ detail: 'Enter the code and a new password.' }, { status: 400 })
  }
  return postForSession(request, '/auth/password/reset', {
    email: body.email.trim(),
    token: body.token.trim(),
    password: body.password,
  })
}
