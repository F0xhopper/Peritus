import { LedgerPage } from '@/components/ledger/ledger-page'
import { getCorpusReport, getExpert } from '@/lib/api/data'
import type { SourceDecision, SourceSort } from '@/lib/api/types'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Sources — ${displayName(await getExpert(slug))}` }
}

const DECISIONS = new Set<SourceDecision>(['all', 'accepted', 'rejected'])
const SORTS = new Set<SourceSort>([
  'decision',
  'quality',
  'relevance',
  'title',
  'type',
  'discovered_via',
  'added',
])

const PAGE_SIZE = 100

export default async function SourcesPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>
  searchParams: Promise<{
    decision?: string
    sort?: string
    page?: string
    concept?: string
    source?: string
  }>
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams])

  // Every query value is validated against the API's own vocabulary before it
  // is forwarded — an unrecognised `sort` would be a 422 from upstream, and a
  // URL someone edited by hand should fall back rather than break the page.
  const decision = DECISIONS.has(query.decision as SourceDecision)
    ? (query.decision as SourceDecision)
    : 'all'
  const sort = SORTS.has(query.sort as SourceSort) ? (query.sort as SourceSort) : 'decision'
  const page = Math.max(1, Number(query.page) || 1)

  const [expert, report] = await Promise.all([
    getExpert(slug),
    getCorpusReport(slug, {
      decision,
      sort,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    }),
  ])

  return (
    <LedgerPage
      expert={expert}
      report={report}
      decision={decision}
      sort={sort}
      page={page}
      pageSize={PAGE_SIZE}
      conceptFilter={query.concept ?? null}
      focusSourceId={Number(query.source) || null}
    />
  )
}
