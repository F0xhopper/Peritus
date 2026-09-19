'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { seqFromId, streamSse } from '@/lib/api/sse'
import {
  initialBuildState,
  isTerminalEvent,
  reduceBuildEvent,
  type BuildState,
} from '@/lib/build/reducer'
import type { BuildEvent } from '@/lib/api/types'

/**
 * Tail a build's event log, resuming from a cursor across dropped connections.
 *
 * Three things here are load-bearing and easy to get wrong:
 *
 * **An abandoned connection is closed, and each run of the effect closes only
 * its own.** The tail is a `GET` with a cursor, opened *inside* the effect, so
 * every run owns one `AbortController` and its cleanup aborts that one. Strict
 * Mode's throwaway first mount therefore cancels a request nothing was going to
 * read, and the re-run opens the real one — unlike the chat stream, a `POST`
 * started by a click, where a cleanup abort would cancel the only request there
 * is (which is where "never abort on unmount" comes from, and why it still
 * holds there).
 *
 * It used to be abandoned without being closed — the loop stopped reducing and
 * the socket was left "until the response is garbage collected", which for an
 * open event stream is never. A build can go minutes between events, so every
 * visit to a page that tails one (the build page, Home, Knowledge) left a stream
 * open, two under Strict Mode. A browser allows six connections per host over
 * HTTP/1.1, which is what `next dev` and a plain `next start` speak: by the third
 * visit the new tail, `/map` and the cost poll were all queued behind streams
 * nobody was reading, and the page came back with no map and no cost.
 *
 * **A closed stream is not a finished build.** Only `done`, `error` or
 * `cancelled` ends the tail. Anything else means reconnect with
 * `after=<lastSeq>` on a 1s→10s backoff, which is the whole reason the log is
 * durable server-side.
 *
 * **`lastSeq` comes from the SSE `id:`, not from a counter.** The cursor has to
 * be the server's sequence number or a reconnect would replay or skip events.
 */

export interface UseBuildEventsOptions {
  /** Start tailing immediately. False parks the hook (a finished build). */
  enabled?: boolean
  /**
   * Events already received — typically from the `POST /experts/build`
   * response, which streams the same log from seq 0. The hook resumes after
   * the last of them rather than starting over.
   */
  seed?: { seq: number; event: BuildEvent }[]
  /** `router.refresh()` on a terminal event so the server data catches up. */
  refreshOnTerminal?: boolean
  onTerminal?: (state: BuildState) => void
}

const BACKOFF_START_MS = 1000
const BACKOFF_MAX_MS = 10_000

export interface BuildEventsResult {
  state: BuildState
  /** True while a reconnect is pending — the log shows a "reconnecting" line. */
  reconnecting: boolean
  /** True while a connection is open and events may arrive. */
  live: boolean
  /** Reopen now, for the retry button on a stalled tail. */
  reconnect: () => void
}

