'use client'

import { startTransition, useCallback, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { seqFromId, streamSse } from '@/lib/api/sse'
import {
  isEntitlementDenial,
  type BuildEvent,
  type EntitlementDenial,
  type ExpertTier,
} from '@/lib/api/types'

/**
 * Start a build and navigate to its page.
 *
 * `POST /experts/build` answers with the event stream itself, and the very
 * first event — `created` — carries the slug the server chose. **That is the
 * only correct source of the slug.** The server walks `topic`, `topic-2`,
 * `topic-3`… stepping silently over other people's experts, so a client that
 * slugified the topic itself would navigate to someone else's expert or to a
 * 404. There is no client-side slugify anywhere in this app for that reason.
 *
 * The stream is read only far enough to find `created`; the build page reopens
 * the same durable log from `after=<seq>`, so abandoning this response loses
 * nothing.
 */

export interface StartBuildResult {
  start: (topic: string, tier: ExpertTier | null) => Promise<void>
  submitting: boolean
  /** The structured 402 body, to render as a panel rather than a toast. */
  denial: EntitlementDenial | null
  error: string | null
  clear: () => void
}

export function useStartBuild(): StartBuildResult {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)
  const [denial, setDenial] = useState<EntitlementDenial | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)

  const clear = useCallback(() => {
    setDenial(null)
    setError(null)
  }, [])

  const start = useCallback(
    async (topic: string, tier: ExpertTier | null) => {
      const trimmed = topic.trim()
      if (!trimmed || inFlight.current) return
      inFlight.current = true
      setSubmitting(true)
      setDenial(null)
      setError(null)

      try {
        const res = await fetch('/api/experts/build', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify({ topic: trimmed, tier }),
        })

        if (res.status === 402) {
          const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
          if (isEntitlementDenial(body?.detail)) {
            setDenial(body.detail)
          } else {
            setError('This build needs more credits than the account has.')
          }
          return
        }

        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
          setError(
            typeof body?.detail === 'string'
              ? body.detail
              : `Could not start the build (${res.status}).`
          )
          return
        }

        // Read until `created`, then navigate. Any other first event means the
        // client attached to a build already in flight, which is fine — the
        // log still starts at seq 0 and `created` is still in it.
        for await (const frame of streamSse<BuildEvent>(res)) {
          if (frame.data.type === 'created' && typeof frame.data.slug === 'string') {
            const url = `/experts/${encodeURIComponent(frame.data.slug)}/build?from=${seqFromId(frame.id, 1)}`
            // The push alone renders the build page but not the shell: the
            // layout's expert list was fetched before this expert existed, so
            // the rail would not show it building until a reload. The refresh
            // is queued behind the push and re-renders the layout with it.
            startTransition(() => {
              router.push(url)
              router.refresh()
            })
            return
          }
        }

        // The stream ended without a `created` event. The build may well be
        // running, but there is no slug to navigate to, so refresh: the new
        // expert will appear in the rail and on Home.
        setError('The build started but did not report which expert it belongs to. Check Home.')
        router.refresh()
      } catch {
        setError('Could not reach Peritus. Check your connection.')
      } finally {
        inFlight.current = false
        setSubmitting(false)
      }
    },
    [router]
  )

  return { start, submitting, denial, error, clear }
}
