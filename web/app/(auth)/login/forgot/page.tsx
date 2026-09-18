import { ForgotForm } from '@/components/auth/forgot-form'
import { safeNext } from '@/lib/auth/pkce'

export const metadata = { title: 'Reset your password' }

export default async function ForgotPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; email?: string }>
}) {
  const params = await searchParams
  return <ForgotForm next={safeNext(params.next)} initialEmail={params.email?.trim() ?? ''} />
}
