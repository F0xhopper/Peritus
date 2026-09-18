import 'server-only'

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { proxyJson } from '@/lib/api/proxy'
import type { AuthStatus } from '@/lib/api/types'
import { ACCESS_COOKIE, REFRESH_COOKIE } from '@/lib/auth/cookies'

/**
 * Already signed in and arriving at a sign-in page — usually the back button
 * after signing in. Go where they were heading rather than showing a form that
 * would do nothing.
 */
export async function redirectIfSignedIn(next: string): Promise<void> {
  const jar = await cookies()
  if (jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value) redirect(next)
}

/**
 * Asked once, server side: a deployment with no Supabase configured should say
 * so in the card rather than on the first submit.
 */
export async function authStatus(): Promise<{ loginAvailable: boolean; authEnabled: boolean }> {
  const status = await proxyJson<AuthStatus>('/auth/status', { anonymous: true }).catch(() => null)
  return {
    loginAvailable: status?.login_available ?? true,
    authEnabled: status?.auth_enabled ?? true,
  }
}
