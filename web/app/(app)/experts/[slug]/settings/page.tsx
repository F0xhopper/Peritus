import { notFound } from 'next/navigation'

import { ExpertSettingsPage } from '@/components/settings/expert-settings-page'
import { canManage } from '@/lib/access'
import { getBilling, getExpert, getShareState } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Settings — ${displayName(await getExpert(slug))}` }
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const expert = await getExpert(slug)
  // Every control on this page changes the expert. A viewer has none of them,
  // so for them the page does not exist — the same 404 the API would give.
  if (!canManage(expert)) notFound()

  const [credits, share] = await Promise.all([
    getBilling(`/experts/${slug}/settings`).catch(() => null),
    getShareState(slug).catch(() => null),
  ])

  return (
    <ExpertSettingsPage
      expert={expert}
      share={share}
      tiers={credits?.tiers ?? []}
      allowedTiers={credits?.plan.allowed_tiers ?? null}
      creditsEnforced={credits?.credits_enforced === true}
      balance={credits?.balance ?? null}
    />
  )
}
