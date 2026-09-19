'use client'

import { useSyncExternalStore } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { peekPendingQuestion, subscribeToNothing } from '@/hooks/use-chat-stream'

/**
 * The transcript area while a chat loads.
 *
 * Opening a chat that exists: a skeleton of a question and its answer card,
 * as before. Arriving with a question just asked on the Overview: that question,
 * set exactly where and how the chat will set it, and nothing else — the
 * skeleton's made-up answer card, then the empty chat's intro, then the real
 * question was a three-screen flash between pressing Ask and seeing it asked.
 */
export function ChatLoadingTranscript() {
  const carried = useSyncExternalStore(
    subscribeToNothing,
    () => peekPendingQuestion(),
    () => null
  )

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-1 flex-col gap-4 px-3 py-4 md:px-4">
      {carried ? (
        // Matches `UserTurn` in transcript.tsx.
        <p className="text-base leading-relaxed font-medium whitespace-pre-wrap text-fg">
          {carried}
        </p>
      ) : (
        <>
          <Skeleton className="h-4 w-2/3" />
          <div className="rounded-card border border-border-soft bg-panel p-3 md:p-4">
            <div className="mb-3 flex items-center gap-2">
              <Skeleton className="size-5 rounded-chip" />
              <Skeleton className="h-3.5 w-32" />
            </div>
            <div className="space-y-2">
              {['w-full', 'w-full', 'w-11/12', 'w-full', 'w-3/4', 'w-full', 'w-5/6'].map(
                (width, i) => (
                  <Skeleton key={i} className={`h-3.5 ${width}`} />
                )
              )}
            </div>
            <Skeleton className="mt-4 h-3 w-24" />
          </div>
        </>
      )}
    </div>
  )
}
