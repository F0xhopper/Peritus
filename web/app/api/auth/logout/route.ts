import { guardOrigin } from '@/lib/api/route'
import { proxyVoid } from '@/lib/api/proxy'
import { signedOut } from '@/lib/auth/respond'
import { NextResponse } from 'next/server'

/**
 * Sign out: `?scope=local` (this device), `global` (every device, the default)
 * or `others` (every device but this one — which keeps the cookies).
 *
 * The upstream revoke is best-effort; for `local` and `global` the cookies are
 * cleared either way. A failed revoke must never leave a user looking signed
 * in — an expired token is already un-revokable, and the API treats that as
 * success.
 */
const SCOPES = new Set(['local', 'global', 'others'])

export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked

  const raw = new URL(request.url).searchParams.get('scope') ?? 'global'
  const scope = SCOPES.has(raw) ? raw : 'global'

  if (scope === 'others') {
    // Nothing local changes, so a failure here is worth reporting.
    try {
      await proxyVoid('/auth/logout?scope=others', { method: 'POST' })
      return NextResponse.json({ ok: true })
    } catch {
      return NextResponse.json(
        { detail: 'Could not sign out your other devices. Try again.' },
        { status: 502 }
      )
    }
  }

  try {
    await proxyVoid(`/auth/logout?scope=${scope}`, { method: 'POST' })
  } catch {
    /* already signed out, or the auth server is unreachable */
  }
  return signedOut()
}
