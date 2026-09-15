import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** The owner's view of the share link. 404 for anyone but the owner. */
export async function GET(_request: Request, { params }: Ctx) {
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/share`)
}

/** Turn the link on. Idempotent: a live link is returned, never replaced. */
export async function PUT(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/share`, { method: 'PUT' })
}

/** Turn the link off. Everyone who opened it loses access. */
export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/share`, { method: 'DELETE' })
}
