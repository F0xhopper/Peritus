'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

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
  const [starting, setStarting] = useState(false)

  const start = useCallback(async () => {
    setStarting(true)
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/conversations`, {
        method: 'POST',
      })
      if (res.status === 409) {
        toast.error('This expert cannot answer yet.')
        return
      }
      if (!res.ok) throw new Error()
      const conversation = (await res.json()) as ConversationSummary
      router.push(`/chats/${conversation.id}`)
    } catch {
      toast.error('Could not start that chat.')
    } finally {
      setStarting(false)
    }
  }, [router, slug])

  return { start, starting }
}
