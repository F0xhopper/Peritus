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
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { MenuItem } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { takePendingQuestion, useChatStream } from '@/hooks/use-chat-stream'
import { auditsByMessageId } from '@/lib/chat-audits'
import { cn } from '@/lib/cn'
import { chatTitle } from '@/lib/format'
import { displayName, subtitle } from '@/lib/persona'
import { useApiAction } from '@/hooks/use-api-action'
import { apiSend, apiVoid, messageFor } from '@/lib/api/client'
import type {
  AnswerAuditsPage,
  ChatRetrievalAuditEvent,
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
  unavailable = false,
}: {
  conversation: ConversationDetail
  expert: ExpertWithCatalog
  siblings: ConversationSummary[]
  /** The expert was shared with the caller and no longer is. The transcript
   *  stays readable; asking, opening the expert and its sources do not. */
  unavailable?: boolean
}) {
  const router = useRouter()
  const { openContext, setChatExpert } = useShell()
  const chat = useChatStream(conversation.id)
  const [selected, setSelected] = useState<Citation | null>(null)
  // Every citation in the answer the open one came from, so the panel can name
  // the other numbers that rest on the same source.
  const [selectedAnswer, setSelectedAnswer] = useState<Citation[]>([])
  // The accepted half of the ledger, fetched the first time a citation is
  // opened, so the panel can show the source's type, scores and links rather
  // than only the citation's one-line label.
  const [ledger, setLedger] = useState<Map<number, LedgerSource> | null>(null)
  const ledgerRequested = useRef(false)
  // The stored retrieval trails for the answers already in this transcript.
  const [storedAudits, setStoredAudits] = useState<Map<number, ChatRetrievalAuditEvent>>(
    () => new Map()
  )
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
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [draft, setDraft] = useState<{ text: string; id: number } | null>(null)
  const handed = useRef(false)

  const chattable = !unavailable && expert.readiness !== 'pending'

  // Tell the shell whose chat this is, so the rail and sidebar stay on this
  // expert even when the chat is not in the layout's recents.
  useEffect(() => {
    setChatExpert({ chatId: conversation.id, slug: expert.name })
    return () => setChatExpert((current) => (current?.chatId === conversation.id ? null : current))
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
  /**
   * The stored retrieval trails, once per visit.
   *
   * Fetched rather than streamed: the live `retrieval_audit` event only exists
   * for the turn you watched, so before this every answer lost its trail on
   * reload. One GET, best-effort — a failure means the action is simply absent,
   * which is what it was before.
   */
  useEffect(() => {
    if (!conversation.messages.some((message) => message.role === 'assistant')) return
    const controller = new AbortController()
    void fetch(
      `/api/experts/${encodeURIComponent(expert.name)}/answer-audits?conversation_id=${conversation.id}&limit=50`,
      { signal: controller.signal }
    )
      .then((response) => (response.ok ? (response.json() as Promise<AnswerAuditsPage>) : null))
      .then((page) => {
        if (page) setStoredAudits(auditsByMessageId(conversation.messages, page.audits ?? []))
      })
      .catch(() => {
        /* no trail is the status quo ante, and not worth a toast */
      })
    return () => controller.abort()
  }, [conversation.id, conversation.messages, expert.name])

  useEffect(() => {
    if (handed.current || !chattable) return
    const pending = takePendingQuestion(conversation.id)
    if (!pending) return
    handed.current = true
    ask(pending)
    // `chat.send` is stable per conversation; depending on it would re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.id, chattable])

  const selectCitation = (citation: Citation, all: Citation[] = []) => {
    setSelected(citation)
    setSelectedAnswer(all)
    if (citation.source_id !== null && !ledgerRequested.current) {
      ledgerRequested.current = true
      void fetch(
        `/api/experts/${encodeURIComponent(expert.name)}/sources?decision=accepted&limit=500`
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
      await apiSend(`/api/conversations/${conversation.id}`, 'PATCH', { title: trimmed })
      router.refresh()
    } catch (error) {
      setTitle(previous)
      toast.error(messageFor(error, 'Could not rename that chat.'))
    }
  }

  // The refresh is not optional: the sidebar's chat list belongs to the layout,
  // and a push reuses it.
  const { run: remove, pending: deleting } = useApiAction(
    () => apiVoid(`/api/conversations/${conversation.id}`, { method: 'DELETE' }),
    {
      success: 'Chat deleted',
      error: 'Could not delete that chat.',
      onSuccess: () => {
        setConfirmingDelete(false)
        router.push(unavailable ? '/chats' : `/experts/${expert.name}`)
      },
    }
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        // No crumb to an expert the caller can no longer open.
        expert={unavailable ? null : expert}
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
            {!unavailable && (
              <>
                <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>
                  Open the expert
                </MenuItem>
                <MenuItem onClick={() => router.push(`/experts/${expert.name}/sources`)}>
                  Sources
                </MenuItem>
              </>
            )}
            {/* Behind a confirm, like every other delete in the product. It
                used to fire on the click: a whole conversation gone from a
                menu item, with no dialog and no undo. */}
            <MenuItem tone="danger" onClick={() => setConfirmingDelete(true)}>
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
        intro={{ bio: expert.persona_bio, concepts: expert.key_concepts }}
        storedAudits={storedAudits}
        onStarter={(question) => setDraft({ text: question, id: Date.now() })}
        onSelectCitation={selectCitation}
        selectedCitation={selected?.n ?? null}
        onRegenerate={ask}
      />

      {chattable && expert.readiness === 'chat_ready' && (
        <p className="shrink-0 px-3 pb-1 text-xs text-fg-3 md:px-4">
          The concept graph is still building, so answers are not yet expanded with related concepts
          or flagged where sources disagree.
        </p>
      )}

      <Composer
        onSend={ask}
        onStop={chat.stop}
        streaming={chat.streaming}
        disabled={!chattable || chat.phase === 'busy'}
        disabledReason={
          unavailable ? (
            'This expert is no longer shared with you. The chat is kept, but it cannot be continued.'
          ) : !chattable ? (
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
        // The long form only when it fits one line on a phone: "Ask Dr. Marta
        // Belen about Varroa mite control in temperate beekeeping…" wrapped at
        // 393px, so the empty composer was two lines tall before a word was
        // typed. Measured in characters rather than by a media query, so the
        // server and the browser render the same string.
        placeholder={placeholderFor(expert)}
        autoFocus={conversation.messages.length === 0}
        draft={draft}
      />

      <Dialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete this chat?"
        description="Every question and answer in it goes. The expert and its sources are untouched."
        disablePointerDismissal
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
              Keep it
            </Button>
            <Button variant="danger" loading={deleting} onClick={() => void remove()} minWidth={92}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-3">{title}</p>
      </Dialog>

      {selected && (
        <ContextSlot title="Cited passage" open onClose={() => setSelected(null)}>
          <PassagePanel
            citation={selected}
            source={selected.source_id !== null ? (ledger?.get(selected.source_id) ?? null) : null}
            slug={expert.name}
            siblings={selectedAnswer.filter(
              (other) =>
                other.n !== selected.n &&
                other.source_id !== null &&
                other.source_id === selected.source_id
            )}
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

const PLACEHOLDER_CHARS = 48

function placeholderFor(expert: ExpertWithCatalog): string {
  const name = displayName(expert)
  const topic = subtitle(expert)
  const long = topic ? `Ask ${name} about ${topic}…` : ''
  return long && long.length <= PLACEHOLDER_CHARS ? long : `Ask ${name}…`
}
