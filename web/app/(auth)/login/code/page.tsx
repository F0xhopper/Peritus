import { CodeLoginForm } from '@/components/auth/code-login-form'
import { safeNext } from '@/lib/auth/pkce'
import { authStatus, redirectIfSignedIn } from '@/lib/auth/page'

export const metadata = { title: 'Sign in with a code' }

export default async function CodeLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; email?: string }>
}) {
  const params = await searchParams
  const next = safeNext(params.next)
  await redirectIfSignedIn(next)
  const { authEnabled } = await authStatus()

  return (
    <CodeLoginForm
      next={next}
      initialEmail={params.email?.trim() ?? ''}
      authEnabled={authEnabled}
    />
  )
}
