import { forward, guardOrigin } from '@/lib/api/route'

/** Remove a sign-in method. The API refuses the last one. */
export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { id } = await params
  return forward(`/auth/account/identities/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
