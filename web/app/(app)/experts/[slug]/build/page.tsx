import { BuildView } from '@/components/build/build-view'
import { getBilling, getBuildStatus, getExpert } from '@/lib/api/data'
import { displayName } from '@/lib/persona'

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  return { title: `Build log — ${displayName(await getExpert(slug))}` }
}

export default async function BuildPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const [expert, status, billing] = await Promise.all([
    getExpert(slug),
    getBuildStatus(slug),
    getBilling().catch(() => null),
  ])
  // What this tier costs in credits, where credits are in force.
  const creditCost = billing?.credits_enforced
    ? (billing.tiers.find((tier) => tier.tier === expert.tier)?.credit_cost ?? null)
    : null

  // The composer appends `?from=<seq>` after reading the `created` event off
  // the POST response, but nothing here needs it: the log is durable and the
  // page replays it from seq 0, so the reducer sees the same events either way.
  return <BuildView expert={expert} status={status} creditCost={creditCost} />
}
