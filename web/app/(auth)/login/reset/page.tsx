import { redirect } from 'next/navigation'

import { ResetForm } from '@/components/auth/reset-form'
import { safeNext } from '@/lib/auth/pkce'

export const metadata = { title: 'Choose a new password' }

export default async function ResetPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; email?: string }>
}) {
  const params = await searchParams
  const email = params.email?.trim()
  if (!email) redirect('/login/forgot')
  return <ResetForm email={email} next={safeNext(params.next)} />
}
