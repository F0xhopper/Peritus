'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { ApiError } from '@/lib/api/errors'
import { streamSse } from '@/lib/api/sse'
import type { ChatEvent, ChatRetrievalAuditEvent, Citation } from '@/lib/api/types'

/**
 * Ask a question and stream the answer.
 *
 * The rendering discipline is the point of this hook, not the transport:
 *
 * **One `setState` per animation frame.** Tokens land in a ref and are flushed
 * on a `requestAnimationFrame`. A 2,000-token answer would otherwise be 2,000
 * renders of a growing Markdown tree, which drops frames on a mid-range phone
 * long before the answer finishes.
 *
 * **The status line is separate state.** "Searching" → "Composing" must not
 * re-render the transcript, so it never shares a state object with the answer.
 *
 * **Only Stop aborts.** Unmount does not: Strict Mode double-mounts, and an
 * abort on cleanup would cancel every first request in development. A stopped
 * or abandoned stream leaves the partial answer persisted server-side as
 * `interrupted`, which is what makes Retry possible.
 */

export type ChatPhase = 'idle' | 'streaming' | 'done' | 'error' | 'busy'

export interface ChatStreamState {
  phase: ChatPhase
  /**
   * The question this turn is answering. The server stores it before the
   * first token, but the page's transcript is the render from *before* the
   * send, so without this the question is invisible until the turn ends — and
   * on a failed turn, which never refreshes, it was never shown at all.
   */
  question: string | null
  /** The answer so far. Flushed once per frame. */
  answer: string
  /** The latest status message, or null between turns. */
  status: string | null
  citations: Citation[]
  /** Markers the answer invented; rendered as plain text, never as links. */
  dangling: number[]
  hasContradiction: boolean
  audit: ChatRetrievalAuditEvent | null
  error: string | null
  /** Seconds until the 409 claim window expires, counted down from 180. */
  retryIn: number | null
}

const CLAIM_WINDOW_SECONDS = 180

function emptyState(): ChatStreamState {
  return {
    phase: 'idle',
    question: null,
    answer: '',
    status: null,
    citations: [],
    dangling: [],
    hasContradiction: false,
    audit: null,
    error: null,
    retryIn: null,
  }
}

export interface UseChatStreamResult extends ChatStreamState {
  send: (question: string) => Promise<void>
  stop: () => void
  /** Clear a finished or failed turn, ready for the next question. */
  reset: () => void
  streaming: boolean
}

