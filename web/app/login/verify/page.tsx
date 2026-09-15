import { redirect } from 'next/navigation'

import { VerifyCard } from '@/components/auth/verify-card'
import { safeNext } from '@/lib/auth/pkce'

export const metadata = { title: 'Enter your code' }

export default async function VerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string; next?: string }>
}) {
  const params = await searchParams
  const email = params.email?.trim()
  // Landing here without an email means a refresh after clearing the URL, or a
  // pasted link. There is nothing to verify against, so start over.
  if (!email) redirect('/login')

  return <VerifyCard email={email} next={safeNext(params.next)} />
}
