import { GraphView } from '@/components/graph/graph-view'
import { getExpert, getGraph } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Concepts — ${displayName(await getExpert(slug))}` }
}

/** The API's own bounds: `GRAPH_NODES_DEFAULT` / `GRAPH_NODES_MAX`. */
const DEFAULT_LIMIT = 400
const MAX_LIMIT = 1500

export default async function GraphPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ limit?: string }>
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams])
  const requested = Number(query.limit)
  const limit =
    Number.isInteger(requested) && requested >= 1 && requested <= MAX_LIMIT
      ? requested
      : DEFAULT_LIMIT

  const [expert, graph] = await Promise.all([getExpert(slug), getGraph(slug, limit)])
  return <GraphView expert={expert} graph={graph} limit={limit} />
}
