import { forward } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

export async function GET(_request: Request, { params }: Ctx) {
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/build/status`)
}
