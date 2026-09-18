import { SignupForm } from '@/components/auth/signup-form'
import { safeNext } from '@/lib/auth/pkce'
import { authStatus, redirectIfSignedIn } from '@/lib/auth/page'

export const metadata = { title: 'Create an account' }

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>
}) {
  const params = await searchParams
  const next = safeNext(params.next)
  await redirectIfSignedIn(next)
  const status = await authStatus()

  return <SignupForm next={next} initialError={params.error ?? null} {...status} />
}
