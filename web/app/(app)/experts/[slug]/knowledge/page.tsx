import { KnowledgePage } from '@/components/knowledge/knowledge-page'
import { getCorpusReport, getExpert, getExpertMap } from '@/lib/api/data'
import type { SourceSort } from '@/lib/api/types'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Knowledge — ${displayName(await getExpert(slug))}` }
}

const SORTS = new Set<SourceSort>(['title', 'type', 'added'])

const PAGE_SIZE = 100

/** The API's own bound on `?expand=` (`MAP_EXPAND_MAX`). */
const EXPAND_MAX = 31

/**
 * One expert's knowledge: the Map and the List of the same selection
 * (docs/plans/expert-brain.md). Only what the server fetches is read here —
 * sort, page and an expanded sector. The view and the selection are the
 * client's, and change without a round trip.
 */
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{ sort?: string; page?: string; expand?: string }>
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams])

  // Every value is checked against the API's own vocabulary before it is
  // forwarded: a URL someone edited by hand should fall back, not 422.
  const sort = SORTS.has(query.sort as SourceSort) ? (query.sort as SourceSort) : 'title'
  const page = Math.max(1, Number(query.page) || 1)
  const requested = Number(query.expand)
  const expand =
    query.expand !== undefined &&
    Number.isInteger(requested) &&
    requested >= 0 &&
    requested <= EXPAND_MAX
      ? requested
      : null

  const [expert, report, map] = await Promise.all([
    getExpert(slug),
    // The sources this expert answers from; the API still holds the rest of
    // the screening record.
    getCorpusReport(slug, {
      decision: 'accepted',
      sort,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
    getExpertMap(slug, expand),
  ])

  return (
    <KnowledgePage
      expert={expert}
      report={report}
      map={map}
      sort={sort}
      page={page}
      pageSize={PAGE_SIZE}
      expand={expand}
    />
  )
}
