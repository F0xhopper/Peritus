import { NewExpertForm } from '@/components/experts/new-expert-form'
import { TopBar } from '@/components/shell/top-bar'
import { getBilling } from '@/lib/api/data'

export const metadata = { title: 'New expert' }

export default async function NewExpertPage({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string }>
}) {
  const [credits, params] = await Promise.all([
    getBilling('/experts/new').catch(() => null),
    searchParams,
  ])

  return (
    <>
      <TopBar title="New expert" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-4 pb-10 md:px-6">
          <h1 className="text-title font-medium text-fg">New expert</h1>
          <p className="mt-1 text-sm text-fg-3">
            Name a subject. Peritus plans a search, screens what it finds, and keeps a record of
            every source it accepted and rejected.
          </p>

          <NewExpertForm
            initialTopic={params.topic ?? ''}
            tiers={credits?.tiers ?? []}
            allowedTiers={credits?.plan.allowed_tiers ?? null}
            creditsEnforced={credits?.credits_enforced === true}
            balance={credits?.balance ?? null}
          />
        </div>
      </div>
    </>
  )
}
