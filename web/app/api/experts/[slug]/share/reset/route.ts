import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** Replace the link with a new one; the old one stops working for everyone. */
export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/share/reset`, { method: 'POST' })
}
