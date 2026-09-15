import { notFound } from 'next/navigation'

import { AdminPage } from '@/components/settings/admin-page'
import { getMe } from '@/lib/api/data'

export const metadata = { title: 'Admin', robots: { index: false, follow: false } }

export default async function Page() {
  const me = await getMe('/admin')
  // 404, not 403 — the same convention the API uses for everything out of
  // scope. A 403 would confirm the page exists to anyone who guessed the URL.
  if (!me.is_admin) notFound()
  return <AdminPage me={me} />
}
