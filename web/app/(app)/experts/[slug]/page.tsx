import { OverviewPage } from '@/components/experts/overview-page'
import { getBuildStatus, getCorpusReport, getExpert, getExpertConversations } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const expert = await getExpert(slug)
  return {
    title: displayName(expert),
    description: expert.persona_bio ?? expert.topic,
  }
}

export default async function ExpertOverview({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const expert = await getExpert(slug)

  const [conversations, status, report] = await Promise.all([
    getExpertConversations(slug),
    getBuildStatus(slug),
    // The corpus report carries the method statement, the acceptance rate and
    // the rubric version — everything the "how this corpus was assembled"
    // section states. One row is enough; the page never lists sources.
    getCorpusReport(slug, { limit: 1 }).catch(() => null),
  ])

  return (
    <OverviewPage
      expert={expert}
      conversations={conversations}
      buildStatus={status}
      report={report}
    />
  )
}