export function useBuildEvents(
  slug: string | null,
  options: UseBuildEventsOptions = {}
): BuildEventsResult {
  const { enabled = true, seed, refreshOnTerminal = true, onTerminal } = options
  const router = useRouter()

  const [state, setState] = useState<BuildState>(() => {
    let initial = initialBuildState()
    for (const { seq, event } of seed ?? []) initial = reduceBuildEvent(initial, seq, event)
    return initial
  })
  const [reconnecting, setReconnecting] = useState(false)
  const [live, setLive] = useState(false)

  // The cursor lives in a ref as well as in state: the read loop needs the
  // value synchronously, before React has committed the render.
  const lastSeq = useRef(state.lastSeq)
  const terminal = useRef(state.terminal !== null)
  const generation = useRef(0)
  const wake = useRef<(() => void) | null>(null)

  // Kept in a ref so the tail effect does not restart every time a parent
  // re-renders with a new inline callback. Written in an effect, not during
  // render — a render-phase ref write is not safe under concurrent rendering.
  const onTerminalRef = useRef(onTerminal)
  useEffect(() => {
    onTerminalRef.current = onTerminal
  }, [onTerminal])

  const reconnect = useCallback(() => {
    wake.current?.()
  }, [])

  useEffect(() => {
    if (!slug || !enabled || terminal.current) return

    const myGeneration = ++generation.current
    const stale = () => generation.current !== myGeneration
    // This run's connection, and only this run's. See the docstring.
    const connection = new AbortController()
    let backoff = BACKOFF_START_MS
    let cancelled = false
    let wakeTimer: ReturnType<typeof setTimeout> | null = null

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        wakeTimer = setTimeout(resolve, ms)
        // The retry button resolves the wait early rather than opening a second
        // connection alongside the one that is about to open.
        wake.current = () => {
          if (wakeTimer) clearTimeout(wakeTimer)
          resolve()
        }
      })

    const run = async () => {
      while (!cancelled && !stale() && !terminal.current) {
        try {
          const res = await fetch(
            `/api/experts/${encodeURIComponent(slug)}/build/events?after=${lastSeq.current}`,
            {
              headers: { Accept: 'text/event-stream' },
              cache: 'no-store',
              signal: connection.signal,
            }
          )

          if (res.status === 404) {
            // No build job for this expert yet. Nothing to tail, and polling
            // would be pointless — the page fetches status on navigation.
            setLive(false)
            return
          }
          if (res.status === 401) {
            // The session went while the tab sat open. A reload runs the proxy
            // gate, which either refreshes or sends the user to sign in.
            if (!stale()) router.refresh()
            return
          }
          if (!res.ok || !res.body) throw new Error(`Build stream failed (${res.status})`)

          if (stale()) return
          setLive(true)
          setReconnecting(false)
          backoff = BACKOFF_START_MS

          for await (const frame of streamSse<BuildEvent>(res)) {
            if (stale() || cancelled) return
            const seq = seqFromId(frame.id, lastSeq.current + 1)
            lastSeq.current = Math.max(lastSeq.current, seq)
            const done = isTerminalEvent(frame.data)
            if (done) terminal.current = true

            // The picture lands seconds into a build, while discovery is still
            // running, and it changes what the rail draws for this expert. The
            // rail is server-rendered, so nothing moves without a refresh —
            // this is the same `router.refresh()` a terminal event does, just
            // earlier and for a different reason.
            if (frame.data.type === 'picture_ready') {
              queueMicrotask(() => {
                if (!stale()) router.refresh()
              })
            }

            setState((prev) => {
              const next = reduceBuildEvent(prev, seq, frame.data)
              if (done) {
                // Deferred: calling out of a reducer would run during render.
                queueMicrotask(() => {
                  onTerminalRef.current?.(next)
                  if (refreshOnTerminal) router.refresh()
                })
              }
              return next
            })

            if (done) {
              setLive(false)
              return
            }
          }
        } catch {
          // A network blip, a proxy timeout, a server restart — or this run's
          // own abort, which the check below turns into a silent return. The
          // rest are indistinguishable here and treated the same way: wait and
          // resume from the cursor.
        }

        if (cancelled || stale() || terminal.current) return
        // The stream closed without a terminal event, so the build is still
        // running as far as anyone knows. Reconnect.
        setLive(false)
        setReconnecting(true)
        await sleep(backoff)
        backoff = Math.min(backoff * 2, BACKOFF_MAX_MS)
      }
    }

    void run()

    return () => {
      // `cancelled` makes anything already read inert; the abort gives the
      // connection back, whether the fetch is still pending or mid-stream.
      cancelled = true
      connection.abort()
      if (wakeTimer) clearTimeout(wakeTimer)
      wake.current = null
    }
    // `seed` is deliberately absent: it is consumed once, in the initial
    // state, and depending on it would restart the tail on every render.
  }, [slug, enabled, refreshOnTerminal, router])

  return { state, reconnecting, live, reconnect }
}
