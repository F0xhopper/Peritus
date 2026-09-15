import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'

import { LoginCard } from '@/components/auth/login-card'
import { ACCESS_COOKIE, REFRESH_COOKIE } from '@/lib/auth/cookies'
import { safeNext } from '@/lib/auth/pkce'
import { proxyJson } from '@/lib/api/proxy'
import type { AuthStatus } from '@/lib/api/types'

export const metadata = { title: 'Sign in' }

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>
}) {
  const params = await searchParams
  const next = safeNext(params.next)

  // Already signed in and arriving at /login — usually the back button after a
  // sign-in. Go where they were heading rather than showing a form that would
  // do nothing.
  const jar = await cookies()
  if (jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value) redirect(next)

  // Asked once, server side: a deployment with no Supabase configured should
  // say so in the card rather than on the first submit.
  const status = await proxyJson<AuthStatus>('/auth/status', { anonymous: true }).catch(() => null)

  return (
    <LoginCard
      next={next}
      initialError={params.error ?? null}
      loginAvailable={status?.login_available ?? true}
      authEnabled={status?.auth_enabled ?? true}
    />
  )
}
