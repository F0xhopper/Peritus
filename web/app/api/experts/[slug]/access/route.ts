import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** A viewer removes a shared expert from their workspace. 409 for its owner. */
export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/access`, { method: 'DELETE' })
}
