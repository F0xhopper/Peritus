'use client'

import { ArrowUp } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { stashPendingQuestion } from '@/hooks/use-chat-stream'
import { cn } from '@/lib/cn'
import type { ConversationSummary, ExpertSummary } from '@/lib/api/types'

/**
 * The id of the question field, so the Overview's own "Ask" action can put the
 * cursor in it rather than merely scrolling past it. Exported rather than
 * written twice: a hard-coded id on one end and a `getElementById` on the other
 * is a link nothing checks.
 */
export const ASK_FIELD_ID = 'ask-question'

const DRAFT_KEY = 'peritus:ask-draft'

/**
 * Pre-fill the Overview's ask field for the next visit to `…#ask` — what the
 * ledger's and the graph's "Ask about this" do before navigating there. The
 * reader edits the question rather than retyping a source title.
 */
export function stashAskDraft(slug: string, text: string) {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ slug, text }))
  } catch {
    /* private mode: the field is simply empty */
  }
}

function takeAskDraft(slug: string): string | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { slug?: string; text?: string }
    if (parsed.slug !== slug) return null
    sessionStorage.removeItem(DRAFT_KEY)
    return typeof parsed.text === 'string' ? parsed.text : null
  } catch {
    return null
  }
}

/**
 * Scroll to and focus the ask field when `href` is `…#ask` on the page already
 * open. Returns whether it did, so a link can skip its own navigation.
 */
export function focusAskField(href: string): boolean {
  const [path, hash] = href.split('#')
  if (hash !== 'ask' || path !== window.location.pathname) return false
  const field = document.getElementById(ASK_FIELD_ID)
  if (!field) return false
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  document.getElementById('ask')?.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })
  field.focus({ preventScroll: true })
  return true
}

/**
 * The first question of a new conversation.
 *
 * Three steps, and the order matters: create the conversation, stash the
 * question in `sessionStorage`, then navigate. The stash is what survives the
 * navigation — holding the question in state and sending it from here would
 * have the request aborted as this component unmounts, and putting it in the
 * URL would leave it in the address bar and the history.
 */
export function NewChatComposer({
  expert,
  className,
}: {
  expert: Pick<ExpertSummary, 'name' | 'persona_name' | 'topic'>
  className?: string
}) {
  const router = useRouter()
  const [question, setQuestion] = useState('')
  const [starting, setStarting] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)

  // Arriving from a "New chat" or "Ask about this" link (`…#ask`). The router's
  // own hash scroll does not reach the page's inner scroll column, so scroll
  // the section into view here, and put the cursor in the field.
  useEffect(() => {
    if (window.location.hash !== '#ask') return
    const draft = takeAskDraft(expert.name)
    // A one-off read of browser storage after mount; it cannot happen during
    // render without the server and client disagreeing about the field.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (draft) setQuestion(draft)
    document.getElementById('ask')?.scrollIntoView({ block: 'start' })
    field.current?.focus({ preventScroll: true })
  }, [expert.name])

  const send = async () => {
    const trimmed = question.trim()
    if (!trimmed || starting) return
    setStarting(true)
    try {
      const res = await fetch(
        `/api/experts/${encodeURIComponent(expert.name)}/conversations`,
        { method: 'POST' },
      )
      if (res.status === 409) {
        toast.error('This expert cannot answer yet.')
        return
      }
      if (!res.ok) throw new Error()
      const conversation = (await res.json()) as ConversationSummary
      stashPendingQuestion(conversation.id, trimmed)
      router.push(`/chats/${conversation.id}`)
    } catch {
      toast.error('Could not start that chat.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className={cn('rounded-card border border-border bg-panel p-2', className)}>
      <Textarea
        id={ASK_FIELD_ID}
        ref={field}
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          // Enter sends, Shift+Enter breaks — but only with a fine pointer. On
          // a phone Enter is the keyboard's newline and the button is the only
          // way to send.
          if (event.key === 'Enter' && !event.shiftKey && window.matchMedia('(hover: hover)').matches) {
            event.preventDefault()
            void send()
          }
        }}
        rows={2}
        maxLength={4000}
        placeholder={`Ask about ${expert.topic}…`}
        aria-label="Your question"
        className="resize-none border-0 bg-transparent px-1 focus:border-0"
      />
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-xs text-fg-3">
          {question.length > 3600 ? `${question.length} / 4000` : 'Enter to send'}
        </span>
        <Button
          variant="primary"
          size="md"
          onClick={() => void send()}
          disabled={!question.trim()}
          loading={starting}
        >
          Ask
          <ArrowUp className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}
