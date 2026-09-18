import 'server-only'

import { NextResponse } from 'next/server'

import { errorResponse } from '@/lib/api/route'
import { callApi, throwForStatus } from '@/lib/api/server'
import { clearedSessionCookies, sessionCookies } from '@/lib/auth/cookies'
import type { Session } from '@/lib/api/types'

/**
 * A JSON response that also signs the browser in.
 *
 * Every flow that ends in a session — a code, a password, a reset, a confirmed
 * sign-up, a completed email change — ends here, so there is one place where
 * the tokens become httpOnly cookies and one rule about the body: it carries
 * the user and never a token.
 */
export function signedIn(session: Session, body: Record<string, unknown> = {}): NextResponse {
  const response = NextResponse.json({ ...body, user: session.user })
  for (const cookie of sessionCookies(session)) response.cookies.set(cookie)
  return response
}

/** A JSON response that signs the browser out. Both cookies, always. */
export function signedOut(body: Record<string, unknown> = { ok: true }): NextResponse {
  const response = NextResponse.json(body)
  for (const cookie of clearedSessionCookies()) response.cookies.set(cookie)
  return response
}

/**
 * POST `payload` to an anonymous API auth endpoint that answers with a session,
 * and sign the browser in with it. Errors pass through with their status,
 * `Retry-After` and coded `detail` intact — the form decides what they mean.
 */
export async function postForSession(
  request: Request,
  path: string,
  payload: unknown
): Promise<NextResponse> {
  try {
    const res = await callApi(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...clientAgent(request) },
      body: JSON.stringify(payload),
    })
    if (!res.ok) await throwForStatus(res)
    return signedIn((await res.json()) as Session)
  } catch (error) {
    return errorResponse(error)
  }
}

/**
 * The browser's own User-Agent, for a call that creates a session.
 *
 * Supabase labels a session with the agent of the request that created it, and
 * that request comes from here — so without this, every device in Settings
 * would read as this server.
 */
export function clientAgent(request: Request): Record<string, string> {
  const agent = request.headers.get('user-agent')
  return agent ? { 'User-Agent': agent } : {}
}
