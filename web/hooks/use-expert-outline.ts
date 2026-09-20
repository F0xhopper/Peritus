'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { apiJson, messageFor } from '@/lib/api/client'
import type { OutlineResponse, OutlineWork } from '@/lib/api/types'

/**
 * The outline, fetched when the Outline view is first opened.
 *
 * In the browser for the Graph's reason (`useExpertGraph`): four of the page's
 * five views never draw it, and switching view is a `pushState` with no server
 * round trip to carry it on.
 */
export function useExpertOutline(
  slug: string,
  enabled: boolean
): { outline: OutlineResponse | null; error: string | null; pending: boolean } {
  const [state, setState] = useState<{
    slug: string
    outline: OutlineResponse | null
    error: string | null
  } | null>(null)

  useEffect(() => {
    if (!enabled) return
    let current = true
    apiJson<OutlineResponse>(
      `/api/experts/${encodeURIComponent(slug)}/outline`,
      {},
      'Could not load the outline.'
    )
      .then((outline) => {
        if (current) setState({ slug, outline, error: null })
      })
      .catch((error: unknown) => {
        if (current) {
          setState({ slug, outline: null, error: messageFor(error, 'Could not load the outline.') })
        }
      })
    return () => {
      current = false
    }
  }, [slug, enabled])

  const mine = state?.slug === slug ? state : null
  return {
    outline: mine?.outline ?? null,
    error: mine?.error ?? null,
    pending: enabled && mine === null,
  }
}

export type WorkSections = { work: OutlineWork; error: null } | { work: null; error: string }

/**
 * One work's sections — what each stretch of it establishes — read when the
 * work is opened.
 *
 * Apart from the outline because they are most of its weight: a few hundred
 * paragraphs on a large expert, of which a reader opens two or three works'.
 * `load` is idempotent and sets state only when a request settles, so it is safe
 * to call from an effect as well as from a click; "loading" is whatever was
 * asked for and has not come back, which the caller already knows.
 */
export function useOutlineSections(slug: string): {
  loaded: ReadonlyMap<number, WorkSections>
  load: (sourceId: number) => void
} {
  const [loaded, setLoaded] = useState<ReadonlyMap<number, WorkSections>>(new Map())
  const asked = useRef(new Set<number>())

  const load = useCallback(
    (sourceId: number) => {
      if (asked.current.has(sourceId)) return
      asked.current.add(sourceId)
      const settle = (result: WorkSections) =>
        setLoaded((previous) => new Map(previous).set(sourceId, result))
      apiJson<OutlineWork>(
        `/api/experts/${encodeURIComponent(slug)}/outline/works/${sourceId}`,
        {},
        'Could not load this work.'
      )
        .then((work) => settle({ work, error: null }))
        .catch((error: unknown) => {
          // Asked again on the next open rather than failed for the session.
          asked.current.delete(sourceId)
          settle({ work: null, error: messageFor(error, 'Could not load this work.') })
        })
    },
    [slug]
  )

  return { loaded, load }
}
