import { Lock, MessageSquare } from 'lucide-react'
import Link from 'next/link'

import { Avatar } from '@/components/identity/avatar'
import { PictureCredit } from '@/components/identity/picture-credit'
import { OpenSharedExpert } from '@/components/share/open-shared-expert'
import { sharedPictureUrl, sharePath } from '@/lib/access'
import { humanise, plural } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import { sourceKind } from '@/lib/source-kind'
import type { SharedExpert } from '@/lib/api/types'

/**
 * The share page's one card: what this expert is, what it is built from, and
 * the single thing to do next.
 *
 * The call to action depends only on whether there is a session. Signed in, it
 * opens the expert (recording that this person opened the link); signed out, it
 * is sign-in, which returns here. It never says who shared the link — the API
 * does not send that, and a link forwarded twice would make it wrong anyway.
 */
export function SharedExpertCard({
  token,
  expert,
  signedIn,
}: {
  token: string
  expert: SharedExpert
  signedIn: boolean
}) {
  const name = displayName(expert)
  const about = subtitle(expert)
  const answerable = expert.readiness !== 'pending'
  const kinds = kindCounts(expert.source_type_counts)
  const shownAvatar = expert.avatar === null && expert.picture !== null

  return (
    <article className="mx-auto w-full max-w-[680px] px-4 pt-10 pb-16 md:px-6">
      <p className="text-xs text-fg-3">Shared with you on Peritus</p>

      <header className="mt-3 flex items-start gap-4">
        <Avatar
          expert={expert}
          size={56}
          eager
          pictureSrc={expert.picture ? sharedPictureUrl(token, expert.picture.version) : undefined}
        />
        <div className="min-w-0 flex-1">
          <h1 className="text-title font-medium text-fg">{name}</h1>
          {about && <p className="mt-1 text-sm text-fg-2">{about}</p>}
          {shownAvatar && expert.picture && (
            <PictureCredit picture={expert.picture} className="mt-1.5" />
          )}
        </div>
      </header>

      {expert.persona_bio && (
        <p className="mt-5 text-base leading-relaxed text-fg-2">{expert.persona_bio}</p>
      )}

      <dl className="mt-6 grid grid-cols-1 gap-x-6 gap-y-2 text-sm min-[480px]:grid-cols-[auto_1fr]">
        <Property label="Depth">{humanise(expert.tier)}</Property>
        <Property label="Sources">{plural(expert.source_count, 'source')}</Property>
        <Property label="Passages">{expert.chunk_count}</Property>
        {expert.node_count > 0 && <Property label="Concepts">{expert.node_count}</Property>}
      </dl>

      {expert.key_concepts.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-fg">Key concepts</h2>
          <p className="mt-2 leading-relaxed text-fg-2">
            {expert.key_concepts.map((concept, index) => (
              <span key={concept}>
                {index > 0 && <span className="text-fg-3"> · </span>}
                {concept}
              </span>
            ))}
          </p>
        </section>
      )}

      {kinds.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-medium text-fg">Kinds of source</h2>
          <p className="mt-2 leading-relaxed">
            {kinds.map(([kind, count], index) => (
              <span key={kind}>
                {index > 0 && <span className="text-fg-3"> · </span>}
                <span className="text-fg-2">{kind}</span> <span className="text-fg-3">{count}</span>
              </span>
            ))}
          </p>
        </section>
      )}

      <section className="mt-10 rounded-card bg-panel p-4">
        <h2 className="flex items-center gap-2 text-base font-medium text-fg">
          <MessageSquare className="size-4 text-fg-3" aria-hidden="true" />
          {answerable ? `Ask ${name}` : `${name} is still being built`}
        </h2>
        <p className="mt-1 text-sm text-fg-3">
          {answerable
            ? 'Every answer cites the passages it is built from, and you can open each source.'
            : 'You can open it now and watch; it answers as soon as its sources are indexed.'}
        </p>
        <div className="mt-3">
          {signedIn ? (
            <OpenSharedExpert token={token} />
          ) : (
            <Link
              href={`/login?next=${encodeURIComponent(sharePath(token))}`}
              className="inline-flex h-(--btn-lg) items-center rounded-row bg-accent px-4 text-sm font-medium text-accent-fg transition-opacity duration-(--dur-1) hover:opacity-90"
            >
              Sign in to open it
            </Link>
          )}
        </div>
        <p className="mt-3 flex items-start gap-1.5 text-xs text-fg-3">
          <Lock className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          Your questions are private. The person who shared this cannot see your chats.
        </p>
      </section>
    </article>
  )
}

function Property({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-fg-3 min-[480px]:text-right">{label}</dt>
      <dd className="min-w-0 text-fg-2">{children}</dd>
    </div>
  )
}

function kindCounts(counts: Record<string, number>): [string, number][] {
  const merged = new Map<string, number>()
  for (const [type, count] of Object.entries(counts)) {
    const kind = sourceKind(type)
    merged.set(kind, (merged.get(kind) ?? 0) + count)
  }
  return [...merged.entries()].sort((a, b) => b[1] - a[1])
}
