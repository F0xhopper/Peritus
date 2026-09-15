import { forward, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['limit']))
  return forward(`/experts/${encodeURIComponent(slug)}/graph${q}`)
}
