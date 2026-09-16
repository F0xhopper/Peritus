'use client'

import { RotateCcw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { AvatarPicker } from '@/components/identity/avatar-picker'
import { PictureCredit } from '@/components/identity/picture-credit'
import { ConfirmDelete } from '@/components/experts/confirm-delete'
import { DenialNotice } from '@/components/experts/denial-notice'
import { SharePanel } from '@/components/experts/share-panel'
import { CostLine, TierPicker, type TierChoice } from '@/components/experts/tier-picker'
import { TopBar } from '@/components/shell/top-bar'
import { Button } from '@/components/ui/button'
import { Notice } from '@/components/ui/notice'
import { useStartBuild } from '@/hooks/use-start-build'
import { displayName } from '@/lib/persona'
import type { ExpertTier, ExpertWithCatalog, ShareState, TierPrice } from '@/lib/api/types'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'

/**
 * Managing one expert: re-skin, share, rebuild, delete. Owner only — the route
 * 404s a viewer before this renders.
 *
 * A rebuild goes through the same `POST /experts/build` the composer uses —
 * with the **topic**, not the slug, because the server resolves the slug from
 * the topic and finds the caller's existing expert on it. That is how a rebuild
 * and a first build stay one code path.
 *
 * The warning is not boilerplate: a rebuild resets the corpus. Sources,
 * passages and the graph are deleted and rebuilt clean, uploads excepted, and
 * it costs credits again.
 */
export function ExpertSettingsPage({
  expert,
  share,
  tiers,
  allowedTiers,
  creditsEnforced,
  balance,
}: {
  expert: ExpertWithCatalog
  /** Null when it could not be loaded; the panel fetches it again itself. */
  share: ShareState | null
  tiers: TierPrice[]
  allowedTiers: ExpertTier[] | null
  creditsEnforced: boolean
  balance: number | null
}) {
  const router = useRouter()
  const [tier, setTier] = useState<TierChoice>(expert.tier)
  const [confirming, setConfirming] = useState(false)
  const { start, submitting, denial, error } = useStartBuild()

  // `useApiAction` refreshes after a success, which is what the rail, the
  // sidebar and the recent-chats list need: they are the `(app)` layout's own
  // data and a push reuses the cached layout, so without it the expert just
  // deleted stays in the rail until a hard reload.
  const { run: remove, pending: deleting } = useApiAction(
    () =>
      apiVoid(
        `/api/experts/${encodeURIComponent(expert.name)}`,
        { method: 'DELETE' },
        'Could not delete that expert.'
      ),
    {
      success: `Deleted ${displayName(expert)}`,
      error: 'Could not delete that expert.',
      onSuccess: () => router.push('/experts'),
    }
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar expert={expert} title="Settings" />

      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <h1 className="text-title font-medium text-fg">Settings</h1>
          <p className="mt-1 text-sm text-fg-3">{displayName(expert)}</p>

          <section className="mt-8">
            <h2 className="text-lg font-medium text-fg">Avatar</h2>
            <p className="mt-1 text-sm text-fg-3">
              A found, licensed picture of the subject, or a drawing generated from a style and a
              seed. Nothing is ever uploaded.
            </p>
            <div className="mt-3 flex items-center gap-3">
              <AvatarPicker expert={expert}>
                <Avatar expert={expert} size={48} />
              </AvatarPicker>
              <div className="min-w-0">
                <p className="text-xs text-fg-3">
                  {expert.avatar
                    ? `Pinned — style "${expert.avatar.style}".`
                    : expert.picture
                      ? 'Showing the picture found for this subject. Pinning a drawing overrides it; Reset brings it back.'
                      : 'Derived from the persona name, so a rebuild that renames this expert changes it.'}
                </p>
                {expert.picture && !expert.avatar && (
                  <PictureCredit picture={expert.picture} className="mt-1" />
                )}
              </div>
            </div>
          </section>

          <section id="sharing" className="mt-10 scroll-mt-16">
            <h2 className="text-lg font-medium text-fg">Sharing</h2>
            <p className="mt-1 text-sm text-fg-3">
              Private unless you create a link. Only people with the link can open it.
            </p>
            <div className="mt-3">
              <SharePanel
                slug={expert.name}
                name={displayName(expert)}
                initial={share ?? undefined}
              />
            </div>
          </section>

          <section className="mt-10">
            <h2 className="text-lg font-medium text-fg">Rebuild</h2>
            <p className="mt-1 text-sm text-fg-3">Search again from scratch at a chosen depth.</p>

            <Notice tone="warn" className="mt-3" title="A rebuild starts over from scratch">
              Every discovered source, passage and concept is deleted and rebuilt. Sources you
              uploaded yourself survive. It costs credits again, and the expert cannot answer until
              its new passages are indexed.
            </Notice>

            <TierPicker
              tiers={tiers}
              allowedTiers={allowedTiers}
              value={tier}
              onChange={setTier}
              creditsEnforced={creditsEnforced}
              balance={balance}
              className="mt-4 lg:grid-cols-2"
            />

            {denial && <DenialNotice denial={denial} className="mt-4" />}
            {error && (
              <Notice tone="bad" className="mt-4">
                {error}
              </Notice>
            )}

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <CostLine
                tier={tier}
                tiers={tiers}
                balance={balance}
                creditsEnforced={creditsEnforced}
              />
              <Button
                variant="primary"
                size="lg"
                loading={submitting}
                minWidth={124}
                // The topic, not the slug: the server resolves the slug from it
                // and finds this expert, which is what makes it a rebuild.
                onClick={() => void start(expert.topic, tier)}
              >
                <RotateCcw className="size-3.5" />
                Rebuild
              </Button>
            </div>
          </section>

          <section className="mt-12 border-t border-border-soft pt-6">
            <h2 className="text-lg font-medium text-bad">Danger zone</h2>
            <p className="mt-1 text-sm text-fg-3">
              Deleting an expert removes its whole record of sources — every one it kept and every
              one it dropped — along with its passages, its concept map and its chats. It cannot be
              undone.
            </p>
            <Button variant="danger" size="md" className="mt-3" onClick={() => setConfirming(true)}>
              Delete {displayName(expert)}
            </Button>
          </section>
        </div>
      </div>

      <ConfirmDelete
        expert={expert}
        open={confirming}
        onOpenChange={setConfirming}
        onConfirm={remove}
        deleting={deleting}
      />
    </div>
  )
}