export function useChatStream(conversationId: string): UseChatStreamResult {
  const router = useRouter()
  const [state, setState] = useState<ChatStreamState>(emptyState)

  const buffer = useRef('')
  const frame = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const stopped = useRef(false)

  const flush = useCallback(() => {
    frame.current = 0
    const text = buffer.current
    setState((prev) => (prev.answer === text ? prev : { ...prev, answer: text }))
  }, [])

  const scheduleFlush = useCallback(() => {
    if (frame.current) return
    frame.current = requestAnimationFrame(flush)
  }, [flush])

  useEffect(() => {
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current)
    }
  }, [])

  const reset = useCallback(() => {
    buffer.current = ''
    setState(emptyState())
  }, [])

  const stop = useCallback(() => {
    stopped.current = true
    controller.current?.abort()
    controller.current = null
    // Whatever arrived stays on screen and is persisted server-side as an
    // interrupted answer, so Retry has something to continue from.
    flush()
    setState((prev) => ({ ...prev, phase: 'done', status: null }))
    router.refresh()
  }, [flush, router])

  const send = useCallback(
    async (question: string) => {
      if (!question.trim()) return

      buffer.current = ''
      stopped.current = false
      setState({ ...emptyState(), phase: 'streaming', question: question.trim() })

      const ac = new AbortController()
      controller.current = ac

      try {
        const res = await fetch(
          `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            body: JSON.stringify({ question: question.trim() }),
            signal: ac.signal,
            cache: 'no-store',
          }
        )

        if (res.status === 409) {
          // Another tab (or this one before a refresh) is mid-answer. The claim
          // self-expires, so the composer re-enables on a countdown rather than
          // the user retrying into the same 409.
          setState({ ...emptyState(), phase: 'busy', retryIn: CLAIM_WINDOW_SECONDS })
          return
        }
        if (!res.ok) {
          const detail = await res.json().catch(() => null)
          const message =
            (detail && typeof detail.detail === 'string' && detail.detail) ||
            `The expert could not answer (${res.status}).`
          throw new ApiError(res.status, message)
        }

        for await (const frameData of streamSse<ChatEvent>(res)) {
          const event = frameData.data
          switch (event.type) {
            case 'meta':
              // `conversation_id` and the auto-title. The sidebar picks the
              // title up from the refresh on `done`.
              break
            case 'status':
              setState((prev) => ({ ...prev, status: String(event.message ?? '') }))
              break
            case 'token':
              buffer.current += String((event as { text?: unknown }).text ?? '')
              scheduleFlush()
              break
            case 'sources': {
              const citations = Array.isArray((event as { citations?: unknown }).citations)
                ? (event as { citations: Citation[] }).citations
                : []
              const dangling = Array.isArray(
                (event as { dangling_citations?: unknown }).dangling_citations
              )
                ? (event as { dangling_citations: number[] }).dangling_citations
                : []
              setState((prev) => ({
                ...prev,
                citations,
                dangling,
                hasContradiction:
                  (event as { has_contradiction?: boolean }).has_contradiction === true,
              }))
              break
            }
            case 'retrieval_audit':
              setState((prev) => ({ ...prev, audit: event as ChatRetrievalAuditEvent }))
              break
            case 'error':
              flush()
              setState((prev) => ({
                ...prev,
                phase: 'error',
                status: null,
                error: String(
                  (event as { message?: unknown }).message ?? 'The expert hit an error.'
                ),
              }))
              // The question (and any partial, marked interrupted) is stored
              // and the conversation has its title now, so refetch them — the
              // transcript's "Ask it again" record is what outlives this notice.
              router.refresh()
              return
            case 'done':
              flush()
              setState((prev) => ({ ...prev, phase: 'done', status: null }))
              // The turn is persisted now, so the server data (transcript,
              // conversation title, sidebar) is refetched once.
              router.refresh()
              return
            default:
              // Unknown event type — ignored, as with the build stream.
              break
          }
        }

        // The stream ended without `done`: the connection dropped mid-answer.
        // Whatever arrived is kept and marked finished; the server has it as
        // interrupted and the card offers Retry.
        flush()
        setState((prev) =>
          prev.phase === 'streaming' ? { ...prev, phase: 'done', status: null } : prev
        )
        router.refresh()
      } catch (error) {
        if (stopped.current || (error instanceof Error && error.name === 'AbortError')) return
        flush()
        setState((prev) => ({
          ...prev,
          phase: 'error',
          status: null,
          error:
            error instanceof ApiError
              ? error.message
              : 'Lost the connection while the expert was answering.',
        }))
      } finally {
        controller.current = null
      }
    },
    [conversationId, flush, router, scheduleFlush]
  )

  // The 409 countdown. One interval, only while busy.
  useEffect(() => {
    if (state.phase !== 'busy' || state.retryIn === null) return
    const timer = setInterval(() => {
      setState((prev) => {
        if (prev.retryIn === null) return prev
        const left = prev.retryIn - 1
        if (left <= 0) return { ...prev, phase: 'idle', retryIn: null }
        return { ...prev, retryIn: left }
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [state.phase, state.retryIn])

  return { ...state, send, stop, reset, streaming: state.phase === 'streaming' }
}

/**
 * The handoff for a brand-new conversation's first question.
 *
 * The composer on the expert page creates the conversation, navigates to
 * `/chats/[id]`, and the new page sends the question. Passing it through
 * `sessionStorage` rather than component state is what makes that survive the
 * navigation — and a query parameter would put the question in the URL bar and
 * in the history.
 */
const PENDING_KEY = 'peritus:pending-question'

export function stashPendingQuestion(conversationId: string, question: string) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify({ conversationId, question }))
  } catch {
    /* private mode: the user retypes, which is survivable */
  }
}

/**
 * The question being carried to a new chat, without consuming it.
 *
 * Read during render — by the chat's loading screen, which does not know the
 * conversation id yet, and by the chat's first frame — so the question is on
 * screen from the moment the Ask is pressed. Before this the route went Overview
 * → a skeleton of a made-up question and answer → the empty-chat intro → the
 * question, each step crossfaded: a flash of three screens that were never the
 * one being opened.
 */
export function peekPendingQuestion(conversationId?: string): string | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { conversationId?: string; question?: string }
    if (conversationId !== undefined && parsed.conversationId !== conversationId) return null
    return typeof parsed.question === 'string' ? parsed.question : null
  } catch {
    return null
  }
}

/** For `useSyncExternalStore`: the stash changes only through this tab's own writes. */
export function subscribeToNothing() {
  return () => {}
}

export function takePendingQuestion(conversationId: string): string | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { conversationId?: string; question?: string }
    if (parsed.conversationId !== conversationId) return null
    sessionStorage.removeItem(PENDING_KEY)
    return typeof parsed.question === 'string' ? parsed.question : null
  } catch {
    return null
  }
}
