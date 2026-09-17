import { notFound } from 'next/navigation'

import { SourceReader } from '@/components/ledger/source-reader'
import { getExpert, getPassages } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string; id: string }>
}) {
  const { slug } = await params
  return { title: `Reading — ${displayName(await getExpert(slug))}` }
}

/**
 * A source's text, opened at the cited passage.
 *
 * A page rather than the panel: a whole book in a 50% sheet is not reading. The
 * API decides what may be reproduced — asking for the whole of a source we may
 * not returns the window around the passage instead, and says so in `scope`, so
 * this page renders whatever came back rather than promising the whole of
 * anything.
 */
export default async function ReadSourcePage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string; id: string }>
  searchParams: Promise<{ at?: string }>
}) {
  const [{ slug, id }, query] = await Promise.all([params, searchParams])
  const sourceId = Number(id)
  if (!Number.isInteger(sourceId)) notFound()

  const at = Number(query.at)
  const [expert, window] = await Promise.all([
    getExpert(slug),
    getPassages(slug, sourceId, {
      around: Number.isInteger(at) ? at : null,
      whole: true,
      // The fallback when the whole is not ours to show: enough either side of
      // the citation to read it in context, which is the panel's window twice
      // over rather than a teaser.
      before: 4,
      after: 4,
    }),
  ])

  return <SourceReader expert={expert} window={window} />
}
