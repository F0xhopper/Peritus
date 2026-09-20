import { forward } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string; id: string }>
}

export async function GET(_request: Request, { params }: Ctx) {
  const { slug, id } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/outline/works/${encodeURIComponent(id)}`)
}
