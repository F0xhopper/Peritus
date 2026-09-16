import type { Metadata } from 'next'
import { notFound } from 'next/navigation'

import { SharedExpertCard } from '@/components/share/shared-expert-card'
import { getSharedExpert, hasSession } from '@/lib/api/data'
import { appUrl } from '@/lib/api/server'
import { sharedPictureUrl } from '@/lib/access'
import { displayName, subtitle } from '@/lib/persona'

/**
 * What someone sees when they open a share link.
 *
 * Public, because a link has to make sense to whoever it is sent to before they
 * have an account — and because the chat app it is pasted into fetches it,
 * signed out, to draw the preview. It shows what the expert is and nothing
 * about who shared it; opening the expert itself needs a session.
 *
 * Never indexed, and the page sends no referrer: the token *is* the access, so
 * it must not end up in a search index or in the logs of a site linked from
 * here. (`next.config.ts` sets the same two headers for every `/share/*`
 * response, so they hold on the 404 as well.)
 */

type Props = { params: Promise<{ token: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { token } = await params
  const expert = await getSharedExpert(token)
  const robots = { index: false, follow: false }
  if (!expert) return { title: 'This link is not active', robots, referrer: 'no-referrer' }

  const name = displayName(expert)
  const about = subtitle(expert)
  const title = about ? `${name} — ${about}` : name
  const description =
    expert.persona_bio ??
    `An expert on ${expert.topic}, built from screened sources. Every answer cites the passages it came from.`
  const image = expert.picture
    ? `${appUrl()}${sharedPictureUrl(token, expert.picture.version)}`
    : undefined

  return {
    title,
    description,
    robots,
    referrer: 'no-referrer',
    openGraph: {
      type: 'website',
      siteName: 'Peritus',
      title,
      description,
      ...(image
        ? { images: [{ url: image, width: expert.picture?.width, height: expert.picture?.height }] }
        : {}),
    },
    twitter: { card: 'summary', title, description, ...(image ? { images: [image] } : {}) },
  }
}

export default async function SharePage({ params }: Props) {
  const { token } = await params
  const [expert, signedIn] = await Promise.all([getSharedExpert(token), hasSession()])
  if (!expert) notFound()

  return <SharedExpertCard token={token} expert={expert} signedIn={signedIn} />
}
