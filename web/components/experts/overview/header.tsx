'use client'

import { Users } from 'lucide-react'
import { ViewTransition } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { AvatarPicker } from '@/components/identity/avatar-picker'
import { PictureCredit } from '@/components/identity/picture-credit'
import { firstSentence } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import type { ExpertWithCatalog } from '@/lib/api/types'

/**
 * The Overview's identity block: avatar, name, topic, voice, credit.
 *
 * Two rules live here rather than in the page, because both are about *this*
 * region and both are easy to get subtly wrong:
 *
 * **The picture is credited only where it is actually what is shown.** An owner
 * who pinned a drawing is not using the picture, and crediting it under someone
 * else's tile would be a claim about the wrong image. `PictureCredit` drops out
 * on its own for public domain.
 *
 * **The voice is shown whole, one sentence of it.** The builder sometimes
 * writes a paragraph, and clamping cut a sentence off mid-clause; the full text
 * is on the `title` for anyone curious.
 */
export function OverviewHeader({ expert, owner }: { expert: ExpertWithCatalog; owner: boolean }) {
  const name = displayName(expert)
  const voice = firstSentence(expert.persona_style)

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
        {voice && (
          <p title={expert.persona_style ?? undefined} className="mt-1 text-sm text-fg-3 italic">
            {voice}
          </p>
        )}
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
