import { ExpertSettingsPage } from '@/components/settings/expert-settings-page'
import { getBilling, getExpert } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Settings — ${displayName(await getExpert(slug))}` }
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const [expert, credits] = await Promise.all([
    getExpert(slug),
    getBilling(`/experts/${slug}/settings`).catch(() => null),
  ])

  return (
    <ExpertSettingsPage
      expert={expert}
      tiers={credits?.tiers ?? []}
      allowedTiers={credits?.plan.allowed_tiers ?? null}
      creditsEnforced={credits?.credits_enforced === true}
      balance={credits?.balance ?? null}
    />
  )
}
