import { forward, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** The expert's map — syllabus, shared concepts and sources in one payload. */
export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['expand']))
  return forward(`/experts/${encodeURIComponent(slug)}/map${q}`)
}
