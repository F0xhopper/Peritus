import { OverviewPage } from '@/components/experts/overview-page'
import { getBuildStatus, getExpert, getExpertConversations } from '@/lib/api/data'
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

  const [conversations, status] = await Promise.all([
    getExpertConversations(slug),
    getBuildStatus(slug),
  ])

  return <OverviewPage expert={expert} conversations={conversations} buildStatus={status} />
}
