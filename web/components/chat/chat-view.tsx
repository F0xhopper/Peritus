'use client'

import { Pencil } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Composer } from '@/components/chat/composer'
import { PassagePanel } from '@/components/chat/passage-panel'
import { Transcript } from '@/components/chat/transcript'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { MenuItem } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { takePendingQuestion, useChatStream } from '@/hooks/use-chat-stream'
import { cn } from '@/lib/cn'
import { chatTitle } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import type {
  Citation,
  ConversationDetail,
  ConversationSummary,
  CorpusReport,
  ExpertWithCatalog,
  LedgerSource,
} from '@/lib/api/types'

/**
 * One conversation.
 *
 * The transcript is server-rendered from the persisted messages, and the
 * streaming turn is layered on top as local state — so a refresh mid-answer
 * loses nothing (the server has the partial, marked interrupted) and the page
 * is correct on first paint without waiting for a stream.
 *
 * **Chat is gated on `readiness`.** A pending expert disables the composer with
 * a link to its build; a chat-ready one whose graph is still extracting gets a
 * one-line note rather than a block, because it answers perfectly well.
 */
export function ChatView({
  conversation,
  expert,
  siblings,
}: {
  conversation: ConversationDetail
  expert: ExpertWithCatalog
  siblings: ConversationSummary[]
}) {
  const router = useRouter()
  const { openContext, setChatExpert } = useShell()
  const chat = useChatStream(conversation.id)
  const [selected, setSelected] = useState<Citation | null>(null)
  // The accepted half of the ledger, fetched the first time a citation is
  // opened, so the panel can show the source's type, scores and links rather
  // than only the citation's one-line label.
  const [ledger, setLedger] = useState<Map<number, LedgerSource> | null>(null)
  const ledgerRequested = useRef(false)
  const serverTitle = chatTitle(conversation.title)
  const [title, setTitle] = useState(serverTitle)
  // Follow the server's title when a refetch brings a new one — the first
  // question names the chat, and until this the top bar said "Untitled chat"
  // until a reload. Adjusted during render, not in an effect.
  const [seenServerTitle, setSeenServerTitle] = useState(serverTitle)
  if (serverTitle !== seenServerTitle) {
    setSeenServerTitle(serverTitle)
    setTitle(serverTitle)
  }
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState<{ text: string; id: number } | null>(null)
  const handed = useRef(false)

  const chattable = expert.readiness !== 'pending'

  // Tell the shell whose chat this is, so the rail and sidebar stay on this
  // expert even when the chat is not in the layout's recents.
  useEffect(() => {
    setChatExpert({ chatId: conversation.id, slug: expert.name })
    return () =>
      setChatExpert((current) => (current?.chatId === conversation.id ? null : current))
  }, [conversation.id, expert.name, setChatExpert])

  /**
   * Hand off between the streamed turn and the persisted one.
   *
   * On `done` the hook calls `router.refresh()`, and the server then returns
   * the turn it has stored. Until that lands the streamed copy is the only
   * copy; once it lands, rendering both would show the same answer twice.
   *
   * Purely derived — no state, no timer. The server persists exactly the tokens
   * it streamed, so "the last persisted answer is the answer on screen" is an
   * exact test for "the refetch has landed". Clearing the stream on `done`
   * instead would blank the answer for as long as the refetch took, and a timer
   * would sometimes show both.
   */
  const lastPersistedAnswer = [...conversation.messages]
    .reverse()
    .find((message) => message.role === 'assistant')
  const streamedTurnPersisted =
    chat.answer.trim().length > 0 && lastPersistedAnswer?.content.trim() === chat.answer.trim()

  // The question in flight, shown until the refetched transcript carries it:
  // either the whole turn has landed, or (after a failure) the stored question
  // is the transcript's last message.
  const lastPersisted = conversation.messages.at(-1)
  const pendingQuestion =
    chat.question &&
    chat.phase !== 'idle' &&
    chat.phase !== 'busy' &&
    !streamedTurnPersisted &&
    !(lastPersisted?.role === 'user' && lastPersisted.content.trim() === chat.question)
      ? chat.question
      : null

  const ask = (question: string) => void chat.send(question)

  // The handoff from the expert page's composer. `sessionStorage`, consumed
  // exactly once — the ref guards against Strict Mode's double effect firing
  // the question twice.
  useEffect(() => {
    if (handed.current || !chattable) return
    const pending = takePendingQuestion(conversation.id)
    if (!pending) return
    handed.current = true
    ask(pending)
    // `chat.send` is stable per conversation; depending on it would re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.id, chattable])

  const selectCitation = (citation: Citation) => {
    setSelected(citation)
    if (citation.source_id !== null && !ledgerRequested.current) {
      ledgerRequested.current = true
      void fetch(
        `/api/experts/${encodeURIComponent(expert.name)}/sources?decision=accepted&limit=500`,
      )
        .then((res) => (res.ok ? (res.json() as Promise<CorpusReport>) : null))
        .then((report) => {
          if (!report) throw new Error('ledger unavailable')
          setLedger(new Map(report.sources.map((source) => [source.id, source])))
        })
        .catch(() => {
          // The label alone still renders, so no toast — but let a later click
          // try again rather than leaving the panel bare for the whole visit.
          ledgerRequested.current = false
        })
    }
    // Opens the overlay at `lg` and the bottom sheet below; at `xl` the inline
    // panel is already there and this is a no-op.
    openContext()
  }

  const rename = async (next: string) => {
    const trimmed = next.trim().slice(0, 120)
    if (!trimmed || trimmed === title) {
      setRenaming(false)
      return
    }
    const previous = title
    // Optimistic: the title is the thing the user just typed, so showing it
    // immediately is correct, and the rollback is one line.
    setTitle(trimmed)
    setRenaming(false)
    try {
      const res = await fetch(`/api/conversations/${conversation.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      })
      if (!res.ok) throw new Error()
      router.refresh()
    } catch {
      setTitle(previous)
      toast.error('Could not rename that chat.')
    }
  }

  const remove = async () => {
    try {
      const res = await fetch(`/api/conversations/${conversation.id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error()
      toast.success('Chat deleted')
      router.push(`/experts/${expert.name}`)
      // The sidebar's chat list belongs to the layout, not this page.
      router.refresh()
    } catch {
      toast.error('Could not delete that chat.')
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title={title}
        titleSlot={
          renaming ? (
            <input
              defaultValue={title}
              autoFocus
              maxLength={120}
              onBlur={(event) => void rename(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void rename(event.currentTarget.value)
                if (event.key === 'Escape') setRenaming(false)
              }}
              aria-label="Chat title"
              className="w-full min-w-0 rounded-chip bg-raised px-1.5 py-0.5 text-sm text-fg focus:outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={() => setRenaming(true)}
              title="Click to rename"
              // `--row-h` rather than the text's own height: this is the one
              // control in the bar a thumb has to hit, and at `py-0.5` it was
              // 24px tall — under the 44px floor every touch project asserts.
              className="group/title flex h-(--row-h) w-full items-center gap-1.5 rounded-chip px-1.5 text-left text-sm font-medium text-fg transition-colors duration-(--dur-1) hover:bg-raised"
            >
              <span className="truncate">{title}</span>
              {/* The affordance, not just a tooltip: shown on hover with a
                  mouse and always on touch, where there is no hover. */}
              <Pencil
                aria-hidden="true"
                className="size-3 shrink-0 text-fg-3 opacity-0 transition-opacity duration-(--dur-1) group-hover/title:opacity-100 [@media(hover:none)]:opacity-100"
              />
            </button>
          )
        }
        overflow={
          <>
            <MenuItem onClick={() => setRenaming(true)}>Rename</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>
              Open the expert
            </MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}/sources`)}>
              Sources
            </MenuItem>
            <MenuItem tone="danger" onClick={() => void remove()}>
              Delete chat
            </MenuItem>
          </>
        }
      />

      {chat.phase === 'error' && chat.error && (
        <div className="px-3 pt-3 md:px-4">
          <Notice tone="bad">{chat.error}</Notice>
        </div>
      )}

      {chat.phase === 'busy' && (
        <div className="px-3 pt-3 md:px-4">
          <Notice tone="warn" title="Still answering">
            This conversation has an answer in flight — probably in another tab. It will free up
            {chat.retryIn !== null ? ` in ${chat.retryIn}s` : ' shortly'}.
          </Notice>
        </div>
      )}

      <Transcript
        expert={expert}
        messages={conversation.messages}
        pendingQuestion={pendingQuestion}
        streamingAnswer={streamedTurnPersisted ? '' : chat.answer}
        streamingCitations={chat.citations}
        streamingDangling={chat.dangling}
        status={chat.status}
        streaming={chat.streaming}
        audit={chat.audit}
        hasContradiction={chat.hasContradiction}
        onSelectCitation={selectCitation}
        selectedCitation={selected?.n ?? null}
        onRegenerate={ask}
      />

      {chattable && expert.readiness === 'chat_ready' && (
        <p className="shrink-0 px-3 pb-1 text-xs text-fg-3 md:px-4">
          The concept graph is still building, so answers are not yet expanded with related
          concepts or flagged where sources disagree.
        </p>
      )}

      <Composer
        onSend={ask}
        onStop={chat.stop}
        streaming={chat.streaming}
        disabled={!chattable || chat.phase === 'busy'}
        disabledReason={
          !chattable ? (
            <>
              {displayName(expert)} has no indexed passages yet.{' '}
              <Link
                href={`/experts/${expert.name}/build`}
                className="text-fg underline underline-offset-2"
              >
                Watch the build
              </Link>
              .
            </>
          ) : (
            'Waiting for the answer in flight to finish.'
          )
        }
        placeholder={
          subtitle(expert)
            ? `Ask ${displayName(expert)} about ${subtitle(expert)}…`
            : `Ask ${displayName(expert)}…`
        }
        autoFocus={conversation.messages.length === 0}
        draft={draft}
      />

      {selected && (
        <ContextSlot title="Cited passage" open onClose={() => setSelected(null)}>
          <PassagePanel
            citation={selected}
            source={
              selected.source_id !== null ? (ledger?.get(selected.source_id) ?? null) : null
            }
            slug={expert.name}
            onAsk={(title) => {
              setDraft({ text: `What else does “${title}” say about this?`, id: Date.now() })
              // Below `xl` the panel covers the composer; close it so the
              // question is visible where it will be sent from.
              if (!window.matchMedia('(min-width: 1280px)').matches) setSelected(null)
            }}
          />
        </ContextSlot>
      )}

      {/* Sibling chats are in the sidebar at `lg`+; below that the nav drawer
          carries the same list, so nothing is rendered here. */}
      <span className={cn('sr-only')}>{siblings.length} chats with this expert</span>
    </div>
  )
}
