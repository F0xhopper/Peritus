'use client'

import { ArrowDown, RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { AssistantCard } from '@/components/chat/assistant-card'
import { StatusLine } from '@/components/chat/status-line'
import { cn } from '@/lib/cn'
import type {
  ChatRetrievalAuditEvent,
  Citation,
  ConversationMessage,
  ExpertSummary,
} from '@/lib/api/types'

/**
 * The conversation.
 *
 * Auto-scroll follows the same at-bottom rule as the build log: new content
 * scrolls into view only while the reader is within 48px of the end, and
 * otherwise a *new content* pill appears. `overflow-anchor: none` is set on the
 * list because the browser's own scroll anchoring fights a card that is growing
 * a token at a time — with anchoring on, the viewport drifts upward as the
 * answer gets longer.
 *
 * Not virtualised: a conversation is tens of messages, not thousands, and the
 * cards use `content-visibility: auto` so off-screen ones cost nothing to
 * paint. A virtualiser here would break find-in-page for no measurable gain.
 */
const AT_BOTTOM_SLACK = 48

export function Transcript({
  expert,
  messages,
  pendingQuestion,
  streamingAnswer,
  streamingCitations,
  streamingDangling,
  status,
  streaming,
  audit,
  hasContradiction,
  onSelectCitation,
  selectedCitation,
  onRegenerate,
}: {
  expert: Pick<ExpertSummary, 'name' | 'persona_name' | 'topic' | 'avatar'>
  messages: ConversationMessage[]
  /** The question in flight, until the refetched transcript carries it. */
  pendingQuestion: string | null
  streamingAnswer: string
  streamingCitations: Citation[]
  streamingDangling: number[]
  status: string | null
  streaming: boolean
  audit: ChatRetrievalAuditEvent | null
  hasContradiction: boolean
  onSelectCitation: (citation: Citation) => void
  selectedCitation: number | null
  onRegenerate: (question: string) => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)

  const checkAtBottom = useCallback(() => {
    const element = scroller.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    setAtBottom(distance <= AT_BOTTOM_SLACK)
  }, [])

  useLayoutEffect(() => {
    if (!atBottom) return
    const element = scroller.current
    if (!element) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    element.scrollTo({
      top: element.scrollHeight,
      // Smooth within a screen, instant for a longer jump.
      behavior: distance < element.clientHeight ? 'smooth' : 'auto',
    })
  }, [messages.length, pendingQuestion, streamingAnswer, status, atBottom])

  useEffect(() => {
    checkAtBottom()
  }, [checkAtBottom])

  // The last user message, for Retry on an interrupted or failed answer.
  const lastQuestion = [...messages].reverse().find((m) => m.role === 'user')?.content ?? ''
  const unanswered =
    !streaming &&
    !streamingAnswer &&
    messages.length > 0 &&
    messages[messages.length - 1].role === 'user'

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scroller}
        onScroll={checkAtBottom}
        className="anchor-none pan-y h-full overflow-y-auto overscroll-contain"
      >
        {/* Top-anchored, like a page. Anchoring to the bottom (messaging-app
            style) left a one-turn conversation in the lower third under an
            empty screen, and put the answer exactly where the cited-passage
            sheet opens on a phone or tablet. A long conversation still opens
            at, and follows, its end — see the at-bottom effect above. */}
        <div className="mx-auto flex w-full max-w-[720px] flex-col gap-4 px-3 py-4 md:px-4">
          {messages.map((message, index) =>
            message.role === 'user' ? (
              <UserTurn key={message.id}>{message.content}</UserTurn>
            ) : (
              <AssistantCard
                key={message.id}
                expert={expert}
                content={message.content}
                citations={message.citations ?? []}
                dangling={[]}
                interrupted={message.interrupted}
                hasContradiction={message.has_contradiction}
                onSelectCitation={onSelectCitation}
                selectedCitation={selectedCitation}
                onRegenerate={
                  // Retry the question that produced this answer.
                  index > 0 && messages[index - 1]?.role === 'user'
                    ? () => onRegenerate(messages[index - 1].content)
                    : undefined
                }
              />
            )
          )}

          {/**
           * A question whose answer never arrived.
           *
           * The live failure is a notice above the transcript, and that notice
           * is state — it is gone on the next reload, which left the page
           * showing a question, nothing under it, and no hint that anything had
           * gone wrong. The record has to be as durable as the question is.
           */}
          {unanswered && (
            <div className="rounded-card bg-panel p-3 md:p-4">
              <p className="text-sm text-fg-2">
                No answer was recorded for this question. The answer was interrupted, or the server
                could not finish it.
              </p>
              <button
                type="button"
                onClick={() => onRegenerate(lastQuestion)}
                className={cn(
                  'mt-2 inline-flex h-(--row-h) items-center gap-1.5 rounded-row bg-raised px-2.5',
                  'text-xs text-fg-2 transition-colors duration-(--dur-1) hover:text-fg'
                )}
              >
                <RotateCcw className="size-3" />
                Ask it again
              </button>
            </div>
          )}

          {pendingQuestion && <UserTurn>{pendingQuestion}</UserTurn>}

          {(streaming || streamingAnswer) && (
            <>
              <StatusLine status={status} visible={streaming && !streamingAnswer} />
              {(streamingAnswer || streaming) && (
                <AssistantCard
                  expert={expert}
                  content={streamingAnswer}
                  citations={streamingCitations}
                  dangling={streamingDangling}
                  streaming={streaming}
                  audit={audit}
                  hasContradiction={hasContradiction}
                  onSelectCitation={onSelectCitation}
                  selectedCitation={selectedCitation}
                  onRegenerate={
                    !streaming && lastQuestion ? () => onRegenerate(lastQuestion) : undefined
                  }
                />
              )}
            </>
          )}
        </div>
      </div>

      {!atBottom && (
        <button
          type="button"
          onClick={() => {
            setAtBottom(true)
            scroller.current?.scrollTo({
              top: scroller.current.scrollHeight,
              behavior: 'smooth',
            })
          }}
          className={cn(
            'absolute bottom-3 left-1/2 -translate-x-1/2',
            'inline-flex h-(--icon-btn-sm) items-center gap-1.5 rounded-full border border-border bg-raised px-3',
            'text-xs text-fg-2 shadow-lg shadow-black/25',
            'transition-colors duration-(--dur-1) hover:text-fg',
            'motion-safe:animate-in motion-safe:duration-(--dur-2) motion-safe:fade-in motion-safe:slide-in-from-bottom-1'
          )}
        >
          <ArrowDown className="size-3" />
          {streaming ? 'New content' : 'Jump to the end'}
        </button>
      )}
    </div>
  )
}

/**
 * The user's own words, as plain text. No card and no bubble: this is not
 * something the product is asserting. `--fg` and a little weight, though,
 * because it is the heading of its turn — at `--fg-2` it read as quieter than
 * the answer under it.
 */
function UserTurn({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-base leading-relaxed font-medium whitespace-pre-wrap text-fg">{children}</p>
  )
}
