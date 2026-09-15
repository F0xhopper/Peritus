import { forward, pickParams, query } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ slug: string }>
}

/**
 * The ledger. Upstream is `corpus-report`, which is the audit surface and
 * carries the rejected half, the totals and the provenance block — not
 * `GET /experts/{slug}/sources`, which is only the owner's management list.
 */
export async function GET(request: Request, { params }: Ctx) {
  const { slug } = await params
  const q = query(pickParams(request.url, ['decision', 'sort', 'limit', 'offset']))
  return forward(`/experts/${encodeURIComponent(slug)}/corpus-report${q}`)
}
