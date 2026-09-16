'use client'

import { Users } from 'lucide-react'
import { ViewTransition } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { AvatarPicker } from '@/components/identity/avatar-picker'
import { PictureCredit } from '@/components/identity/picture-credit'
import { displayName, subtitle } from '@/lib/persona'
import type { ExpertWithCatalog } from '@/lib/api/types'

/**
 * The Overview's identity block: avatar, name, topic, credit.
 *
 * Two rules live here rather than in the page, because both are about *this*
 * region and both are easy to get subtly wrong:
 *
 * **The picture is credited only where it is actually what is shown.** An owner
 * who pinned a drawing is not using the picture, and crediting it under someone
 * else's tile would be a claim about the wrong image. `PictureCredit` drops out
 * on its own for public domain.
 *
 * **`persona_style` is not printed here.** It is a system-prompt instruction,
 * written to the model, so on real experts it rendered as an unlabelled command
 * addressed to someone else — *"You teach Aristotelian logic as a craft, not a
 * museum piece."* — directly under the name, and it was the line most likely to
 * be quoted when the page was shared. The bio says who this is in the third
 * person and is what the reader gets. A prose sentence written *about* the
 * expert's voice would belong here; until the builder writes one, nothing does.
 */
export function OverviewHeader({ expert, owner }: { expert: ExpertWithCatalog; owner: boolean }) {
  const name = displayName(expert)

  return (
    <header className="flex items-start gap-4">
      <ViewTransition name={`sigil-${expert.name}`}>
        <div>
          {owner ? (
            <AvatarPicker expert={expert}>
              <Avatar expert={expert} size={48} />
            </AvatarPicker>
          ) : (
            <Avatar expert={expert} size={48} />
          )}
        </div>
      </ViewTransition>
      <div className="min-w-0 flex-1">
        <h1 className="text-title font-medium text-fg">{name}</h1>
        {subtitle(expert) && <p className="mt-1 text-sm text-fg-2">{subtitle(expert)}</p>}
        {expert.picture && !expert.avatar && (
          <PictureCredit picture={expert.picture} className="mt-1.5" />
        )}
        {!owner && (
          <p className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-fg-3">
            <Users className="size-3" aria-hidden="true" />
            Shared with you — you can read and ask, not change it.
          </p>
        )}
      </div>
    </header>
  )
}
