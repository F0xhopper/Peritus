import { forward, guardOrigin } from '@/lib/api/route'

/** Sign one other device out. */
export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { id } = await params
  return forward(`/auth/account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
