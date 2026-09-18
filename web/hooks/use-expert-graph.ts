'use client'

import { useEffect, useState } from 'react'

import { apiJson, messageFor } from '@/lib/api/client'
import type { GraphResponse } from '@/lib/api/types'

/**
 * The concept graph, fetched when the Graph view is first opened.
 *
 * In the browser and not in the page's server render: it is up to fifteen
 * hundred nodes that three of the page's four views never draw, and switching
 * view is a `pushState`, not a navigation — there is no server round trip to
 * carry it on. It lives outside the view's own chunk because the page's search
 * reads the nodes too.
 *
 * **The last graph stays up while the next one loads**, so moving the limit
 * reheats the layout the reader is looking at rather than blanking it:
 * existing nodes keep their positions (`GraphCanvas`).
 */
export function useExpertGraph(
  slug: string,
  limit: number,
  enabled: boolean
): { graph: GraphResponse | null; error: string | null; pending: boolean } {
  const [state, setState] = useState<{
    key: string
    graph: GraphResponse | null
    error: string | null
  } | null>(null)
  const key = `${slug}:${limit}`

  useEffect(() => {
    if (!enabled) return
    let current = true
    apiJson<GraphResponse>(
      `/api/experts/${encodeURIComponent(slug)}/graph?limit=${limit}`,
      {},
      'Could not load the graph.'
    )
      .then((graph) => {
        if (current) setState({ key, graph, error: null })
      })
      .catch((error: unknown) => {
        if (current) {
          setState((previous) => ({
            key,
            graph: previous?.graph ?? null,
            error: messageFor(error, 'Could not load the graph.'),
          }))
        }
      })
    return () => {
      current = false
    }
  }, [slug, limit, enabled, key])

  return {
    graph: state?.graph ?? null,
    error: state?.key === key ? state.error : null,
    pending: enabled && state?.key !== key,
  }
}
