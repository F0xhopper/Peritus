import { ChatLoadingTranscript } from '@/components/chat/chat-loading'
import { Skeleton, SkeletonTopBar } from '@/components/ui/skeleton'

/**
 * A conversation: the transcript starts at the top of its column, as the real
 * one does, and the composer is pinned below. The transcript is a client piece
 * so that a question just asked on the Overview is shown as itself while the
 * chat loads — see `ChatLoadingTranscript`.
 */
export default function Loading() {
  return (
    <>
      <SkeletonTopBar crumb titleWidth="w-56" />
      <div className="flex min-h-0 flex-1 flex-col">
        <ChatLoadingTranscript />
        <div className="shrink-0 px-3 pt-2 pb-3 md:px-4">
          <Skeleton className="mx-auto h-11 w-full max-w-[720px] rounded-card" />
        </div>
      </div>
    </>
  )
}
