import { redirect } from 'next/navigation'

import { GRAPH_LIMIT_DEFAULT, parseGraphLimit } from '@/lib/graph/limits'

/**
 * The concept graph is the Graph view of the Knowledge page. It was folded into
 * the Map for a while (docs/plans/expert-brain.md) and this redirect sent every
 * old link there, dropping `?limit=`; the graph is back as its own view, so an
 * old link leads to what it always meant, at the size it asked for.
 */
export default async function GraphRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ limit?: string }>
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams])
  const limit = parseGraphLimit(query.limit)
  const suffix = limit === GRAPH_LIMIT_DEFAULT ? '' : `&limit=${limit}`
  redirect(`/experts/${encodeURIComponent(slug)}/knowledge?view=graph${suffix}`)
}
