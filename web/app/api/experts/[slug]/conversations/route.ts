import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function GET(_request: Request, { params }: Ctx) {
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/conversations`)
}

/** Create an empty conversation. 409 when the expert cannot answer yet. */
export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/conversations`, { method: 'POST' })
}
