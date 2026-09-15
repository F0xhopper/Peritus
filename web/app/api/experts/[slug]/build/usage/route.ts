import { forward } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/** 404 until the latest job has metered some spend; the page renders that. */
export async function GET(_request: Request, { params }: Ctx) {
  const { slug } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/build/usage`)
}
