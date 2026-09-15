import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/build/cancel`, { method: 'POST' })
}
