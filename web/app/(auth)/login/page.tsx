import { LoginForm } from '@/components/auth/login-form'
import { safeNext } from '@/lib/auth/pkce'
import { authStatus, redirectIfSignedIn } from '@/lib/auth/page'

export const metadata = { title: 'Sign in' }

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>
}) {
  const params = await searchParams
  const next = safeNext(params.next)
  await redirectIfSignedIn(next)
  const status = await authStatus()

  return <LoginForm next={next} initialError={params.error ?? null} {...status} />
}
