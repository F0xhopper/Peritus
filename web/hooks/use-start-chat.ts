'use client'

import { useRouter } from 'next/navigation'

import { useApiAction } from '@/hooks/use-api-action'
import { apiSend } from '@/lib/api/client'
import type { ConversationSummary } from '@/lib/api/types'

/**
 * Create a conversation with an expert and land in it, composer focused.
 *
 * The payoff of a build is asking the expert something. Sending someone who has
 * just watched a build finish to the Overview — a properties document with the
 * composer as its last section — made them go looking for the thing they paid
 * for. An empty chat focuses its own composer on arrival.
 */
export function useStartChat(slug: string) {
  const router = useRouter()

  const { run, pending } = useApiAction(
    () =>
      apiSend<ConversationSummary>(
        `/api/experts/${encodeURIComponent(slug)}/conversations`,
        'POST',
        undefined,
        'Could not start that chat.'
      ),
    {
      error: 'Could not start that chat.',
      // The navigation is the feedback; a toast on top of it is noise.
      onSuccess: (conversation) => router.push(`/chats/${conversation.id}`),
      // Landing in the new chat re-renders the layout anyway.
      refresh: false,
    }
  )

  return { start: run, starting: pending }
}
