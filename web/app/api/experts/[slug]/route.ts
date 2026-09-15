import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function GET(_request: Request, { params }: Ctx) {
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}`)
}

export async function DELETE(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}
