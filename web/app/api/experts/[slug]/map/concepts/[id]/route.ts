import { forward } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string; id: string }>
}

/**
 * One concept of the map: its sources, its claims and their relations.
 *
 * Fetched when a concept is opened rather than with the map — claims are the
 * only heavy part of the map, and only one concept is ever open.
 */
export async function GET(_request: Request, { params }: Ctx) {
  const { slug, id } = await params
  return forward(`/experts/${encodeURIComponent(slug)}/map/concepts/${encodeURIComponent(id)}`)
}
