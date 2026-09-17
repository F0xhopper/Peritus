'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useRef } from 'react'

import { useApiAction } from '@/hooks/use-api-action'
import { stashPendingQuestion } from '@/hooks/use-chat-stream'
import { apiSend } from '@/lib/api/client'
import type { ConversationSummary } from '@/lib/api/types'

/**
 * Create a conversation with an expert and land in it, composer focused.
 *
 * The payoff of a build is asking the expert something. Sending someone who has
 * just watched a build finish to the Overview — a properties document with the
 * composer as its last section — made them go looking for the thing they paid
 * for. An empty chat focuses its own composer on arrival.
 *
 * `start(question)` asks it straight away: the question is stashed against the
 * new conversation's id and the chat sends it on arrival. That is how a source
 * row's *Ask about this* works — it used to stash a draft and bounce the reader
 * through the Overview, a page they had not asked for.
 */
export function useStartChat(slug: string) {
  const router = useRouter()
  // Held in a ref rather than state: it is read once, inside the callback that
  // follows the POST, and re-rendering for it would be pointless work.
  const question = useRef<string | null>(null)

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
      onSuccess: (conversation) => {
        const asked = question.current
        question.current = null
        if (asked) stashPendingQuestion(conversation.id, asked)
        router.push(`/chats/${conversation.id}`)
      },
      // Landing in the new chat re-renders the layout anyway.
      refresh: false,
    }
  )

  const start = useCallback(
    (asked?: string) => {
      question.current = asked?.trim() || null
      return run()
    },
    [run]
  )

  return { start, starting: pending }
}
