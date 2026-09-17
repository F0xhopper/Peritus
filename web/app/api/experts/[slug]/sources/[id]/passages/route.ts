import { forward, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string; id: string }>
}

/**
 * The text around a cited passage — what the expert read, either side of the
 * chunk a citation points at.
 *
 * Read-scoped upstream, like the corpus report: a share grant that lets someone
 * chat has to let them read what the chat cites. `whole` is a request rather
 * than an instruction; the API decides what it may reproduce and says which in
 * `scope`.
 */
export async function GET(request: Request, { params }: Ctx) {
  const { slug, id } = await params
  const q = query(pickParams(request.url, ['around', 'before', 'after', 'whole']))
  return forward(
    `/experts/${encodeURIComponent(slug)}/sources/${encodeURIComponent(id)}/passages${q}`
  )
}
